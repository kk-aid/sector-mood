"""설정값 모음. 숫자 기준을 바꾸고 싶으면 여기만 고치면 됨."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_ROOT = DOCS / "data"              # 시장별 하위 폴더: docs/data/us, kr, jp
UNIVERSE_ROOT = ROOT / "data" / "universe"

# ── 시장 정의 ────────────────────────────────────────────
# min_mcap 은 각 시장 현지 통화 기준. yf: yfinance 심볼 접미사 (kr 은 .KS 실패 시 .KQ 재시도)
MARKETS = {
    "us": {
        "label": "미국", "flag": "🇺🇸", "tv": "america", "exchanges": ("NASDAQ", "NYSE", "AMEX"),
        "min_mcap": 1e9, "currency": "달러", "tz": "America/New_York", "close": (16, 20),
        "min_count": 500, "yf": "", "yf_alt": None, "events": "us",
    },
    "kr": {
        "label": "한국", "flag": "🇰🇷", "tv": "korea", "exchanges": None,
        "min_mcap": 3e11, "currency": "원", "tz": "Asia/Seoul", "close": (15, 45),
        "min_count": 150, "yf": ".KS", "yf_alt": ".KQ", "events": "kr",
    },
    "jp": {
        "label": "일본", "flag": "🇯🇵", "tv": "japan", "exchanges": ("TSE",),
        "min_mcap": 1e11, "currency": "엔", "tz": "Asia/Tokyo", "close": (15, 45),
        "min_count": 300, "yf": ".T", "yf_alt": None, "events": "jp",
    },
}
SEC_TYPES = ("stock", "dr")       # 보통주 + 예탁증서(ADR)

# ── 계산 창 ──────────────────────────────────────────────
TURNOVER_LOOKBACK = 20            # 거래대금 비교 기준: 직전 20거래일 평균
SIGMA_LOOKBACK = 60               # z-score용 업종 상대수익률 표준편차 창
PRICE_HISTORY = "2y"              # yfinance 다운로드 기간 (연초 시총 순위·백필 여유)
RET_CLIP = 0.5                    # 동일가중 계산 시 일간 수익률 ±50% 클리핑 (데이터 오류 방어)
MARKET_SPIKE = 1.4                # 시장 전체 거래대금이 20일 평균의 1.4배 이상이면 이벤트일 플래그
BACKFILL_WEEKS = 26               # 데이터가 없을 때 자동 백필 주 수
# ── 분석 (history / signals / trend) ────────────────────
HISTORY_WEEKS = 52                # 주간 이력 보관 주 수
HISTORY_INDUSTRY_MIN_N = 3        # 이력·로테이션에 포함할 산업 최소 종목 수
SIGNAL_INDUSTRY_MIN_N = 5         # 신호 검증에 포함할 산업 최소 종목 수
RRG_TREND = 10                    # 로테이션: RS 추세 = RS ÷ 10주 평균 RS
RRG_MOM = 4                       # 로테이션: RS 모멘텀 = RS 추세의 4주 변화
DAILY_MAS = [5, 20, 60, 120, 200] # 일봉 이평
WEEKLY_MAS = [10, 20, 30, 40]     # 주봉 이평
STAGE_FLAT = 0.01                 # Stage: 30주선 4주 기울기 ±1% 이내면 횡보

INDUSTRY_MIN_N = 2                # 산업 단위 집계에 포함할 최소 종목 수 (화면에서 더 높게 거를 수 있음)

# ── 규모와 쏠림 ──────────────────────────────────────────
SIZE_BUCKETS = [(1, 10, "초대형 10"), (11, 100, "11–100위"), (101, 500, "101–500위"), (501, None, "501위 이하")]
CONCENTRATION_TOP = 10            # 쏠림: 그날 거래대금 상위 N종목 몫

# ── 텔레그램 알림 판정 기준 (화면 기본값과 동일) ─────────
NOTIFY_WEIGHT = "cw"              # cw=시총가중, ew=동일가중
NOTIFY_MODE = "fixed"             # fixed=고정 %p, sigma=변동성 σ
NOTIFY_TURN = "tv"                # tv=거래대금, vr=거래량
NOTIFY_THR = {"dR": 1.0, "wR": 2.0, "zR": 1.0, "dT": 1.10, "wT": 1.05}
NOTIFY_TOP_STOCKS = 3             # 거래 몰린 업종마다 함께 보여줄 대형 종목 수

# ── 업종 이름 (FactSet 20개 섹터 → 한국어) ───────────────
SECTOR_KO = {
    "Commercial Services": "상업 서비스",
    "Communications": "커뮤니케이션",
    "Consumer Durables": "소비자 내구재",
    "Consumer Non-Durables": "소비재 비내구재",
    "Consumer Services": "소비자 서비스",
    "Distribution Services": "유통 서비스",
    "Electronic Technology": "전자 기술",
    "Energy Minerals": "에너지 광물",
    "Finance": "금융",
    "Health Services": "보건 서비스",
    "Health Technology": "의료 기술",
    "Industrial Services": "산업 서비스",
    "Miscellaneous": "기타",
    "Non-Energy Minerals": "비에너지 광물",
    "Process Industries": "공정 산업",
    "Producer Manufacturing": "생산자 제조",
    "Retail Trade": "소매업",
    "Technology Services": "기술 서비스",
    "Transportation": "운송",
    "Utilities": "유틸리티",
}


def market(key: str) -> dict:
    if key not in MARKETS:
        raise SystemExit(f"알 수 없는 시장: {key} (가능: {', '.join(MARKETS)})")
    return {"key": key, **MARKETS[key]}
