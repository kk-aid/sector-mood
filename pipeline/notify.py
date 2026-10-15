"""텔레그램 아침 알림.

  python -m pipeline.notify --market kr  # 전송 (환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 필요)
  python -m pipeline.notify --dry-run  # 전송 없이 메시지만 출력
  python -m pipeline.notify --fail URL # 갱신 실패 알림

판정 기준은 config.NOTIFY_* (화면 기본값과 같음).
"""
from __future__ import annotations

import argparse
import html
import json
import os
from datetime import date

import requests

from . import config

CAT = {
    "hu": ("🟥", "거래 몰린 상승"), "qu": ("🩷", "조용한 상승"), "ch": ("🟨", "손바뀜"),
    "ca": ("⬜", "소강"), "ou": ("🩵", "관심 이탈"), "hd": ("🟦", "거래 몰린 하락"),
}
ORDER = ["hu", "qu", "ch", "ou", "hd"]
WD = "월화수목금토일"


def classify(o: dict, is_week: bool) -> tuple[str | None, float | None, float | None, float | None]:
    """(분류, 상대등락 %p, z, 상대거래) 반환. 화면의 classify() 와 같은 규칙."""
    cw = config.NOTIFY_WEIGHT == "cw"
    rel, sig = (o.get("rc"), o.get("sc")) if cw else (o.get("re"), o.get("se"))
    turn = o.get(config.NOTIFY_TURN)
    z = rel / sig if rel is not None and sig else None
    if rel is None or turn is None:
        return None, rel, z, turn
    t = config.NOTIFY_THR
    if config.NOTIFY_MODE == "sigma":
        x, thr = z, t["zR"]
    else:
        x, thr = rel, (t["wR"] if is_week else t["dR"])
    hi = turn >= (t["wT"] if is_week else t["dT"])
    if x is None:
        c = "ch" if hi else "ca"
    elif x >= thr:
        c = "hu" if hi else "qu"
    elif x <= -thr:
        c = "hd" if hi else "ou"
    else:
        c = "ch" if hi else "ca"
    return c, rel, z, turn


def _load_weeks(mkt: str):
    base = config.DATA_ROOT / mkt
    idx = json.loads((base / "index.json").read_text())
    def wk(k):
        return json.loads((base / "weeks" / f"{k}.json").read_text())
    cur = wk(idx["weeks"][-1])
    prev = wk(idx["weeks"][-2]) if len(idx["weeks"]) > 1 else None
    return idx, cur, prev


def _f(x, d=1):
    return "–" if x is None else f"{x:+.{d}f}"


def _site_url():
    repo = os.environ.get("GITHUB_REPOSITORY")      # owner/repo (Actions 가 자동 제공)
    if not repo:
        return None
    owner, name = repo.split("/")
    return f"https://{owner}.github.io/{name}/"


def build_message(mkt: str = "us") -> str:
    m = config.market(mkt)
    idx, W, P = _load_weeks(mkt)
    e = html.escape
    day = W["days"][-1]
    d = date.fromisoformat(day)
    # 전일: 같은 주 앞날, 없으면 지난주 마지막 날
    if len(W["days"]) > 1:
        prev_day, prev_src = W["days"][-2], W
    elif P:
        prev_day, prev_src = P["days"][-1], P
    else:
        prev_day, prev_src = None, None

    wkey = config.NOTIFY_WEIGHT
    mk = W["market"]["day"][day]
    lines = [f"<b>{m['flag']} {m['label']} 업종 심리 · {d.month}/{d.day}({WD[d.weekday()]})</b>",
             f"시장 {_f(mk[wkey], 2)}% · 거래대금 {mk['tv']:.2f}배 "
             f"({'시총' if wkey == 'cw' else '동일'}가중)"]
    if W.get("events", {}).get(day):
        lines.append("⚑ " + e(" · ".join(W["events"][day])) + " (상대 거래 수치 왜곡 가능)")

    # 종목 테이블 (대형 거래 종목 표시용)
    cols = W["stocks"]["cols"]
    ci = {c: i for i, c in enumerate(cols)}
    sec_list = W["stocks"]["sectors"]
    pos = W["days"].index(day)

    groups = {k: [] for k in CAT}
    today_cls = {}
    for s in W["sectors"]:
        c, rel, z, turn = classify(s["day"][day], False)
        if c is None:
            continue
        today_cls[s["key"]] = c
        groups[c].append((s, rel, z, turn))

    def top_names(sector_key):
        si = sec_list.index(sector_key)
        rows = [r for r in W["stocks"]["rows"] if r[ci["sector"]] == si and r[ci["days"]][pos] is not None]
        rows.sort(key=lambda r: -(r[ci["share"]] or 0))
        def label(r):
            if mkt == "us":
                return r[ci["ticker"]]
            nm = r[ci["name"]]
            return nm if len(nm) <= 10 else nm[:9] + "…"
        return ", ".join(f"{e(label(r))} {_f(r[ci['days']][pos])}"
                         for r in rows[:config.NOTIFY_TOP_STOCKS])

    sigma = config.NOTIFY_MODE == "sigma"
    for k in ORDER:
        items = groups[k]
        if not items:
            continue
        items.sort(key=lambda x: -(x[1] or 0) if k in ("hu", "qu", "ch") else (x[1] or 0))
        icon, name = CAT[k]
        lines.append("")
        lines.append(f"<b>{icon} {name}</b>")
        for s, rel, z, turn in items:
            zt = f" ({_f(z)}σ)" if sigma and z is not None else ""
            lines.append(f"  {e(s['name'])} {_f(rel)}%p{zt} · {turn:.2f}배")
            if k in ("hu", "hd"):
                lines.append(f"    └ {top_names(s['key'])}")
    if groups["ca"]:
        lines.append("")
        lines.append(f"{CAT['ca'][0]} 소강 {len(groups['ca'])}개 업종")

    # 전일 대비 전환
    if prev_day:
        changes = []
        for s in prev_src["sectors"]:
            if s["key"] not in today_cls or prev_day not in s["day"]:
                continue
            pc, *_ = classify(s["day"][prev_day], False)
            nc = today_cls[s["key"]]
            if pc and pc != nc and nc != "ca":
                changes.append(f"  {e(s['name'])}: {CAT[pc][1]} → <b>{CAT[nc][1]}</b>")
        if changes:
            lines.append("")
            lines.append("<b>🔄 전일 대비 전환</b>")
            lines.extend(changes[:8])

    # 주간 누적
    ranked = []
    for s in W["sectors"]:
        c, rel, z, turn = classify(s["week"], True)
        if rel is not None:
            ranked.append((rel, s["name"], c))
    ranked.sort(reverse=True)
    n = len(W["days"])
    span = "월" if n == 1 else f"월~{WD[d.weekday()]}"
    if ranked:
        lines.append("")
        lines.append(f"<b>📅 주간 누적 ({span}, {n}일)</b>")
        lines.append("  상위: " + ", ".join(f"{e(nm)} {_f(r)}%p" for r, nm, _ in ranked[:3]))
        lines.append("  하위: " + ", ".join(f"{e(nm)} {_f(r)}%p" for r, nm, _ in ranked[-3:][::-1]))

    # 산업 단위: 오늘 거래 몰린 상승·하락 상위 (종목 수 충분한 산업만)
    hot_up, hot_dn = [], []
    for g in W.get("industries", []):
        if g["n"] < config.SIGNAL_INDUSTRY_MIN_N or day not in g["day"]:
            continue
        c, rel, z, turn = classify(g["day"][day], False)
        if c == "hu":
            hot_up.append((rel, g, turn))
        elif c == "hd":
            hot_dn.append((rel, g, turn))
    if hot_up or hot_dn:
        lines.append("")
        lines.append(f"<b>🏭 산업 ({config.SIGNAL_INDUSTRY_MIN_N}종목 이상)</b>")
        for rel, g, turn in sorted(hot_up, key=lambda x: -x[0])[:3]:
            lines.append(f"  🟥 {e(g['name'])} {_f(rel)}%p · {turn:.2f}배")
        for rel, g, turn in sorted(hot_dn, key=lambda x: x[0])[:3]:
            lines.append(f"  🟦 {e(g['name'])} {_f(rel)}%p · {turn:.2f}배")

    # 추세·폭
    tp = config.DATA_ROOT / mkt / "trend.json"
    if tp.exists():
        T = json.loads(tp.read_text())
        M, n_all = T["market"], T["market"]["n"]
        cols = {c: i for i, c in enumerate(T["stocks"]["cols"])}
        rows = T["stocks"]["rows"]
        new_up = sorted([r for r in rows if r[cols["d_change"]] == 1], key=lambda r: -(r[cols["mcap"]] or 0))
        lost = sum(1 for r in rows if r[cols["d_change"]] == -1)

        def nm(r):
            if mkt == "us":
                return r[cols["ticker"]]
            x = r[cols["name"]]
            return x if len(x) <= 10 else x[:9] + "…"
        a50, a50p = M.get("a50"), M.get("a50_prev")
        lines.append("")
        lines.append("<b>🧭 추세·폭</b>")
        lines.append(f"  50일선 위 {a50}%" + (f" (1주 전 {a50p}%)" if a50p is not None else "")
                     + f" · Stage 2 {M['stage']['2'] / n_all * 100:.0f}% · 8/8 {M['tt']}종목")
        lines.append(f"  52주 신고가 {M['nh']} · 신저가 {M['nl']} · 완전 정배열 신규 {len(new_up)} / 이탈 {lost}")
        if new_up:
            lines.append("  └ 신규: " + ", ".join(e(nm(r)) for r in new_up[:5]))

    url = _site_url()
    if url:
        lines.append("")
        lines.append(f'<a href="{url}#{mkt}/{W["week"]}">🔗 전체 지도 보기</a>')
    # 텔레그램 한도 4096자: 태그가 잘리지 않도록 줄 단위로 줄임
    while len("\n".join(lines)) > 4000 and len(lines) > 5:
        lines.pop(-3 if url else -1)
    return "\n".join(lines)


def send(text: str):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[notify] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없어 전송 생략")
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    if not r.ok:
        raise RuntimeError(f"텔레그램 전송 실패 {r.status_code}: {r.text[:300]}")
    print("[notify] 전송 완료")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="us", choices=list(config.MARKETS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fail", metavar="RUN_URL")
    a = ap.parse_args()
    if a.fail:
        text = f"⚠️ <b>업종 심리 지도 갱신 실패</b>\n<a href=\"{html.escape(a.fail)}\">실행 로그 보기</a>"
    else:
        text = build_message(a.market)
    if a.dry_run:
        print(text)
    else:
        send(text)


if __name__ == "__main__":
    main()
