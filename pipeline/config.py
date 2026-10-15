"""설정값 모음. 숫자 기준을 바꾸고 싶으면 여기만 고치면 됨."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA_OUT = DOCS / "data"
UNIVERSE_DIR = ROOT / "data" / "universe"

# ── 유니버스 ─────────────────────────────────────────────
MIN_MCAP_USD = 1_000_000_000      # 시총 하한 (월 1회 고정)
EXCHANGES = ("NASDAQ", "NYSE", "AMEX")
SEC_TYPES = ("stock", "dr")       # 보통주 + ADR

# ── 계산 창 ──────────────────────────────────────────────
TURNOVER_LOOKBACK = 20            # 거래대금 비교 기준: 직전 20거래일 평균
SIGMA_LOOKBACK = 60               # z-score용 업종 상대수익률 표준편차 창
PRICE_HISTORY = "9mo"             # yfinance 다운로드 기간 (백필 여유 포함)
RET_CLIP = 0.5                    # 동일가중 계산 시 일간 수익률 ±50% 클리핑 (데이터 오류 방어)
MARKET_SPIKE = 1.4                # 시장 전체 거래대금이 20일 평균의 1.4배 이상이면 이벤트일 플래그

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
