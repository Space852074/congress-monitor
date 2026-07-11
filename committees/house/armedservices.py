# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
MAX_PAGES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "House Armed Services Committee"
COMMITTEE_ZH = "美国众议院军事委员会"
CHAMBER = "House"
BASE_URL = "https://armedservices.house.gov"


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str):
    text = clean_text(text)

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%A, %B %d, %Y")
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y")
        except Exception:
            pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    bad_titles = {
        "press releases",
        "press release",
        "hearings",
        "hearing",
        "news",
        "calendar",
    }

    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".documentTitle",
        ".newsTitle",
        ".content-header h1",
        "h2",
    ]

    for selector in selectors:
        nodes = soup.select(selector)
        for node in nodes:
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in bad_titles:
                return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if re.search(r"[A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
            candidates.append(txt)
        elif re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
            candidates.append(txt)
        elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", txt):
            candidates.append(txt)

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []

    selectors = [
        "main p",
        ".main-content p",
        ".content p",
        ".field-content p",
        "article p",
        ".newsbody p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                candidates.append(txt)

    if not candidates:
        for p in soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                candidates.append(txt)

    if not candidates:
        return ""

    summary = " ".join(candidates[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def build_item(category_en: str, category_zh: str, title: str, summary: str, article_dt: datetime, link: str) -> dict:
    return {
        "committee_en": COMMITTEE_EN,
        "committee_cn": COMMITTEE_ZH,
        "committee_zh": COMMITTEE_ZH,
        "committee": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": category_en,
        "category": category_zh,
        "title": title,
        "summary": summary,
        "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": "",
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []

    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            (item.get("sort_date") or "").strip(),
            (item.get("title") or "").strip().lower(),
            (item.get("category") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


# =========================
# 1) Press Releases
# =========================

def fix_press_release_url(url: str) -> str:
    url_l = url.lower()
    if "documentsingle.aspx" in url_l and "/news/" not in url_l:
        url = url.replace(
            "https://armedservices.house.gov/",
            "https://armedservices.house.gov/news/",
        )
        url = url.replace(
            "http://armedservices.house.gov/",
            "https://armedservices.house.gov/news/",
        )
    return url


def collect_press_release_links(list_url: str) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = requests.compat.urljoin(BASE_URL, href)
        full_url = fix_press_release_url(full_url)

        parsed = urlparse(full_url)
        if parsed.netloc.lower().replace("www.", "") != "armedservices.house.gov":
            continue

        if "documentsingle.aspx" not in full_url.lower():
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def scrape_press_releases(existing_links=None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    list_url = "https://armedservices.house.gov/news/documentquery.aspx?DocumentTypeID=27"

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    print("\n====== Press Release ======")

    while not section_done:
        paged_url = list_url if page == 1 else f"{list_url}&Page={page}"

        try:
            detail_urls = collect_press_release_links(paged_url)
        except Exception as e:
            print(f"[press_releases] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_urls:
            print(f"[press_releases] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[press_releases] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

        found_new_on_page = False

        for detail_url in detail_urls:
            norm_link = normalize_link(detail_url)

            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            try:
                soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            title = extract_title(soup)
            article_dt = extract_date_from_soup(soup)

            if not title or not article_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到 {SKIP_LIMIT} 次，停止当前分类")
                    section_done = True
                    break
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            summary = extract_summary(soup, limit=200)
            item = build_item("Press Release", "新闻稿", title, summary, article_dt, norm_link)
            items.append(item)
            print(f"+ {title}")

            time.sleep(0.2)

        if section_done:
            break

        if not found_new_on_page:
            print(f"[press_releases] 第 {page} 页没有新增有效数据")

        page += 1
        if page > MAX_PAGES:
            print("[press_releases] 达到分页上限，停止当前分类")
            break

    return items


# =========================
# 2) Hearings
# =========================

def collect_hearing_links(list_url: str) -> list[str]:
    resp = requests.get(list_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    ids = set(re.findall(r"EventID=(\d+)", html))
    urls = []

    for eid in ids:
        url = f"{BASE_URL}/calendar/eventsingle.aspx?EventID={eid}"
        urls.append(url)

    return urls


def scrape_hearings(existing_links=None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    list_url = "https://armedservices.house.gov/calendar/?EventTypeID=214"

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    print("\n====== Hearing ======")

    while not section_done:
        paged_url = list_url if page == 1 else f"{list_url}&Page={page}"

        try:
            detail_urls = collect_hearing_links(paged_url)
        except Exception as e:
            print(f"[hearings] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_urls:
            print(f"[hearings] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[hearings] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

        found_new_on_page = False

        for detail_url in detail_urls:
            norm_link = normalize_link(detail_url)

            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            try:
                soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            title = extract_title(soup)
            article_dt = extract_date_from_soup(soup)

            if not title or not article_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到 {SKIP_LIMIT} 次，停止当前分类")
                    section_done = True
                    break
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            summary = extract_summary(soup, limit=200)
            item = build_item("Hearing", "听证会", title, summary, article_dt, norm_link)
            items.append(item)
            print(f"+ {title}")

            time.sleep(0.2)

        if section_done:
            break

        if not found_new_on_page:
            print(f"[hearings] 第 {page} 页没有新增有效数据")

        page += 1
        if page > MAX_PAGES:
            print("[hearings] 达到分页上限，停止当前分类")
            break

    return items


def run_committee(existing_links=None):
    existing_links = existing_links or set()

    press_items = scrape_press_releases(existing_links)
    hearing_items = scrape_hearings(existing_links)

    all_items = press_items + hearing_items
    all_items = dedupe_items(all_items)
    return all_items


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)