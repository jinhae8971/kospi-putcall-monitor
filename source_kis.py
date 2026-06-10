#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KIS(한국투자증권) REST API 기반 KOSPI200 옵션 미결제약정 수집기.

- 옵션월물리스트(FHPIO056104C0) → 정규 월물 목록
- 옵션전광판 콜풋(FHPIF05030100) → 월물별 콜/풋 체인의 hts_otst_stpl_qty 합산
- 06:00 KST 호출 시 전일 정규장 마감 기준 OI 스냅샷

주의: 전광판은 월물당 콜/풋 각 100행 한도(ATM 중심). 극외가 잔량이 절단될 수
있으나 OI 비중은 미미하며, 100행 도달 시 truncated 플래그로 기록한다.
"""
import os
import time

import requests

KIS_BASE = "https://openapi.koreainvestment.com:9443"
_TOKEN_CACHE = {"token": None, "ts": 0.0}


class KISError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    key = os.environ.get("KIS_APP_KEY", "")
    sec = os.environ.get("KIS_APP_SECRET", "")
    if not key or not sec:
        raise KISError("KIS_APP_KEY / KIS_APP_SECRET 미설정")
    return key, sec


def get_token() -> str:
    """접근토큰 발급. KIS는 유효기간 내 재요청 시 동일 토큰을 반환한다."""
    if _TOKEN_CACHE["token"] and time.time() - _TOKEN_CACHE["ts"] < 3600:
        return _TOKEN_CACHE["token"]
    key, sec = _credentials()
    r = requests.post(f"{KIS_BASE}/oauth2/tokenP", json={
        "grant_type": "client_credentials", "appkey": key, "appsecret": sec,
    }, timeout=20)
    if r.status_code != 200:
        raise KISError(f"토큰 발급 실패 HTTP {r.status_code}: {r.text[:200]}")
    tok = r.json().get("access_token")
    if not tok:
        raise KISError(f"토큰 응답 이상: {r.text[:200]}")
    _TOKEN_CACHE.update(token=tok, ts=time.time())
    return tok


def _get(path: str, tr_id: str, params: dict) -> dict:
    key, sec = _credentials()
    r = requests.get(f"{KIS_BASE}{path}", params=params, headers={
        "authorization": f"Bearer {get_token()}",
        "appkey": key, "appsecret": sec,
        "tr_id": tr_id, "custtype": "P",
    }, timeout=30)
    if r.status_code != 200:
        raise KISError(f"{tr_id} HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    if j.get("rt_cd") not in ("0", 0):
        raise KISError(f"{tr_id} rt_cd={j.get('rt_cd')} msg={j.get('msg1')}")
    return j


def list_maturities() -> list[str]:
    """정규 KOSPI200 옵션 월물(YYYYMM) 목록."""
    j = _get("/uapi/domestic-futureoption/v1/quotations/display-board-option-list",
             "FHPIO056104C0", {
                 "FID_COND_SCR_DIV_CODE": "509",
                 "FID_COND_MRKT_DIV_CODE": "",
                 "FID_COND_MRKT_CLS_CODE": "",
             })
    out = j.get("output") or j.get("output1") or []
    mats: list[str] = []
    for row in out:
        for v in row.values():
            v = str(v).strip()
            if len(v) == 6 and v.isdigit() and v.startswith("20"):
                if v not in mats:
                    mats.append(v)
                break
    if not mats:
        raise KISError(f"월물리스트 파싱 실패: {str(out)[:200]}")
    return mats


def _sum_oi(rows: list[dict]) -> tuple[int, bool]:
    total = 0
    for row in rows:
        raw = str(row.get("hts_otst_stpl_qty", "0")).replace(",", "").strip()
        if raw not in ("", "-"):
            total += int(float(raw))
    return total, len(rows) >= 100


def fetch_total_oi() -> dict:
    """전 월물 콜/풋 미결제약정 합계."""
    mats = list_maturities()
    call_total, put_total, truncated = 0, 0, False
    for m in mats:
        j = _get("/uapi/domestic-futureoption/v1/quotations/display-board-callput",
                 "FHPIF05030100", {
                     "FID_COND_MRKT_DIV_CODE": "O",
                     "FID_COND_SCR_DIV_CODE": "20503",
                     "FID_MRKT_CLS_CODE": "CO",
                     "FID_MTRT_CNT": m,
                     "FID_MRKT_CLS_CODE1": "PO",
                     "FID_COND_MRKT_CLS_CODE": "",
                 })
        c, tc = _sum_oi(j.get("output1") or [])
        p, tp = _sum_oi(j.get("output2") or [])
        call_total += c
        put_total += p
        truncated = truncated or tc or tp
        time.sleep(1.2)  # 전광판 권장 호출 간격(1초 1건)
    if call_total == 0:
        raise KISError("콜 OI 합계 0 — 응답 구조 변경 가능성")
    return {"call_oi": call_total, "put_oi": put_total,
            "maturities": mats, "truncated": truncated}
