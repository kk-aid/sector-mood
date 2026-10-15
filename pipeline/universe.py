"""유니버스 구성: 미국 상장 보통주+ADR, 시총 하한 이상, FactSet 섹터 분류.

- 소스: TradingView 스크리너 (비공식 엔드포인트, 인증 불필요)
- 월 1회 고정: data/universe/YYYY-MM.json 으로 저장하고 그 달 내내 재사용
- 실패하면 가장 최근 달 파일을 그대로 사용 (자가 복구)
"""
from __future__ import annotations

import json
from datetime import date

import requests

from . import config

TV_URL = "https://scanner.tradingview.com/america/scan"
COLUMNS = ["name", "description", "sector", "industry", "market_cap_basic",
           "close", "exchange", "type", "subtype"]
SUBTYPE_BLOCK = {"preferred", "warrant", "right", "unit", "etf", "etn", "fund",
                 "closedend", "mutual", "trust-other"}


def _fetch_tradingview() -> list[dict]:
    payload = {
        "markets": ["america"],
        "columns": COLUMNS,
        "filter": [
            {"left": "market_cap_basic", "operation": "egreater", "right": config.MIN_MCAP_USD},
            {"left": "type", "operation": "in_range", "right": list(config.SEC_TYPES)},
            {"left": "exchange", "operation": "in_range", "right": list(config.EXCHANGES)},
        ],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 8000],
        "options": {"lang": "en"},
    }
    r = requests.post(TV_URL, json=payload, timeout=60,
                      headers={"User-Agent": "Mozilla/5.0", "Origin": "https://www.tradingview.com"})
    r.raise_for_status()
    out, seen = [], set()
    for row in r.json().get("data", []):
        d = dict(zip(COLUMNS, row["d"]))
        if (d.get("subtype") or "").lower() in SUBTYPE_BLOCK:
            continue
        if d.get("sector") not in config.SECTOR_KO:
            continue
        mcap, close = d.get("market_cap_basic"), d.get("close")
        if not mcap or not close:
            continue
        tv_ticker = d["name"]
        if tv_ticker in seen:          # 중복 상장 제거
            continue
        seen.add(tv_ticker)
        out.append({
            "ticker": tv_ticker,
            "yf": tv_ticker.replace(".", "-").replace("/", "-"),   # BRK.B → BRK-B
            "name": d.get("description") or tv_ticker,
            "sector": d["sector"],
            "industry": d.get("industry") or "",
            "shares": mcap / close,      # 시총가중용 주식 수 (월중 고정)
            "mcap": mcap,
        })
    return out


def _latest_file():
    files = sorted(config.UNIVERSE_DIR.glob("*.json"))
    return files[-1] if files else None


def load_universe(force: bool = False, today: date | None = None) -> tuple[str, list[dict]]:
    """(유니버스 라벨, 종목 리스트) 반환."""
    today = today or date.today()
    label = today.strftime("%Y-%m")
    path = config.UNIVERSE_DIR / f"{label}.json"
    if path.exists() and not force:
        return label, json.loads(path.read_text())

    try:
        rows = _fetch_tradingview()
        if len(rows) < 500:
            raise RuntimeError(f"유니버스가 비정상적으로 작음: {len(rows)}종목")
        config.UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False))
        print(f"[universe] {label}: {len(rows)}종목 새로 구성")
        return label, rows
    except Exception as e:  # noqa: BLE001
        prev = _latest_file()
        if prev is None:
            raise RuntimeError(f"유니버스 수집 실패, 이전 파일도 없음: {e}") from e
        print(f"[universe] 수집 실패({e}) → 이전 파일 {prev.name} 재사용")
        return prev.stem, json.loads(prev.read_text())
