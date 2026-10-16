"""신고가 알림 검증.  python -m tests.test_newhigh"""
import tempfile
from datetime import date
from pathlib import Path

from pipeline import config, newhigh, synthetic


def row(code, chg, close, open_, high, ath, w52, **kw):
    return {"name": code, "description": code, "close": close, "open": open_, "high": high,
            "change": chg, "market_cap_basic": 1e12, "High.All": ath, "price_52_week_high": w52,
            "industry": "Semiconductors", "type": "stock", "subtype": "common", **kw}


def main():
    rows = [
        row("A", 10, 110, 100, 112, 112, 112),             # 역대 신고가
        row("B", 9, 109, 100, 110, 200, 110),              # 52주만
        row("C", 8, 108, 100, 109, 200, 150),              # 신고가 아님
        row("D", 7, 100, 105, 110, 110, 110),              # 음봉 → 제외
        row("E", 6, 106, 100, 107, 107.005, 107),          # 반올림 오차 범위 → 역대 신고가
        row("F", 30, 130, 100, 131, 131, 131, subtype="preferred"),   # 우선주 → 순위에서 제외
        row("G", 29, 129, 100, 130, 130, 130, description="가나스팩3호"),  # 스팩 → 제외
        row("H", 5, 105, 100, 106, 106, None),             # 52주 값 없음, 역대는 충족
        row("I", 4, 104, 100, 105, 105, 105),              # 상위 5 밖 → 제외
        row("J", -1, 99, 100, 101, 101, 101),              # 하락 → 제외
    ]
    base, ath, w52 = newhigh.pick(rows, top_n=5)
    assert [r["name"] for r in base] == ["A", "B", "C", "D", "E"], [r["name"] for r in base]
    assert [r["name"] for r in ath] == ["A", "E"], [r["name"] for r in ath]
    assert [r["name"] for r in w52] == ["B"], [r["name"] for r in w52]
    assert base[0]["rank"] == 1 and base[4]["rank"] == 5

    # 라벨: labels.csv → 소형주 → 산업 한국어
    labels = {("kr", "A"): "후공정·OSAT·장비"}
    assert newhigh.label_of(rows[0], "kr", labels) == "후공정·OSAT·장비"
    small = row("Z", 5, 1, 1, 1, 1, 1, market_cap_basic=3e10)
    assert newhigh.label_of(small, "kr", {}) == config.NEWHIGH["kr"]["small_label"]
    assert newhigh.label_of(small, "us", {}) == "반도체"          # 미국은 소형주 묶음 없음
    assert newhigh.label_of({**rows[1], "industry": "Unknown X"}, "kr", {}) == "Unknown X"
    assert newhigh.display_name({"name": "005930", "description": "삼성전자보통주"}, "kr") == "삼성전자"

    # 메시지: 같은 라벨은 한 줄, 등락률 높은 그룹 먼저
    msg = newhigh.build_message("kr", date(2026, 10, 15), ath, w52, labels)
    assert "2026.10.15(목)" in msg and "🏆 역대 신고가 2" in msg and "52주 신고가 1" in msg
    assert "(후공정·OSAT·장비) A +10.0%" in msg and "(반도체) E +6.0%" in msg
    empty = newhigh.build_message("us", date(2026, 10, 15), [], [], {})
    assert "조건을 충족한 종목 없음" in empty

    # 기록: 같은 날 재실행 시 교체, 서명으로 휴장일 중복 판단
    with tempfile.TemporaryDirectory() as tmp:
        old = config.NEWHIGH_ROOT
        config.NEWHIGH_ROOT = Path(tmp)
        try:
            sig = newhigh.signature(base)
            assert newhigh.last_sig("kr") is None
            newhigh.record("kr", date(2026, 10, 15), ath, w52, labels, sig)
            newhigh.record("kr", date(2026, 10, 15), ath, w52, labels, sig)
            lines = (Path(tmp) / "kr" / "2026-10.csv").read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1 + 3, lines                # 헤더 + 3행 (중복 없음)
            assert newhigh.last_sig("kr") == sig
            assert newhigh.signature(base[:-1]) != sig
        finally:
            config.NEWHIGH_ROOT = old

    # 합성 데이터 전체 흐름 + 실제 labels.csv 로드
    labels = newhigh.load_labels()
    assert labels.get(("kr", "042700")) and labels.get(("us", "NVDA")) and labels.get(("jp", "6857"))
    for mkt in config.MARKETS:
        base, ath, w52 = newhigh.pick(synthetic.newhigh_rows(mkt), config.NEWHIGH[mkt]["top_n"])
        assert len(base) == config.NEWHIGH[mkt]["top_n"] and ath and w52
        assert not any("스팩" in (r["description"] or "") or r["name"] == "999003" for r in ath + w52)
        msg = newhigh.build_message(mkt, date(2026, 10, 15), ath, w52, labels)
        assert len(msg) < 4096
    print("test_newhigh: OK")


if __name__ == "__main__":
    main()
