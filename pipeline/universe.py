"""유니버스 구성: 시장별 보통주(+ADR), 시총 하한 이상, FactSet 섹터 분류.

- 소스: TradingView 스크리너 (비공식 엔드포인트, 인증 불필요)
- 영어 응답(섹터 판정용)과 한국어 응답(종목명·산업명 표시용)을 따로 받아 합침
- 월 1회 고정: data/universe/<시장>/YYYY-MM.json 으로 저장하고 그 달 내내 재사용
- 실패하면 가장 최근 달 파일을 그대로 사용 (자가 복구)
"""
from __future__ import annotations

import json
from datetime import date

import requests

from . import config

COLUMNS = ["name", "description", "sector", "industry", "market_cap_basic",
           "close", "exchange", "type", "subtype"]
SUBTYPE_BLOCK = {"preferred", "warrant", "right", "unit", "etf", "etn", "fund",
                 "closedend", "mutual", "trust-other"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.tradingview.com"}


def _scan(m: dict, lang: str, columns: list[str]) -> list[dict]:
    flt = [
        {"left": "market_cap_basic", "operation": "egreater", "right": m["min_mcap"]},
        {"left": "type", "operation": "in_range", "right": list(config.SEC_TYPES)},
    ]
    payload = {
        "markets": [m["tv"]], "columns": columns, "filter": flt,
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 8000], "options": {"lang": lang},
    }
    r = requests.post(f"https://scanner.tradingview.com/{m['tv']}/scan", json=payload,
                      timeout=60, headers=HEADERS)
    r.raise_for_status()
    return [{"s": row["s"], **dict(zip(columns, row["d"]))} for row in r.json().get("data", [])]


def _yf_symbol(m: dict, tv_name: str) -> tuple[str, str | None]:
    if m["key"] == "us":
        return tv_name.replace(".", "-").replace("/", "-"), None
    alt = tv_name + m["yf_alt"] if m["yf_alt"] else None
    return tv_name + m["yf"], alt


def _fetch(m: dict) -> list[dict]:
    rows = _scan(m, "en", COLUMNS)
    # 한국어 이름·산업 (실패해도 영어로 진행)
    ko = {}
    try:
        for r in _scan(m, "ko", ["name", "description", "industry"]):
            ko[r["s"]] = r
    except Exception as e:  # noqa: BLE001
        print(f"[universe:{m['key']}] 한국어 이름 수집 실패 → 영어 사용 ({e})")

    exch = m["exchanges"]
    if exch and sum(1 for d in rows if d.get("exchange") in exch) >= m["min_count"]:
        rows = [d for d in rows if d.get("exchange") in exch]

    out, seen = [], set()
    for d in rows:
        if (d.get("subtype") or "").lower() in SUBTYPE_BLOCK:
            continue
        if d.get("sector") not in config.SECTOR_KO:
            continue
        mcap, close = d.get("market_cap_basic"), d.get("close")
        if not mcap or not close:
            continue
        tv_ticker = d["name"]
        if tv_ticker in seen:               # 중복 상장 제거 (시총 내림차순이라 첫 항목 유지)
            continue
        seen.add(tv_ticker)
        k = ko.get(d["s"], {})
        yf, yf_alt = _yf_symbol(m, tv_ticker)
        name_en = d.get("description") or tv_ticker
        out.append({
            "ticker": tv_ticker,
            "yf": yf, "yf_alt": yf_alt,
            "name": name_en if m["key"] == "us" else (k.get("description") or name_en),
            "name_en": name_en,
            "sector": d["sector"],
            "industry": k.get("industry") or d.get("industry") or "",
            "industry_en": d.get("industry") or "",
            "shares": mcap / close,          # 시총가중용 주식 수 (월중 고정)
            "mcap": mcap,
        })
    return out


def _latest_file(mkt: str):
    files = sorted((config.UNIVERSE_ROOT / mkt).glob("*.json"))
    if not files and mkt == "us":                       # 구버전 경로 호환
        files = sorted(config.UNIVERSE_ROOT.glob("*.json"))
    return files[-1] if files else None


def load_universe(mkt: str, force: bool = False, today: date | None = None) -> tuple[str, list[dict]]:
    """(유니버스 라벨, 종목 리스트) 반환."""
    m = config.market(mkt)
    today = today or date.today()
    label = today.strftime("%Y-%m")
    path = config.UNIVERSE_ROOT / mkt / f"{label}.json"
    if path.exists() and not force:
        return label, json.loads(path.read_text())

    try:
        rows = _fetch(m)
        if len(rows) < m["min_count"]:
            raise RuntimeError(f"유니버스가 비정상적으로 작음: {len(rows)}종목")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False))
        print(f"[universe:{mkt}] {label}: {len(rows)}종목 새로 구성")
        return label, rows
    except Exception as e:  # noqa: BLE001
        prev = _latest_file(mkt)
        if prev is None:
            raise RuntimeError(f"[{mkt}] 유니버스 수집 실패, 이전 파일도 없음: {e}") from e
        print(f"[universe:{mkt}] 수집 실패({e}) → 이전 파일 {prev.name} 재사용")
        rows = json.loads(prev.read_text())
        for u in rows:                                  # 구버전 파일 보정
            u.setdefault("yf_alt", None)
            u.setdefault("name_en", u.get("name"))
            u.setdefault("industry_en", u.get("industry"))
        return prev.stem, rows
