#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KRX OpenAPI (Data Marketplace) 어댑터
=====================================
- 엔드포인트: http://data-dbg.krx.co.kr/svc/apis/drv/opt_bydd_trd
- 인증: 헤더 AUTH_KEY (openapi.krx.co.kr 무료 회원가입 → API 이용신청 → 인증키)
- 특징: 클라우드 IP 차단 없음(GitHub Actions 직접 호출 가능),
        basDd 파라미터로 임의 과거 거래일 조회 가능 → 백필 지원
- 데이터: 전체 지수옵션 일별매매정보 (미결제약정 ACC_OPNINT_QTY 포함)

코스피200 '정규 월물' 옵션만 집계한다 (미니/위클리/코스닥150 제외)
— Bloomberg P/C OI Ratio 차트와 동일 모집단.
"""
import os
import sys

import requests

ENDPOINT = "http://data-dbg.krx.co.kr/svc/apis/drv/opt_bydd_trd"
TIMEOUT = 30

_FIELD_LOGGED = False


def _to_int(v) -> int:
    try:
        return int(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0


def _is_k200_standard(prod_nm: str) -> bool:
    """'코스피200 옵션' 정규 월물만 통과. 미니/위클리/코스닥/주식옵션 제외."""
    name = prod_nm.replace(" ", "")
    if "코스피200" not in name or "옵션" not in name:
        return False
    return not any(x in name for x in ("미니", "위클리", "먼슬리위클리"))


def _right_of(row: dict) -> str:
    """권리유형 판별: RGHT_TP_NM 우선, 없으면 ISU_NM 토큰."""
    r = (row.get("RGHT_TP_NM") or "").strip().upper()
    if r in ("CALL", "콜", "C"):
        return "C"
    if r in ("PUT", "풋", "P"):
        return "P"
    parts = (row.get("ISU_NM") or "").split()
    if len(parts) > 1 and parts[1] in ("C", "P"):
        return parts[1]
    return ""


def fetch_pc(bas_dd: str, auth_key: str) -> dict | None:
    """해당 거래일의 코스피200 옵션 콜/풋 OI 합산.

    Returns:
        dict  — {"call_oi", "put_oi"}  (정상 수집)
        {}    — 휴장일 (응답은 정상이나 데이터 없음)
        None  — 통신/인증 오류 (소스 사용 불가)
    """
    global _FIELD_LOGGED
    try:
        r = requests.get(ENDPOINT, params={"basDd": bas_dd},
                         headers={"AUTH_KEY": auth_key}, timeout=TIMEOUT)
    except Exception as e:
        print(f"[WARN] KRX OpenAPI 통신 실패: {e}", file=sys.stderr)
        return None

    if r.status_code == 401:
        print("[WARN] KRX OpenAPI 인증 실패 — KRX_OPENAPI_KEY 확인 필요",
              file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"[WARN] KRX OpenAPI HTTP {r.status_code}: {r.text[:120]}",
              file=sys.stderr)
        return None

    try:
        data = r.json()
    except ValueError:
        print(f"[WARN] KRX OpenAPI 비정상 응답: {r.text[:120]}", file=sys.stderr)
        return None

    rows = data.get("OutBlock_1") or []
    if not rows:
        return {}  # 휴장일

    if not _FIELD_LOGGED:
        print(f"[DIAG] OpenAPI 응답 필드: {sorted(rows[0].keys())}")
        prods = sorted({x.get('PROD_NM', '') for x in rows})
        print(f"[DIAG] 상품 목록: {prods}")
        _FIELD_LOGGED = True

    call_oi = put_oi = 0
    traded = 0
    for row in rows:
        if not _is_k200_standard(row.get("PROD_NM", "")):
            continue
        oi = _to_int(row.get("ACC_OPNINT_QTY"))
        traded += _to_int(row.get("ACC_TRDVOL"))
        right = _right_of(row)
        if right == "C":
            call_oi += oi
        elif right == "P":
            put_oi += oi

    if call_oi == 0 and put_oi == 0:
        return {}  # 대상 상품 데이터 없음 → 휴장 취급
    if traded == 0:
        print(f"[SKIP] {bas_dd} 거래량 0 — 휴장 잔존 OI로 간주", file=sys.stderr)
        return {}
    return {"call_oi": call_oi, "put_oi": put_oi}


if __name__ == "__main__":
    key = os.environ.get("KRX_OPENAPI_KEY", "")
    dd = sys.argv[1] if len(sys.argv) > 1 else "20260610"
    print(fetch_pc(dd, key))
