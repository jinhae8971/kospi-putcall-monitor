# kospi-putcall-monitor

KOSPI200 옵션 풋/콜 미결제약정 비율(P/C OI Ratio) 모니터링 시스템.

- **수집**: KRX 정보데이터시스템 `MDCSTAT12502` (KOSPI200 옵션 정규월물 전종목, 콜/풋 미결제약정 합산) + Yahoo `^KS200`
- **스케줄**: 평일 06:00 KST (`0 21 * * 0-4` UTC), 직전 거래일 종가 기준
- **알림**: Telegram 브리핑 (비율, 전일 대비, 1년 백분위, 신호등급)
- **대시보드**: GitHub Pages (`/docs`) — https://jinhae8971.github.io/kospi-putcall-monitor/
- **신호등급**: 🟢 <1.5 · 🟡 ≥1.5 · 🟠 ≥2.0 · 🔴 ≥2.5 (역사적 극단 — 과거 급락 선행 레벨)

## 수동 실행 / 백필
Actions → "KOSPI200 Put-Call Daily Brief" → Run workflow → `backfill_days` 입력 (예: 365)

## Secrets
`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`
