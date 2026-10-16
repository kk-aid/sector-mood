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
# ── 신고가 알림 (pipeline/newhigh.py) ────────────────────
# 그날 상승·양봉 마감 + 장중 신고가(당일 고가 ≥ 기준 고가)인 종목을 모두 뽑음.
# top_n: None 이면 상승률 순위 제한 없음. 숫자를 넣으면 그날 상승률 상위 N 안에서만 찾음.
# min_mcap·min_value 는 현지 통화. small_cap 미만은 small_label 로 묶음(None 이면 안 묶음).
NEWHIGH = {
    "kr": {"top_n": None, "min_mcap": 0, "min_value": 0, "small_cap": 5e10,
           "small_label": "소형주·시총500억↓", "lang": "ko"},
    "us": {"top_n": None, "min_mcap": 3e8, "min_value": 5e6, "small_cap": None,
           "small_label": None, "lang": "en"},
    "jp": {"top_n": None, "min_mcap": 1e10, "min_value": 1e8, "small_cap": None,
           "small_label": None, "lang": "en"},
}
NEWHIGH_TOL = 1e-4                    # 고가가 기준 고가의 99.99% 이상이면 신고가로 봄 (반올림 오차 흡수)
NEWHIGH_EXCLUDE = ("스팩", "SPAC", "Acquisition Corp", "Acquisition Corporation")
NEWHIGH_ROOT = ROOT / "data" / "newhigh"   # labels.csv(섹터 라벨, 직접 수정 가능) · 시장별 기록

# FactSet 산업 → 한국어 (labels.csv 에 없는 종목의 섹터 라벨)
INDUSTRY_KO = {
    "Advertising/Marketing Services": "광고·마케팅", "Aerospace & Defense": "방산·우주",
    "Agricultural Commodities/Milling": "농산물", "Air Freight/Couriers": "항공화물·택배",
    "Airlines": "항공사", "Alternative Power Generation": "신재생 발전", "Aluminum": "알루미늄",
    "Apparel/Footwear": "의류·신발", "Apparel/Footwear Retail": "의류 소매",
    "Auto Parts: OEM": "자동차 부품", "Automotive Aftermarket": "자동차 애프터마켓",
    "Beverages: Alcoholic": "주류", "Beverages: Non-Alcoholic": "음료", "Biotechnology": "바이오",
    "Broadcasting": "방송", "Building Products": "건자재", "Cable/Satellite TV": "케이블·위성방송",
    "Casinos/Gaming": "카지노·게임", "Chemicals: Agricultural": "농화학",
    "Chemicals: Major Diversified": "화학", "Chemicals: Specialty": "특수화학", "Coal": "석탄",
    "Commercial Printing/Forms": "인쇄", "Computer Communications": "네트워크 장비",
    "Computer Peripherals": "컴퓨터 주변기기", "Computer Processing Hardware": "컴퓨터 하드웨어",
    "Construction Materials": "건설자재", "Consumer Sundries": "생활잡화",
    "Containers/Packaging": "포장재", "Contract Drilling": "시추", "Data Processing Services": "데이터 처리",
    "Department Stores": "백화점", "Discount Stores": "할인점", "Drugstore Chains": "드럭스토어",
    "Electric Utilities": "전력", "Electrical Products": "전기장비", "Electronic Components": "전자부품",
    "Electronic Equipment/Instruments": "전자장비·계측", "Electronic Production Equipment": "반도체·전자 장비",
    "Electronics Distributors": "전자 유통", "Electronics/Appliance Stores": "가전 매장",
    "Electronics/Appliances": "가전", "Engineering & Construction": "건설",
    "Environmental Services": "환경 서비스", "Finance/Rental/Leasing": "캐피탈·리스",
    "Financial Conglomerates": "금융지주", "Financial Publishing/Services": "금융 정보",
    "Food Distributors": "식품 유통", "Food Retail": "식품 소매", "Food: Major Diversified": "식품",
    "Food: Meat/Fish/Dairy": "육류·수산·유제품", "Food: Specialty/Candy": "제과·특수식품",
    "Forest Products": "목재", "Gas Distributors": "가스", "Home Furnishings": "가구·인테리어",
    "Home Improvement Chains": "홈인테리어 매장", "Homebuilding": "주택건설",
    "Hospital/Nursing Management": "병원", "Hotels/Resorts/Cruise lines": "호텔·레저",
    "Household/Personal Care": "생활용품·화장품", "Industrial Conglomerates": "복합기업",
    "Industrial Machinery": "기계", "Industrial Specialties": "산업소재",
    "Information Technology Services": "IT 서비스", "Insurance Brokers/Services": "보험 중개",
    "Integrated Oil": "석유 메이저", "Internet Retail": "이커머스",
    "Internet Software/Services": "인터넷", "Investment Banks/Brokers": "증권",
    "Investment Managers": "자산운용", "Investment Trusts/Mutual Funds": "투자회사",
    "Life/Health Insurance": "생명보험", "Major Banks": "은행", "Major Telecommunications": "통신",
    "Managed Health Care": "건강보험", "Marine Shipping": "조선·해운", "Media Conglomerates": "미디어",
    "Medical Distributors": "의약품 유통", "Medical Specialties": "의료기기",
    "Medical/Nursing Services": "의료 서비스", "Metal Fabrication": "금속가공", "Miscellaneous": "기타",
    "Miscellaneous Commercial Services": "상업 서비스", "Miscellaneous Manufacturing": "기타 제조",
    "Motor Vehicles": "자동차", "Movies/Entertainment": "엔터·영화", "Multi-Line Insurance": "종합보험",
    "Office Equipment/Supplies": "사무용품", "Oil & Gas Pipelines": "송유관",
    "Oil & Gas Production": "원유·가스 생산", "Oil Refining/Marketing": "정유",
    "Oilfield Services/Equipment": "유전 서비스", "Other Consumer Services": "소비자 서비스",
    "Other Consumer Specialties": "소비재", "Other Metals/Minerals": "비철금속",
    "Other Transportation": "운송", "Packaged Software": "소프트웨어", "Personnel Services": "인력 서비스",
    "Pharmaceuticals: Generic": "제네릭 제약", "Pharmaceuticals: Major": "제약",
    "Pharmaceuticals: Other": "제약", "Precious Metals": "귀금속", "Property/Casualty Insurance": "손해보험",
    "Publishing: Books/Magazines": "출판", "Publishing: Newspapers": "신문", "Pulp & Paper": "제지",
    "Railroads": "철도", "Real Estate Development": "부동산 개발", "Real Estate Investment Trusts": "리츠",
    "Recreational Products": "레저용품", "Regional Banks": "지방은행", "Restaurants": "외식",
    "Savings Banks": "저축은행", "Semiconductors": "반도체", "Services to the Health Industry": "헬스케어 서비스",
    "Specialty Insurance": "특수보험", "Specialty Stores": "전문 소매", "Specialty Telecommunications": "특수 통신",
    "Steel": "철강", "Telecommunications Equipment": "통신장비", "Textiles": "섬유",
    "Tobacco": "담배", "Tools & Hardware": "공구", "Trucking": "트럭 운송",
    "Trucks/Construction/Farm Machinery": "건설·농기계", "Water Utilities": "수도",
    "Wholesale Distributors": "도매", "Wireless Telecommunications": "무선통신",
}
