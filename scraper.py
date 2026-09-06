"""
중국 플라스틱 원자재 가격 자동 수집 스크립트 (2개 출처 동시 수집)

출처 1: 금투망(金投网, m.cngold.org) 가격 채널 > 石化 > 塑料
        https://m.cngold.org/price/lm3143/
        -> 하루 대표가 한 줄(참고가) 방식. PA(나일론) 없음.

출처 2: 생의사(生意社) 실거래 플랫폼 RawMex — https://www.rawmex.cn/
        橡塑(고무/플라스틱) 카테고리 > 품목별 매물(挂牌) 목록
        https://www.rawmex.cn/trade/s-{품목ID}/
        -> 실제 판매 매물(브랜드/등급/단가/물량/지역) 여러 개를 평균낸 방식. PA6/PA66 있음.

두 출처는 가격 산정 방식이 서로 달라서 값 차이가 날 수 있습니다. 이 스크립트는
두 출처를 모두 수집해 data/prices.csv 에 "source" 컬럼으로 구분해서 함께 저장합니다.
(대시보드 좌측에서 어느 출처를 볼지 고를 수 있습니다)

사용법
------
    python scraper.py

주의
----
- 공개 웹페이지의 가격 정보를 참고용으로 수집합니다. 실거래가와 다를 수 있습니다.
- 사이트 구조가 바뀌면 각 출처의 parse_* 함수를 사이트 구조에 맞게 수정해야 할 수 있습니다.
"""

import csv
import os
import re
import sys
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 공통 설정
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_REQUESTS = 1.0

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PRICES_CSV = os.path.join(DATA_DIR, "prices.csv")
DETAIL_CSV = os.path.join(DATA_DIR, "prices_detail.csv")
FX_CSV = os.path.join(DATA_DIR, "fx.csv")

SUMMARY_FIELDS = ["date", "material", "source", "avg_price", "min_price", "max_price", "spec_count", "unit", "source_url"]
DETAIL_FIELDS = ["date", "material", "source", "name", "spec", "price", "unit", "region", "qty", "source_url"]

# 화면(streamlit_app.py)에서 쓰는 라벨과 동일하게 맞춰주세요.
MATERIAL_LABELS = {
    "PP": "PP (폴리프로필렌)",
    "PE": "PE (폴리에틸렌, 범용)",
    "PS": "PS (폴리스티렌)",
    "ABS": "ABS 수지",
    "PC": "PC (폴리카보네이트)",
    "POM": "POM (폴리아세탈)",
    "PA6": "PA6 (나일론6)",
    "PA66": "PA66 (나일론66)",
    "PET": "PET (페트)",
    "HDPE": "HDPE (고밀도폴리에틸렌)",
    "PVC": "PVC (폴리염화비닐)",
    "LDPE": "LDPE (저밀도폴리에틸렌)",
}


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def fetch(url):
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


# ---------------------------------------------------------------------------
# CSV 입출력 도우미
# ---------------------------------------------------------------------------
def read_existing_keys(csv_path, key_cols):
    keys = set()
    if not os.path.exists(csv_path):
        return keys
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add(tuple(row[c] for c in key_cols))
    return keys


def append_rows(csv_path, fieldnames, rows):
    if not rows:
        return
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ===========================================================================
# 출처 1: 금투망(cngold.org)
# ===========================================================================
CNGOLD_LISTING_URL = "https://m.cngold.org/price/lm3143/"

CNGOLD_TAG_TO_CODE = {
    "ABS报价": "ABS",
    "PS报价": "PS",
    "PP报价": "PP",
    "PP粒报价": "PP",
    "PVC报价": "PVC",
    "LDPE报价": "LDPE",
    "HDPE报价": "HDPE",
    "PET报价": "PET",
    "PC报价": "PC",
    "POM报价": "POM",
    "PE报价": "PE",
}

CNGOLD_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
CNGOLD_TAG_RE = re.compile(r"([A-Za-z]{2,10}(?:粒|粉料)?报价)")
CNGOLD_PRICE_RE = re.compile(r"^\d+(?:\.\d+)?$")
CNGOLD_UNIT_KEYWORDS = ("元/吨", "元/公斤", "元/千克", "元/kg")


def cngold_normalize_url(href):
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://m.cngold.org" + href
    return "https://m.cngold.org/" + href


def cngold_discover_articles(listing_html):
    """목록 페이지에서 {(date_str, code): url} 을 뽑아냅니다."""
    soup = BeautifulSoup(listing_html, "lxml")
    found = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/price/jg" not in href:
            continue
        text = a.get_text(" ", strip=True)

        date_m = CNGOLD_DATE_RE.search(text)
        if not date_m:
            continue
        y, m, d = date_m.groups()
        date_str = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

        tag_m = CNGOLD_TAG_RE.search(text)
        if not tag_m:
            continue
        code = CNGOLD_TAG_TO_CODE.get(tag_m.group(1))
        if not code:
            continue

        key = (date_str, code)
        if key not in found:
            found[key] = cngold_normalize_url(href)
    return found


def cngold_parse_price_rows(article_html):
    """기사 페이지에서 [{name, spec, price, unit}, ...] 를 뽑아냅니다."""
    soup = BeautifulSoup(article_html, "lxml")
    rows_out = []
    seen = set()

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            cells = [c for c in cells if c != ""]
            if len(cells) < 2:
                continue

            price_val = None
            unit_val = None
            for c in cells:
                if unit_val is None and any(k in c for k in CNGOLD_UNIT_KEYWORDS):
                    unit_val = c
                c_num = c.replace(",", "")
                if price_val is None and CNGOLD_PRICE_RE.match(c_num):
                    try:
                        v = float(c_num)
                    except ValueError:
                        v = None
                    if v is not None and v >= 100:
                        price_val = v

            if price_val is None:
                continue

            name = cells[0][:30]
            spec = cells[1][:40] if len(cells) > 2 else ""
            unit = unit_val or "元/吨"

            dedup_key = (name, spec, price_val)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            rows_out.append({"name": name, "spec": spec, "price": price_val, "unit": unit})

    return rows_out


def collect_cngold(existing_keys):
    """existing_keys: {(date, material, 'cngold')} 집합. 새로 수집한 요약/상세 행 목록을 반환합니다."""
    log("=== 금투망(cngold.org) 수집 시작 ===")
    try:
        listing_html = fetch(CNGOLD_LISTING_URL)
    except Exception as e:
        log(f"금투망 목록 페이지 요청 실패, 이번엔 건너뜀: {e}")
        return [], []

    articles = cngold_discover_articles(listing_html)
    log(f"금투망: 발견한 (날짜, 품목) 기사 수: {len(articles)}")

    summary_rows = []
    detail_rows = []

    for (date_str, code), url in sorted(articles.items()):
        if (date_str, code, "cngold") in existing_keys:
            continue

        log(f"  수집 중: {date_str} {code} <- {url}")
        try:
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            article_html = fetch(url)
        except Exception as e:
            log(f"    기사 요청 실패, 건너뜀: {e}")
            continue

        rows = cngold_parse_price_rows(article_html)
        if not rows:
            log("    가격 표를 찾지 못함, 건너뜀")
            continue

        prices = [r["price"] for r in rows]
        unit = rows[0]["unit"]

        summary_rows.append(
            {
                "date": date_str,
                "material": code,
                "source": "cngold",
                "avg_price": round(sum(prices) / len(prices), 2),
                "min_price": round(min(prices), 2),
                "max_price": round(max(prices), 2),
                "spec_count": len(prices),
                "unit": unit,
                "source_url": url,
            }
        )
        for r in rows:
            detail_rows.append(
                {
                    "date": date_str,
                    "material": code,
                    "source": "cngold",
                    "name": r["name"],
                    "spec": r["spec"],
                    "price": r["price"],
                    "unit": r["unit"],
                    "region": "",
                    "qty": "",
                    "source_url": url,
                }
            )

    log(f"금투망: 신규 요약 {len(summary_rows)}행 / 상세 {len(detail_rows)}행")
    return summary_rows, detail_rows


# ===========================================================================
# 출처 2: RawMex (rawmex.cn / 생의사)
# ===========================================================================
RAWMEX_MATERIAL_SID = {
    "PP": 70,
    "PE": 576,
    "PS": 128,
    "ABS": 129,
    "PC": 154,
    "POM": 257,
    "PA6": 155,
    "PA66": 153,
    "PET": 143,
    "HDPE": 158,
    "PVC": 72,
    "LDPE": 157,
}

RAWMEX_LISTING_URL_TMPL = "https://www.rawmex.cn/trade/s-{sid}/"
RAWMEX_PRICE_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*元\s*/\s*(吨|公斤|千克|kg)", re.IGNORECASE)
RAWMEX_POST_TIME_RE = re.compile(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")
PAGES_PER_MATERIAL = 1


def rawmex_normalize_url(href):
    if not href:
        return None
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return "https://www.rawmex.cn" + href
    return "https://www.rawmex.cn/" + href


def rawmex_listing_url(sid, page):
    if page <= 1:
        return RAWMEX_LISTING_URL_TMPL.format(sid=sid)
    return f"https://www.rawmex.cn/trade/s-{sid}-{page}/"


def rawmex_resolve_post_date(month, day, run_date):
    candidate = date(run_date.year, month, day)
    if (candidate - run_date).days > 3:
        candidate = date(run_date.year - 1, month, day)
    return candidate


def rawmex_parse_listing_page(html, run_date):
    """품목별 매물 목록 표에서 [{date, name, spec, price, qty, region, url}, ...] 를 뽑아냅니다."""
    soup = BeautifulSoup(html, "lxml")
    rows_out = []

    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 8:
                continue

            price_m = RAWMEX_PRICE_RE.search(tds[2].get_text(" ", strip=True))
            if not price_m:
                continue  # "议价"(협의가) 등 숫자 가격이 없는 매물은 건너뜀
            price_val = float(price_m.group(1).replace(",", ""))
            unit = price_m.group(2)
            if unit in ("公斤", "千克", "kg"):
                price_val *= 1000

            post_m = RAWMEX_POST_TIME_RE.search(tds[7].get_text(" ", strip=True))
            if not post_m:
                continue
            mo, d, hh, mm = (int(x) for x in post_m.groups())
            post_date = rawmex_resolve_post_date(mo, d, run_date)

            name = tds[0].get_text(strip=True)
            name = re.sub(r"^[【\[](卖|买|SELL|BUY)[】\]]", "", name, flags=re.IGNORECASE).strip()
            spec = tds[1].get_text(strip=True)
            qty = tds[3].get_text(strip=True)
            region = tds[6].get_text(" ", strip=True)

            link = tds[0].find("a")
            url = rawmex_normalize_url(link["href"]) if link and link.has_attr("href") else None

            rows_out.append(
                {
                    "date": post_date.isoformat(),
                    "name": name,
                    "spec": spec,
                    "price": price_val,
                    "qty": qty,
                    "region": region,
                    "url": url,
                }
            )

    return rows_out


def collect_rawmex_material(code, sid, run_date, existing_keys):
    all_rows = []
    for page in range(1, PAGES_PER_MATERIAL + 1):
        url = rawmex_listing_url(sid, page)
        log(f"  매물 목록 요청: {code} (page {page}) <- {url}")
        try:
            html = fetch(url)
        except Exception as e:
            log(f"    요청 실패, 건너뜀: {e}")
            continue
        all_rows.extend(rawmex_parse_listing_page(html, run_date))
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    if not all_rows:
        log(f"    {code}: 파싱된 매물 없음")
        return [], []

    by_date = {}
    for r in all_rows:
        by_date.setdefault(r["date"], []).append(r)

    summary_rows = []
    detail_rows = []
    listing_page_url = rawmex_listing_url(sid, 1)

    for d, rows in by_date.items():
        if (d, code, "rawmex") in existing_keys:
            continue
        prices = [r["price"] for r in rows]
        summary_rows.append(
            {
                "date": d,
                "material": code,
                "source": "rawmex",
                "avg_price": round(sum(prices) / len(prices), 2),
                "min_price": round(min(prices), 2),
                "max_price": round(max(prices), 2),
                "spec_count": len(prices),
                "unit": "元/吨",
                "source_url": listing_page_url,
            }
        )
        for r in rows:
            detail_rows.append(
                {
                    "date": d,
                    "material": code,
                    "source": "rawmex",
                    "name": r["name"],
                    "spec": r["spec"],
                    "price": r["price"],
                    "unit": "元/吨",
                    "region": r["region"],
                    "qty": r["qty"],
                    "source_url": r["url"] or listing_page_url,
                }
            )

    return summary_rows, detail_rows


def collect_rawmex(existing_keys):
    log("=== RawMex(rawmex.cn) 수집 시작 ===")
    summary_rows = []
    detail_rows = []
    for code, sid in RAWMEX_MATERIAL_SID.items():
        s_rows, d_rows = collect_rawmex_material(code, sid, date.today(), existing_keys)
        summary_rows.extend(s_rows)
        detail_rows.extend(d_rows)
        existing_keys.update((r["date"], r["material"], "rawmex") for r in s_rows)
    log(f"RawMex: 신규 요약 {len(summary_rows)}행 / 상세 {len(detail_rows)}행")
    return summary_rows, detail_rows


# ===========================================================================
# 환율(USD/CNY) 수집 (두 출처 공통)
# ===========================================================================
def fetch_fx_usd_cny():
    try:
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get("CNY")
        if rate:
            return float(rate)
    except Exception as e:
        log(f"환율 조회 실패 (open.er-api.com): {e}")

    try:
        resp = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rate = resp.json().get("rates", {}).get("CNY")
        if rate:
            return float(rate)
    except Exception as e:
        log(f"환율 조회 실패 (exchangerate-api.com): {e}")

    return None


# ===========================================================================
# 메인
# ===========================================================================
def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    existing_keys = read_existing_keys(PRICES_CSV, ["date", "material", "source"])

    cngold_summary, cngold_detail = collect_cngold(existing_keys)
    existing_keys.update((r["date"], r["material"], "cngold") for r in cngold_summary)

    rawmex_summary, rawmex_detail = collect_rawmex(existing_keys)

    all_summary = cngold_summary + rawmex_summary
    all_detail = cngold_detail + rawmex_detail

    append_rows(PRICES_CSV, SUMMARY_FIELDS, all_summary)
    append_rows(DETAIL_CSV, DETAIL_FIELDS, all_detail)
    log(f"전체 신규 저장: 요약 {len(all_summary)}행 (금투망 {len(cngold_summary)} + RawMex {len(rawmex_summary)}) "
        f"/ 상세 {len(all_detail)}행")

    # 환율 수집 (하루 1행, 출처 공통)
    today_str = date.today().isoformat()
    fx_existing = read_existing_keys(FX_CSV, ["date"])
    if (today_str,) not in fx_existing:
        rate = fetch_fx_usd_cny()
        if rate:
            append_rows(FX_CSV, ["date", "usd_cny"], [{"date": today_str, "usd_cny": rate}])
            log(f"환율 저장: {today_str} 1 USD = {rate} CNY")
        else:
            log("환율 조회 실패, 이번 실행에서는 fx.csv에 추가하지 않음")

    log("완료")


if __name__ == "__main__":
    main()
