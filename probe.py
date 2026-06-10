#!/usr/bin/env python3
"""Data-source reachability probe (runs on GH Actions runner)."""
import requests, json

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}

def show(name, fn):
    try:
        r = fn()
        body = r.text[:400].replace("\n", " ")
        print(f"== {name} -> {r.status_code} | {body}")
    except Exception as e:
        print(f"== {name} -> ERR {e!r}")

s = requests.Session(); s.headers.update(UA)

# 1) KRX https + 쿠키 워밍업
def krx():
    s.get("https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201", timeout=20)
    return s.post("https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                  data={"bld":"dbms/MDC/STAT/standard/MDCSTAT12502","locale":"ko_KR",
                        "trdDd":"20260610","prodId":"KRDRVOPK2I","mktTpCd":"T","rghtTpCd":"C",
                        "share":"1","money":"3","csvxls_isNo":"false"},
                  headers={"Referer":"https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201",
                           "X-Requested-With":"XMLHttpRequest"}, timeout=25)
show("KRX getJsonData", krx)

# 2) 네이버 PC 옵션 시세
show("naver option_list", lambda: requests.get("https://finance.naver.com/option/option_list.naver", headers=UA, timeout=20))
show("naver sise_option(legacy)", lambda: requests.get("https://finance.naver.com/sise/sise_option.naver", headers=UA, timeout=20))
show("naver finance root", lambda: requests.get("https://finance.naver.com/", headers=UA, timeout=20))

# 3) 네이버 모바일 API
show("m.naver KPI200 basic", lambda: requests.get("https://m.stock.naver.com/api/index/KPI200/basic", headers=UA, timeout=20))
show("m.naver option chain?", lambda: requests.get("https://m.stock.naver.com/front-api/option/list?category=KOSPI200", headers=UA, timeout=20))

# 4) KRX OTP CSV 경로
def krx_otp():
    return s.post("http://data.krx.co.kr/comm/fileDn/GenerateOTP/generate.cmd",
                  data={"bld":"dbms/MDC/STAT/standard/MDCSTAT12502","locale":"ko_KR",
                        "trdDd":"20260610","prodId":"KRDRVOPK2I","mktTpCd":"T","rghtTpCd":"C",
                        "share":"1","money":"3","csvxls_isNo":"false","name":"fileDown","url":"dbms/MDC/STAT/standard/MDCSTAT12502"},
                  headers={"Referer":"http://data.krx.co.kr/"}, timeout=25)
show("KRX OTP", krx_otp)

# 5) 다음 금융
show("daum quotes", lambda: requests.get("https://finance.daum.net/api/market_index/days?market=KOSPI200", headers={**UA,"Referer":"https://finance.daum.net/"}, timeout=20))
print("PROBE DONE")
