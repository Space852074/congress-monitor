# -*- coding: utf-8 -*-
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

BASE = "https://www.epw.senate.gov"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ========================
# 配置
# ========================
COMMITTEE_EN = "Senate Environment and Public Works Committee"
COMMITTEE_ZH = "美国参议院环境与公共工程委员会"
CHAMBER = "Senate"

DAYS_LIMIT = 10
MAX_SKIP = 5
MAX_EMPTY_PAGE = 5

BAD_TITLES = [
    "Filter", "Search", "View", "More", "Next", "Previous",
    "RSS", "Subscribe", "Home", "Back"
]

GUID_PATTERN = re.compile(r'ID=([A-F0-9\-]{36})', re.I)

# ========================
# 工具函数
# ========================
def normalize_link(link):
    if not link:
        return None
    if link.startswith("http"):
        return link
    return BASE + link

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "lxml")
    except:
        pass
    return None

def parse_date(text):
    if not text:
        return None
    text = text.strip()

    for fmt in [
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d"
    ]:
        try:
            dt = datetime.strptime(text, fmt)
            return dt
        except:
            continue
    return None

def extract_title(tag):
    if not tag:
        return None
    text = tag.get_text(strip=True)
    if not text:
        return None
    if any(bad.lower() in text.lower() for bad in BAD_TITLES):
        return None
    return text

def extract_date_from_soup(soup):
    if not soup:
        return None
    text = soup.get_text(" ", strip=True)
    m = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', text)
    if m:
        return parse_date(m.group(1))
    return None

def extract_summary(soup):
    if not soup:
        return ""

    # 优先段落
    ps = soup.select("p")
    texts = []
    for p in ps[:3]:
        t = p.get_text(strip=True)
        if t:
            texts.append(t)

    summary = " ".join(texts)
    return summary[:200]

def is_recent(dt):
    if not dt:
        return False
    return (datetime.now() - dt) <= timedelta(days=DAYS_LIMIT)

def format_date(dt):
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y/%m/%d")

# ========================
# 核心：收集详情页链接
# ========================
def collect_detail_links(soup, section):
    results = []

    for a in soup.select("a"):
        href = a.get("href")
        if not href:
            continue

        if "ID=" not in href:
            continue

        if not GUID_PATTERN.search(href):
            continue

        title = extract_title(a)
        if not title:
            continue

        link = normalize_link(href)

        # 查找同级或父级日期
        parent = a.find_parent()
        date_text = None

        if parent:
            txt = parent.get_text(" ", strip=True)
            m = re.search(r'([A-Z][a-z]+ \d{1,2}, \d{4})', txt)
            if m:
                date_text = m.group(1)

        dt = parse_date(date_text) if date_text else None

        results.append({
            "title": title,
            "link": link,
            "date": dt
        })

    return results

# ========================
# 主抓取逻辑
# ========================
def scrape_section(name, url, category_en, category_zh, party):
    results = []
    seen = set()

    skip_count = 0
    empty_page_count = 0
    page = 1

    while True:
        print(f"[{name}] 抓取页面: {url}")

        soup = fetch(url)
        if not soup:
            break

        items = collect_detail_links(soup, name)

        print(f"[{name}] 第 {page} 页候选链接: {len(items)} | {url}")

        if not items:
            print(f"[{name}] 第 {page} 页无候选链接，停止当前分类")
            break

        valid_count = 0

        for item in items:
            title = item["title"]
            link = item["link"]
            dt = item["date"]

            if not dt:
                detail_soup = fetch(link)
                dt = extract_date_from_soup(detail_soup)

            if not dt:
                print(f"跳过(无日期): {title}")
                continue

            if not is_recent(dt):
                print(f"跳过(超出最近10天): {title}")
                skip_count += 1
                if skip_count >= MAX_SKIP:
                    print("连续跳过达到5条，停止当前分类")
                    return results
                continue

            date_str, sort_date = format_date(dt)

            if (title, link, date_str) in seen:
                continue

            seen.add((title, link, date_str))

            detail_soup = fetch(link)
            summary = extract_summary(detail_soup)

            results.append({
                "committee_en": COMMITTEE_EN,
                "committee_zh": COMMITTEE_ZH,
                "chamber": CHAMBER,
                "category_en": category_en,
                "category": category_zh,
                "title": title,
                "summary": summary,
                "date": date_str,
                "sort_date": sort_date,
                "link": link,
                "party": party
            })

            valid_count += 1
            skip_count = 0

        if valid_count == 0:
            empty_page_count += 1
        else:
            empty_page_count = 0

        if empty_page_count >= MAX_EMPTY_PAGE:
            print(f"[{name}] 连续5页没有新增有效数据，停止当前分类")
            break

        # ⚠️ 该站无明确分页，直接停止
        break

    return results

# ========================
# 入口
# ========================
def run_committee():
    all_data = []

    print("\n====== Hearing ======")
    all_data += scrape_section(
        "hearings",
        "https://www.epw.senate.gov/public/index.cfm/hearings",
        "Hearing",
        "听证会",
        ""
    )

    print("\n====== Business Meeting ======")
    all_data += scrape_section(
        "business_meetings",
        "https://www.epw.senate.gov/public/index.cfm/business-meetings",
        "Business Meeting",
        "商务会议",
        ""
    )

    print("\n====== Republican Press Releases ======")
    all_data += scrape_section(
        "republican_press_releases",
        "https://www.epw.senate.gov/public/index.cfm/press-releases-republican",
        "Republican Press Release",
        "共和党新闻稿",
        "共和党"
    )

    print("\n====== Democratic Press Releases ======")
    all_data += scrape_section(
        "democratic_press_releases",
        "https://www.epw.senate.gov/public/index.cfm/press-releases-democratic",
        "Democratic Press Release",
        "民主党新闻稿",
        "民主党"
    )

    return all_data


if __name__ == "__main__":
    data = run_committee()
    print(f"\nTotal: {len(data)}")