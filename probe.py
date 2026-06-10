#!/usr/bin/env python3
"""probe v2: 네이버 옵션 페이지 디스커버리"""
import requests, re
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}

def grab(url, **kw):
    try:
        r=requests.get(url, headers=UA, timeout=20, **kw)
        return r
    except Exception as e:
        print(f"== {url} ERR {e!r}"); return None

# 1) PC 네이버 증권 메뉴에서 옵션/선물 링크 추출
r=grab("https://finance.naver.com/sise/")
if r is not None:
    links=set(re.findall(r'href="([^"]*(?:option|futures|선물|옵션)[^"]*)"', r.text, re.I))
    print("== sise links:", sorted(links)[:20])

r=grab("https://finance.naver.com/fut_opt/")  # 추정 섹션
print("== fut_opt:", r.status_code if r is not None else "ERR")
if r is not None and r.status_code==200:
    print(r.text[:300].replace("\n"," "))

# 2) 모바일 API 후보
for u in [
  "https://m.stock.naver.com/api/index/futures",
  "https://m.stock.naver.com/api/futures/list",
  "https://m.stock.naver.com/front-api/marketIndex/productList?category=futures",
  "https://m.stock.naver.com/api/json/futures/marketIndexFutures.nhn",
  "https://finance.naver.com/futureOption/main.naver",
  "https://finance.naver.com/futureOption/option.naver",
]:
    r=grab(u)
    if r is not None:
        print(f"== {u} -> {r.status_code} | {r.text[:200].replace(chr(10),' ')}")

# 3) PC 메인에서 선물옵션 메뉴 href 전수
r=grab("https://finance.naver.com/")
if r is not None:
    m=set(re.findall(r'href="(/[^"]*)"[^>]*>([^<]*(?:옵션|선물)[^<]*)<', r.text))
    print("== main menu:", sorted(m)[:15])
print("PROBE DONE")
