# 업종 × 요일 심리 지도 (미국)

미국 상장 종목을 FactSet 20개 섹터로 묶어, 매일 **시장 대비 등락**과 **상대 거래**를 함께 보고 업종 심리를 6칸으로 분류하는 트래커임.
GitHub Actions가 매일 아침(한국 07:30) 데이터를 수집·계산하고, GitHub Pages가 화면을 보여줌. 서버 비용 0원.

## 1. 설치 (최초 1회, 약 10분)

1. GitHub에서 새 저장소 생성 (예: `sector-mood`). **Public**이어야 무료 플랜에서 Pages 사용 가능함.
2. 이 폴더 내용을 그대로 올림.
   ```bash
   cd sector-mood
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<아이디>/sector-mood.git
   git push -u origin main
   ```
3. 저장소 **Settings → Actions → General → Workflow permissions** 에서 **Read and write permissions** 선택 후 저장.
4. **Actions 탭 → update-sector-mood → Run workflow** 로 첫 실행. 첫 실행은 자동으로 26주 백필을 하므로 10~20분 걸림.
5. **Settings → Pages → Build and deployment**: Source = *Deploy from a branch*, Branch = `main`, 폴더 = `/docs` 선택 후 저장.
6. 1~2분 뒤 `https://<아이디>.github.io/sector-mood/` 에서 확인.

이후에는 평일마다 자동 갱신됨. 수동 갱신은 Actions 탭에서 Run workflow.

## 2. 구조

```
pipeline/
  config.py     기준값·시총 하한·업종 한글명
  universe.py   TradingView 스크리너로 유니버스 구성 (월 1회 고정, 실패 시 지난달 재사용)
  prices.py     yfinance 일봉 9개월치 수집
  compute.py    업종 지표 계산 → docs/data/weeks/YYYY-MM-DD.json
  run.py        실행 진입점
  synthetic.py  네트워크 없이 테스트용 가짜 시장
docs/
  index.html    화면 (정적, 서버 불필요)
  data/         계산 결과 (Actions가 매일 커밋)
data/universe/  월별 유니버스 스냅샷
tests/          계산 검증 (손계산 대조)
```

## 3. 지표 정의

| 지표 | 정의 |
|---|---|
| 상대 등락 | 업종 수익률 − 시장 수익률 (%p). 시총가중(전일 시총) / 동일가중 선택 |
| 상대 거래대금 | (업종 당일 거래대금 ÷ 업종 직전 20일 평균) ÷ (시장 동일 비율) |
| 상대 거래량 | 종목별 (거래량 ÷ 직전 20일 평균)의 업종 평균 ÷ 시장 평균. 가격 효과 제거 버전 |
| σ | 업종 일간 상대 등락의 직전 60거래일 표준편차 (주 시작 시점 기준). 주간은 σ×√일수 |
| 상승일 거래 | 그 주 종목 거래대금 중 상승한 날에 발생한 비중 |
| 거래 몫 | 시장 전체 거래대금 중 비중 |
| 거래 배수 | 종목 주간 일평균 거래대금 ÷ 직전 20일 평균 |
| 이긴 날 | 업종이 시장보다 좋았던 날 수 |

**분류**

| | 거래 기준 이상 | 거래 기준 미만 |
|---|---|---|
| 상승 기준 이상 | 거래 몰린 상승 | 조용한 상승 |
| 그 사이 | 손바뀜 | 소강 |
| 하락 기준 이하 | 거래 몰린 하락 | 관심 이탈 |

- 기본값: 일간 ±1%p·1.1배, 주간 ±2%p·1.05배, σ 모드 ±1σ. 화면에서 바로 바꿀 수 있음(브라우저에 저장).
- ⚑ 이벤트일: 3번째 금요일(옵션 만기, 3·6·9·12월은 쿼드러플 위칭), 시장 거래대금 1.4배 이상 급증일, 0.65배 이하 저거래일.

## 4. 알려진 한계

- **데이터 소스가 비공식임.** yfinance(야후)와 TradingView 스크리너는 공식 API가 아님. 구조가 바뀌면 깨질 수 있음. 유니버스는 실패 시 지난달 파일을 재사용하고, 가격은 4회 재시도함. 깨지면 Actions 탭에 빨간 X가 뜸.
- **생존 편향이 약간 있음.** 과거 주를 백필할 때 현재 유니버스를 씀. 그 사이 상장폐지된 종목은 빠져 있음.
- 업종 분류는 TradingView(FactSet) 기준임. GICS와 다름. 예: 애플은 전자 기술, 엔비디아도 전자 기술.
- GitHub 예약 실행은 몇 분~수십 분 지연될 수 있음.
- 저장소에 60일간 활동이 없으면 예약 실행이 멈춤. 매일 데이터 커밋이 생기므로 보통은 문제없음.

## 5. 로컬 테스트

```bash
pip install -r requirements.txt
python -m pipeline.run --synthetic --weeks 6   # 가짜 데이터
python -m tests.test_compute                   # 계산 검증
cd docs && python -m http.server               # http://localhost:8000
```
합성 데이터로 테스트한 뒤에는 `docs/data/` 를 지우고 커밋해야 함. 그래야 첫 Actions 실행이 실제 백필을 함.
