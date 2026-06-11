#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KOSPI200 Put-to-Call Open Interest Ratio Monitor
=================================================
- 주소스: KRX OpenAPI(Data Marketplace) drv/opt_bydd_trd — 증권사 무관, 무료 인증키
- 폴백1: KIS Open API 옵션전광판 (시크릿 등록 시)
- 폴백2: KRX 정보데이터시스템 (클라우드 IP 차단 → 로컬 실행 시에만 유효)
- Yahoo Finance에서 KOSPI200 지수를 병합한다.
- data/history.csv 에 누적 → docs/data.json 재생성 → Telegram 브리핑 발송.

Usage:
  python putcall_monitor.py                 # 직전 거래일 1건 수집 + 텔레그램 발송
  python putcall_monitor.py --backfill 180  # 과거 N캘린더일 백필 (텔레그램 미발송)
  python putcall_monitor.py --no-telegram   # 수집만 수행
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

KST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_CSV = os.path.join(BASE_DIR, "data", "history.csv")
DATA_JSON = os.path.join(BASE_DIR, "docs", "data.json")

KRX_URL = "http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
KRX_INDEX_PAGE = "http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201"
PROD_K200_OPT = "KRDRVOPK2I"  # 코스피200 옵션 (정규 월물)

THRESHOLD_EXTREME = 2.5   # Bloomberg 차트 기준 역사적 극단 구간
THRESHOLD_ELEVATED = 2.0

CSV_FIELDS = ["date", "call_oi", "put_oi", "pc_ratio", "k200"]


# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
def load_config() -> dict:
    cfg = {
        "telegram_token": os.environ.get("TELEGRAM_TOKEN", ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "pages_url": os.environ.get("PAGES_URL", ""),
        "krx_openapi_key": os.environ.get("KRX_OPENAPI_KEY", ""),
    }
    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if not cfg.get(k):
                    cfg[k] = v
    return cfg


# ----------------------------------------------------------------------
# KRX fetch
# ----------------------------------------------------------------------
def krx_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "http://data.krx.co.kr",
        "Referer": KRX_INDEX_PAGE,
    })
    try:
        s.get(KRX_INDEX_PAGE, timeout=20)
    except requests.RequestException:
        pass
    return s


def krx_option_oi(session: requests.Session, trd_dd: str, right: str,
                  retries: int = 3) -> int | None:
    """해당 일자/권리유형(C/P)의 KOSPI200 옵션 전종목 미결제약정 합계."""
    payload = {
        "bld": "dbms/MDC/STAT/standard/MDCSTAT12502",
        "locale": "ko_KR",
        "trdDd": trd_dd,
        "prodId": PROD_K200_OPT,
        "trdDdBox1": trd_dd,
        "trdDdBox2": trd_dd,
        "mktTpCd": "T",
        "rghtTpCd": right,      # "C" 콜 / "P" 풋
        "share": "1",
        "money": "3",
        "csvxls_isNo": "false",
    }
    last_err = None
    for attempt in range(retries):
        try:
            r = session.post(KRX_URL, data=payload, timeout=30)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}: {r.text[:120]}"
                time.sleep(2 * (attempt + 1))
                continue
            data = r.json()
            rows = data.get("output") or data.get("OutBlock_1") or []
            if not rows:
                return 0  # 휴장일 등 데이터 없음
            total = 0
            counted = False
            for row in rows:
                raw = str(row.get("ACC_OPNINT_QTY", "")).replace(",", "").strip()
                if raw in ("", "-"):
                    continue
                total += int(float(raw))
                counted = True
            return total if counted else 0
        except (requests.RequestException, ValueError, json.JSONDecodeError) as e:
            last_err = repr(e)
            time.sleep(2 * (attempt + 1))
    print(f"[WARN] KRX fetch failed ({trd_dd}/{right}): {last_err}", file=sys.stderr)
    return None


def fetch_pc_for_date(session: requests.Session, trd_dd: str) -> dict | None:
    call_oi = krx_option_oi(session, trd_dd, "C")
    put_oi = krx_option_oi(session, trd_dd, "P")
    if call_oi is None or put_oi is None:
        return None  # 네트워크/차단 실패
    if call_oi == 0 and put_oi == 0:
        return {}     # 휴장일
    ratio = round(put_oi / call_oi, 4) if call_oi else 0.0
    return {"date": f"{trd_dd[:4]}-{trd_dd[4:6]}-{trd_dd[6:]}",
            "call_oi": call_oi, "put_oi": put_oi, "pc_ratio": ratio}


# ----------------------------------------------------------------------
# Yahoo Finance: KOSPI200 index
# ----------------------------------------------------------------------
def fetch_k200_series(range_str: str = "2y") -> dict:
    """date(YYYY-MM-DD) -> close 매핑."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EKS200"
    try:
        r = requests.get(url, params={"range": range_str, "interval": "1d"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        out = {}
        for t, c in zip(ts, closes):
            if c is None:
                continue
            d = datetime.fromtimestamp(t, tz=KST).strftime("%Y-%m-%d")
            out[d] = round(float(c), 2)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] Yahoo K200 fetch failed: {e!r}", file=sys.stderr)
        return {}


# ----------------------------------------------------------------------
# History persistence
# ----------------------------------------------------------------------
def load_history() -> list[dict]:
    if not os.path.exists(HISTORY_CSV):
        return []
    with open(HISTORY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        try:
            out.append({
                "date": r["date"],
                "call_oi": int(r["call_oi"]),
                "put_oi": int(r["put_oi"]),
                "pc_ratio": float(r["pc_ratio"]),
                "k200": float(r["k200"]) if r.get("k200") not in (None, "", "0") else None,
            })
        except (KeyError, ValueError):
            continue
    out.sort(key=lambda x: x["date"])
    return out


def save_history(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    rows = sorted({r["date"]: r for r in rows}.values(), key=lambda x: x["date"])
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({
                "date": r["date"], "call_oi": r["call_oi"], "put_oi": r["put_oi"],
                "pc_ratio": r["pc_ratio"],
                "k200": "" if r.get("k200") is None else r["k200"],
            })


def export_dashboard_json(rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(DATA_JSON), exist_ok=True)
    payload = {
        "updated_at": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "threshold_extreme": THRESHOLD_EXTREME,
        "threshold_elevated": THRESHOLD_ELEVATED,
        "series": rows,
    }
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


# ----------------------------------------------------------------------
# Analytics & Telegram
# ----------------------------------------------------------------------
def percentile_rank(values: list[float], target: float) -> float:
    if not values:
        return 0.0
    below = sum(1 for v in values if v <= target)
    return round(100.0 * below / len(values), 1)


def signal_label(ratio: float) -> str:
    if ratio >= THRESHOLD_EXTREME:
        return "🔴 극단 구간 (≥2.5) — 과거 2008·2021 급락 선행 레벨"
    if ratio >= THRESHOLD_ELEVATED:
        return "🟠 경계 구간 (≥2.0) — 풋 미결제 과열 진행"
    if ratio >= 1.5:
        return "🟡 중립 상단 (≥1.5)"
    return "🟢 정상 구간"


def build_message(rows: list[dict], pages_url: str) -> str:
    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    d = datetime.strptime(latest["date"], "%Y-%m-%d")
    one_year_ago = (d - timedelta(days=365)).strftime("%Y-%m-%d")
    trailing = [r["pc_ratio"] for r in rows if r["date"] >= one_year_ago]
    pct = percentile_rank(trailing, latest["pc_ratio"])

    delta_txt = ""
    if prev:
        diff = latest["pc_ratio"] - prev["pc_ratio"]
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "→")
        delta_txt = f" ({arrow}{abs(diff):.3f})"

    k200_txt = "N/A"
    if latest.get("k200"):
        k200_txt = f"{latest['k200']:,.2f}"
        if prev and prev.get("k200"):
            chg = (latest["k200"] / prev["k200"] - 1) * 100
            sign = "+" if chg >= 0 else ""
            k200_txt += f" ({sign}{chg:.2f}%)"

    lines = [
        f"📊 <b>KOSPI200 풋/콜 비율 브리핑</b>",
        f"기준일: {latest['date']} (종가)",
        "━━━━━━━━━━━━━━",
        f"• P/C OI Ratio: <b>{latest['pc_ratio']:.3f}</b>{delta_txt}",
        f"• 1년 백분위: {pct}%",
        f"• 콜 OI {latest['call_oi']:,} / 풋 OI {latest['put_oi']:,}",
        f"• KOSPI200: {k200_txt}",
        "",
        signal_label(latest["pc_ratio"]),
    ]
    if pages_url:
        lines += ["", f'📈 <a href="{pages_url}">추세 대시보드 보기</a>']
    return "\n".join(lines)


def send_telegram(text: str, token: str, chat_id: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, json={
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }, timeout=20)
    r.raise_for_status()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def trading_day_candidates(start: datetime, lookback: int) -> list[str]:
    out, d = [], start
    while len(out) < lookback:
        if d.weekday() < 5:  # 월–금
            out.append(d.strftime("%Y%m%d"))
        d -= timedelta(days=1)
    return out


# ----------------------------------------------------------------------
# KIS (주소스)
# ----------------------------------------------------------------------
def fetch_via_krx_openapi(trd_dd: str, auth_key: str) -> dict | None:
    """KRX OpenAPI로 특정 거래일 콜/풋 OI 수집. (주소스)

    Returns: dict(데이터) / {}(휴장) / None(소스 사용 불가)
    """
    if not auth_key:
        return None
    import source_krx_openapi
    res = source_krx_openapi.fetch_pc(trd_dd, auth_key)
    if not res:
        return res  # None(오류) 또는 {}(휴장) 그대로 전달
    ds = f"{trd_dd[:4]}-{trd_dd[4:6]}-{trd_dd[6:]}"
    ratio = round(res["put_oi"] / res["call_oi"], 4)
    print(f"[OK/KRX-OpenAPI] {ds} call={res['call_oi']:,} "
          f"put={res['put_oi']:,} ratio={ratio}")
    return {"date": ds, "call_oi": res["call_oi"], "put_oi": res["put_oi"],
            "pc_ratio": ratio, "k200": None}


def fetch_via_kis(date_str: str, history: list[dict]) -> dict | None:
    """KIS 옵션전광판으로 전 월물 콜/풋 OI 합산. 실패/미설정 시 None.

    공휴일 가드: 전광판 스냅샷이 직전 행과 콜·풋 모두 동일하면
    휴장으로 간주(신규 데이터 아님)하고 None 반환.
    """
    try:
        import source_kis
        snap = source_kis.fetch_total_oi()
    except Exception as e:
        print(f"[WARN] KIS 수집 실패: {e}", file=sys.stderr)
        return None
    if history:
        last = history[-1]
        if (int(last.get("call_oi") or 0) == snap["call_oi"]
                and int(last.get("put_oi") or 0) == snap["put_oi"]):
            print("[SKIP] KIS OI가 직전 행과 동일 — 휴장 추정", file=sys.stderr)
            return None
    ratio = round(snap["put_oi"] / snap["call_oi"], 4)
    if snap.get("truncated"):
        print("[NOTE] 전광판 100행 한도 도달 월물 존재 — 극외가 일부 절단 가능",
              file=sys.stderr)
    print(f"[OK/KIS] {date_str} call={snap['call_oi']:,} put={snap['put_oi']:,} "
          f"ratio={ratio} (months={len(snap['maturities'])})")
    return {"date": date_str, "call_oi": snap["call_oi"],
            "put_oi": snap["put_oi"], "pc_ratio": ratio, "k200": None}


def notify_setup_needed(cfg: dict) -> None:
    """데이터 소스 전부 실패 + 누적 0건일 때 1회성 설정 안내."""
    msg = (
        "⚙️ <b>KOSPI200 P/C 모니터 — 설정 필요</b>\n\n"
        "증권사 계좌 없이 <b>KRX OpenAPI 무료 인증키</b>만으로 작동합니다.\n\n"
        "1️⃣ https://openapi.krx.co.kr 회원가입 (무료)\n"
        "2️⃣ [API 이용신청] → 파생상품 → <b>옵션 일별매매정보</b> 신청\n"
        "3️⃣ 발급된 인증키를 레포 Secrets에 등록:\n"
        "   • <code>KRX_OPENAPI_KEY</code>\n"
        "   → https://github.com/jinhae8971/kospi-putcall-monitor/settings/secrets/actions\n\n"
        "등록 후 Actions 수동 실행 또는 다음 평일 06:00부터 자동 수집됩니다."
    )
    if cfg["telegram_token"] and cfg["telegram_chat_id"]:
        try:
            send_telegram(msg, cfg["telegram_token"], cfg["telegram_chat_id"])
            print("[DONE] 설정 안내 Telegram 발송")
        except Exception as e:
            print(f"[WARN] 안내 발송 실패: {e}", file=sys.stderr)
    print("[INFO] KRX_OPENAPI_KEY 등록 필요 — 수집 생략", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0,
                    help="과거 N캘린더일 백필 (텔레그램 미발송)")
    ap.add_argument("--no-telegram", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    session = krx_session()
    history = load_history()
    known_dates = {r["date"] for r in history}
    now_kst = datetime.now(KST)

    new_rows: list[dict] = []

    if args.backfill > 0:
        start = now_kst - timedelta(days=1)
        d = start
        while d >= start - timedelta(days=args.backfill):
            if d.weekday() < 5:
                ds = d.strftime("%Y-%m-%d")
                if ds not in known_dates:
                    trd = d.strftime("%Y%m%d")
                    if cfg.get("krx_openapi_key"):
                        res = fetch_via_krx_openapi(trd, cfg["krx_openapi_key"])
                    else:
                        res = fetch_pc_for_date(session, trd)
                    if res is None:
                        print(f"[ERROR] 데이터 소스 사용 불가 at {ds}; aborting backfill.",
                              file=sys.stderr)
                        break
                    if res:
                        new_rows.append(res)
                        print(f"[OK] {ds} ratio={res['pc_ratio']}")
                    else:
                        print(f"[SKIP] {ds} holiday")
                    time.sleep(0.4)
            d -= timedelta(days=1)
    else:
        # ── 일일 수집: KIS(주소스) → KRX(폴백) ─────────────────────
        # 06:00 KST 실행 시 KIS 전광판 OI = 직전 거래일 정규장 마감 스냅샷.
        prev_td = trading_day_candidates(now_kst - timedelta(days=1), 1)[0]
        prev_ds = f"{prev_td[:4]}-{prev_td[4:6]}-{prev_td[6:]}"

        res = None
        if prev_ds not in known_dates:
            # 1순위: KRX OpenAPI — 최대 7영업일 소급 (연휴 대응)
            if cfg.get("krx_openapi_key"):
                for trd_dd in trading_day_candidates(now_kst - timedelta(days=1), 7):
                    ds = f"{trd_dd[:4]}-{trd_dd[4:6]}-{trd_dd[6:]}"
                    if ds in known_dates:
                        break
                    r = fetch_via_krx_openapi(trd_dd, cfg["krx_openapi_key"])
                    if r is None:
                        break  # 인증/통신 오류 → 다음 소스로
                    if r:
                        res = r
                        break
                    time.sleep(0.4)
            # 2순위: KIS 옵션전광판
            if res is None:
                res = fetch_via_kis(prev_ds, history)
            if res is None:  # 3순위: KRX 데이터시스템 (로컬 IP 전용)
                for trd_dd in trading_day_candidates(now_kst - timedelta(days=1), 7):
                    ds = f"{trd_dd[:4]}-{trd_dd[4:6]}-{trd_dd[6:]}"
                    if ds in known_dates:
                        break
                    r = fetch_pc_for_date(session, trd_dd)
                    if r is None:
                        break  # KRX 차단
                    if r:
                        res = r
                        break
                    time.sleep(0.5)

        if res:
            new_rows.append(res)
        elif prev_ds not in known_dates and not history:
            # 양 소스 모두 실패 + 누적 데이터 없음 → 설정 안내 후 정상 종료
            notify_setup_needed(cfg)
            return 0
        elif prev_ds not in known_dates:
            print("[WARN] 신규 데이터 수집 실패 — 기존 누적분으로 브리핑 발송",
                  file=sys.stderr)

    merged = {r["date"]: r for r in history}
    for r in new_rows:
        merged[r["date"]] = {**merged.get(r["date"], {}), **r}

    # KOSPI200 지수 병합 (누락분 일괄 보강)
    k200 = fetch_k200_series("2y")
    for ds, row in merged.items():
        if row.get("k200") is None and ds in k200:
            row["k200"] = k200[ds]

    rows = sorted(merged.values(), key=lambda x: x["date"])
    save_history(rows)
    export_dashboard_json(rows)
    print(f"[DONE] history={len(rows)} rows, new={len(new_rows)}")

    if args.backfill == 0 and not args.no_telegram and rows:
        if cfg["telegram_token"] and cfg["telegram_chat_id"]:
            send_telegram(build_message(rows, cfg.get("pages_url", "")),
                          cfg["telegram_token"], cfg["telegram_chat_id"])
            print("[DONE] Telegram sent")
        else:
            print("[WARN] Telegram 설정 없음 — 발송 생략", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
