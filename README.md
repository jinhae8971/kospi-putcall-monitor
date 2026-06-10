# kospi-putcall-monitor

KOSPI200 옵션 풋/콜 미결제약정 비율(P/C OI Ratio) 모니터링 시스템.

- **수집(주소스)**: KIS(한국투자증권) Open API 옵션전광판 `FHPIF05030100` — KOSPI200 옵션 전 정규월물의 콜/풋 미결제약정(`hts_otst_stpl_qty`) 합산. 평일 06:00 KST 호출 시 직전 거래일 정규장 마감 스냅샷.
  - 전광판은 월물당 콜/풋 각 100행(ATM 중심) 한도 — 극외가 잔량 일부가 절단될 수 있으나 OI 비중은 미미 (`truncated` 로그로 추적)
  - 필요 시크릿: `KIS_APP_KEY`, `KIS_APP_SECRET` ([KIS 개발자센터](https://apiportal.koreainvestment.com) 무료 발급)
- **폴백**: KRX 정보데이터시스템 `MDCSTAT12502` (GitHub Actions 러너 IP는 차단되어 로컬 실행/백필 시에만 유효)
- **지수**: Yahoo `^KS200`
- **스케줄**: 평일 06:00 KST (`0 21 * * 0-4` UTC), 직전 거래일 종가 기준
- **알림**: Telegram 브리핑 (비율, 전일 대비, 1년 백분위, 신호등급)
- **대시보드**: GitHub Pages (`/docs`) — https://jinhae8971.github.io/kospi-putcall-monitor/
- **신호등급**: 🟢 <1.5 · 🟡 ≥1.5 · 🟠 ≥2.0 · 🔴 ≥2.5 (역사적 극단 — 과거 급락 선행 레벨)

## 수동 실행 / 백필
Actions → "KOSPI200 Put-Call Daily Brief" → Run workflow → `backfill_days` 입력 (예: 365)

## Secrets
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
