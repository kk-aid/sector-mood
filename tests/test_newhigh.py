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
    from unittest.mock import patch
    cache = patch("pipeline.taxonomy.toss_rows", return_value=({}, None))
    cache.start()
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

    # 순위 제한 없음(기본): 상승 종목 전체에서 신고가. 상위 5 밖이던 I(+4%) 포함, 하락 J·우선주 F·스팩 G 제외
    base_all, ath_all, w52_all = newhigh.pick(rows)
    assert [r["name"] for r in ath_all] == ["A", "E", "H", "I"], [r["name"] for r in ath_all]
    assert [r["name"] for r in w52_all] == ["B"], [r["name"] for r in w52_all]
    assert len(base_all) == 7 and base_all[-1]["name"] == "I" and base_all[-1]["rank"] == 7
    assert config.NEWHIGH["kr"]["top_n"] is None

    # 진단 문구
    codes = {r["name"] for r in base}
    assert newhigh.explain(rows[8], codes, 5).startswith("제외: 상승률 상위 5 밖")
    assert newhigh.explain(rows[8], {r["name"] for r in base_all}, None).startswith("포함: 역대 신고가")
    assert newhigh.explain(rows[3], codes, 5).startswith("제외: 양봉 아님")
    assert newhigh.explain(rows[2], codes, 5).startswith("제외: 장중 고가가 52주 고가 미달")
    assert newhigh.explain(rows[9], codes, 5).startswith("제외: 상승 마감 아님")
    assert newhigh.explain(rows[6], codes, 5).startswith("제외: 우선주·스팩")

    # 긴 메시지 분할: 각 조각 4096자 미만, 내용 손실 없음
    many = [row(f"X{i:03d}", 5 + i / 100, 105, 100, 106, 106, 106, description=f"종목{i:03d}",
                industry=f"Ind{i % 40}") for i in range(400)]
    _, ath_m, _ = newhigh.pick(many)
    long = newhigh.build_message("kr", date(2026, 10, 15), ath_m, [], {})
    parts = newhigh.split_message(long)
    assert len(long) > 4096 and len(parts) > 1 and all(len(p) < 4096 for p in parts)
    assert parts[1].startswith(f"(2/{len(parts)})")
    joined = "".join(parts)
    assert all(f"종목{i:03d}" in joined for i in range(400))
    one = newhigh.split_message("짧은 메시지")
    assert one == ["짧은 메시지"]

    # 업종은 승인 분류 또는 공급자 산업. 기존 테마·규모가 덮어쓰지 않음
    labels = {("kr", "A"): "후공정·OSAT·장비"}
    assert newhigh.label_of(rows[0], "kr", labels) == "토스 미등록"
    small = row("Z", 5, 1, 1, 1, 1, 1, market_cap_basic=3e10)
    assert newhigh.label_of(small, "kr", {}) == "토스 미등록"
    assert newhigh.size_tag(small, "kr") == " [소형주]"
    assert newhigh.label_of(small, "us", {}) == "토스 미등록"          # 미국은 소형주 묶음 없음
    assert newhigh.label_of({**rows[1], "industry": "Unknown X"}, "kr", {}) == "토스 미등록"
    assert newhigh.display_name({"name": "005930", "description": "삼성전자보통주"}, "kr") == "삼성전자"

    # 메시지: 같은 라벨은 한 줄, 등락률 높은 그룹 먼저
    msg = newhigh.build_message("kr", date(2026, 10, 15), ath, w52, labels)
    assert "2026.10.15(목)" in msg and "🏆 역대 신고가 2" in msg and "52주 신고가 1" in msg
    assert "(토스 미등록) A +10.0%" in msg and "E +6.0%" in msg
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
        assert len(base) > 70 and ath and w52                  # 순위 제한 없음 → 합성 상승 종목 전체가 기준
        assert not any("스팩" in (r["description"] or "") or r["name"] == "999003" for r in ath + w52)
        msg = newhigh.build_message(mkt, date(2026, 10, 15), ath, w52, labels)
        assert all(len(p) < 4096 for p in newhigh.split_message(msg))
        assert "상승률 상위" not in msg
    cache.stop()
    print("test_newhigh: OK")


if __name__ == "__main__":
    main()
