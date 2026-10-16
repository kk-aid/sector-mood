"""신고가 보강 검증 (네트워크 없이 모의 응답).  python -m tests.test_newhigh_enrich"""
import io
import json
import shutil
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from pipeline import config, newhigh, newhigh_enrich as E, synthetic

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>HT\xeb\xa1\x9c\xeb\xb3\xb4\xed\x8b\xb1\xec\x8a\xa4, \xeb\xb3\xb4\xec\x8a\xa4\xed\x84\xb4 \xec\x88\x98\xec\xa3\xbc - \xed\x95\x9c\xea\xb5\xad\xea\xb2\xbd\xec\xa0\x9c</title>
<link>https://news.google.com/a</link><pubDate>Thu, 15 Oct 2026 09:00:00 GMT</pubDate><source url="x">\xed\x95\x9c\xea\xb5\xad\xea\xb2\xbd\xec\xa0\x9c</source></item>
<item><title>\xec\x97\x89\xeb\x9a\xb1\xed\x95\x9c \xea\xb8\xb0\xec\x82\xac - A</title><link>https://news.google.com/b</link>
<pubDate>Fri, 16 Oct 2026 01:00:00 GMT</pubDate><source url="y">A</source></item>
<item><title>HT\xeb\xa1\x9c\xeb\xb3\xb4\xed\x8b\xb1\xec\x8a\xa4 \xec\x8b\xa0\xea\xb3\xa0\xea\xb0\x80 - B</title><link>https://news.google.com/c</link>
<pubDate>Fri, 16 Oct 2026 02:00:00 GMT</pubDate><source url="z">B</source></item>
</channel></rss>"""


class Resp:
    def __init__(self, content=b"", js=None, ok=True):
        self.content, self._js, self.ok, self.status_code, self.text = content, js, ok, 200 if ok else 500, ""

    def json(self):
        return self._js

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("http")


def main():
    # 1) RSS: 출처 꼬리 제거, 필수 단어 없는 기사 제외, 최신순
    items = E.parse_rss(RSS, n=3, must=["HT로보틱스"])
    assert [x["t"] for x in items] == ["HT로보틱스 신고가", "HT로보틱스, 보스턴 수주"], items
    assert items[0]["d"] == "2026-10-16" and items[1]["s"] == "한국경제"

    # 2) DART: 고유번호 zip 파싱 + 공시 목록
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", "<result><list><corp_code>00111111</corp_code><stock_code>033780</stock_code></list>"
                                   "<list><corp_code>00999999</corp_code><stock_code> </stock_code></list></result>")
    tmp = Path(tempfile.mkdtemp())
    old_root, old_nh = config.ROOT, config.NEWHIGH_ROOT
    config.ROOT, config.NEWHIGH_ROOT = tmp, tmp / "data" / "newhigh"
    try:
        orig_get = E.requests.get
        calls = []

        def fake_get(url, params=None, timeout=None, headers=None):
            calls.append(url)
            if "corpCode" in url:
                return Resp(buf.getvalue())
            if "list.json" in url:
                assert params["corp_code"] == "00111111"
                return Resp(js={"status": "000", "list": [
                    {"report_nm": "단일판매ㆍ공급계약체결  ", "rcept_no": "20261016000123", "rcept_dt": "20261016"}]})
            if "company_tickers" in url:
                return Resp(js={"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"}})
            if "submissions" in url:
                return Resp(js={"filings": {"recent": {
                    "form": ["8-K", "4", "10-Q"], "filingDate": ["2026-10-15", "2026-10-14", "2026-08-20"],
                    "accessionNumber": ["0001-26-000001", "x", "y"], "primaryDocument": ["a.htm", "b", "c"],
                    "items": ["2.02,9.01", "", ""]}}})
            raise AssertionError(url)

        E.requests.get = fake_get
        m = E.dart_corp_map("KEY")
        assert m == {"033780": "00111111"}
        assert E.dart_corp_map("KEY") == m and sum("corpCode" in c for c in calls) == 1   # 캐시 사용
        f = E.dart_filings("KEY", "00111111", date(2026, 10, 16))
        assert f[0]["t"] == "단일판매ㆍ공급계약체결" and f[0]["d"] == "2026-10-16" and "rcpNo=20261016000123" in f[0]["u"]
        # 3) SEC: 8-K 항목 번역, 기간 밖·관심 외 양식 제외
        assert E.sec_cik_map()["NVDA"] == 1045810
        s = E.sec_filings(1045810, date(2026, 10, 16))
        assert len(s) == 1 and s[0]["t"] == "8-K: 실적 발표" and s[0]["u"].endswith("/1045810/000126000001/a.htm"), s
        E.requests.get = orig_get

        # 4) 전체 흐름 (합성, 기록·사이트 파일 작성): 군집·누적·업종 흐름·사후 성과
        config.NEWHIGH_ROOT.mkdir(parents=True, exist_ok=True)
        shutil.copy(old_nh / "labels.csv", config.NEWHIGH_ROOT / "labels.csv")
        rows = synthetic.newhigh_rows("kr")
        base, ath, w52 = newhigh.pick(rows)
        labels = newhigh.load_labels()
        lab = lambda r: newhigh.label_of(r, "kr", labels)          # noqa: E731
        dn = lambda r: newhigh.display_name(r, "kr")                # noqa: E731
        # 과거 기록 하루치 (사후 성과·누적용)
        newhigh.record("kr", date(2026, 10, 15), ath[:5], w52[:5], labels, "sig0")
        out = E.run("kr", date(2026, 10, 16), ath, w52, lab, dn, synthetic=True, out_png=tmp / "png")
        assert out["clusters"] and all(cl["n"] >= 1 for cl in out["clusters"])
        cl0 = out["clusters"][0]
        assert cl0["n"] >= config.NEWHIGH_CLUSTER_MIN and cl0["n5"] >= cl0["n"]
        assert len(out["charts"]) == min(config.NEWHIGH_CHART_MAX, len(out["clusters"]))
        assert all(Path(p).stat().st_size > 10_000 for p, _ in out["charts"])
        assert all(out["notes"][cl["label"]] for cl in out["clusters"])
        site = tmp / "docs" / "data" / "kr" / "newhigh"
        doc = json.loads((site / "2026-10-16.json").read_text())
        idx = json.loads((site / "index.json").read_text())
        assert idx["days"] == ["2026-10-16"] and sum(idx["counts"]["2026-10-16"].values()) == len(ath) + len(w52)
        st = doc["stocks"][0]
        assert st["chart"]["c"][-1] == 1000 and st["chart"]["step"] == 2 and st["news"]
        assert len(doc["follow"]) == 10 and all("ret" in r for r in doc["follow"])
        # 누적: 어제 기록된 종목은 오늘 다시 나와도 한 번만 셈
        any_label = doc["follow"][0]["label"]
        today_codes = {s["code"] for s in doc["stocks"] if s["label"] == any_label}
        past_codes = {r["code"] for r in doc["follow"] if r["label"] == any_label}
        assert doc["cum5"][any_label] == len(today_codes | past_codes)

        # 5) 메시지: 기존 형식 유지 + 군집 줄·재료 줄·링크
        out["url"] = "https://kk-aid.github.io/sector-mood/#kr/newhigh/2026-10-16"
        msg = newhigh.build_message("kr", date(2026, 10, 16), ath, w52, labels, out)
        plain = newhigh.build_message("kr", date(2026, 10, 16), ath, w52, labels)
        for line in plain.split("\n"):
            assert line in msg, line                                     # 기존 줄은 하나도 빠지지 않음
        assert "🔥 군집:" in msg and "└ " in msg and "차트·재료 전체 보기" in msg
        assert msg.count("<a ") == msg.count("</a>") and msg.count("<b>") == msg.count("</b>")
        assert all(len(p) < 4096 for p in newhigh.split_message(msg))

        # 6) 보존 기한: 오래된 일별 파일 정리
        for i in range(config.NEWHIGH_SITE_KEEP_DAYS + 3):
            (site / f"2026-0{1 + i // 28}-{1 + i % 28:02d}.json").write_text("{}")
        E._write_site("kr", date(2026, 10, 17), [], {}, {}, {}, {}, {}, [], {5: {}, 20: {}}, [], {}, dn)
        assert len(list(site.glob("20*.json"))) == config.NEWHIGH_SITE_KEEP_DAYS
    finally:
        config.ROOT, config.NEWHIGH_ROOT = old_root, old_nh
        shutil.rmtree(tmp, ignore_errors=True)
    print("test_newhigh_enrich: OK")


if __name__ == "__main__":
    main()
