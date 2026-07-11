# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
MAX_PAGES = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "House Homeland Security Committee"
COMMITTEE_ZH = "美国众议院国土安全委员会"
CHAMBER = "House"
BASE_URL = "https://homeland.house.gov"

SECTIONS = [
    {
        "key": "hearings",
        "category_en": "Hearing",
        "category_zh": "听证会",
        "list_url": "https://homeland.house.gov/hearings/",
        "mode": "hearings",
    },
    {
        "key": "press",
        "category_en": "Press Release",
        "category_zh": "新闻稿",
        "list_url": "https://homeland.house.gov/press/",
        "mode": "press",
    },
    {
        "key": "letters",
        "category_en": "Letter",
        "category_zh": "信函",
        "list_url": "https://homeland.house.gov/letters/",
        "mode": "letters",
    },
    {
        "key": "border_stats",
        "category_en": "Border Stats",
        "category_zh": "边境数据",
        "list_url": "https://homeland.house.gov/border-startling-stats/",
        "mode": "border_stats",
    },
]


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    return urlunparse(
        (
            (parsed.scheme or "https").lower(),
            parsed.netloc.lower().replace("www.", ""),
            (parsed.path or "").rstrip("/"),
            "",
            parsed.query,
            "",
        )
    )


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def try_fetch(url: str):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None


def parse_date(text: str):
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
        "%m/%d/%y",
        "%m/%d/%Y",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    m = re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", text)
    if m:
        try:
            return datetime.strptime(m.group(0), "%B %d, %Y")
        except Exception:
            pass

    m = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    if m:
        val = m.group(0)
        for fmt in ("%m/%d/%y", "%m/%d/%Y"):
            try:
                return datetime.strptime(val, fmt)
            except Exception:
                pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        "article h1",
        ".entry-title",
        ".page-title",
        ".elementor-heading-title",
        "main h1",
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            txt = clean_text(node.get_text(" ", strip=True))
            if len(txt) >= 5:
                return txt
    return ""


def extract_date_from_detail(soup: BeautifulSoup):
    selectors = [
        "time",
        ".posted-on",
        ".entry-date",
        ".elementor-post-info__item--type-date",
        ".post-date",
        "article time",
    ]

    for sel in selectors:
        for node in soup.select(sel):
            txt = clean_text(node.get_text(" ", strip=True))
            dt = parse_date(txt)
            if dt:
                return dt

            dt_attr = node.get("datetime")
            if dt_attr:
                dt_attr = dt_attr.strip()
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        return datetime.strptime(dt_attr[:19], fmt[:19])
                    except Exception:
                        pass

    for node in soup.find_all(["span", "div", "p", "li"]):
        txt = clean_text(node.get_text(" ", strip=True))
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_summary(soup: BeautifulSoup) -> str:
    selectors = [
        "article p",
        ".entry-content p",
        ".elementor-widget-theme-post-content p",
        "main p",
        ".content p",
    ]

    texts = []
    seen = set()

    for sel in selectors:
        for p in soup.select(sel):
            txt = clean_text(p.get_text(" ", strip=True))
            if len(txt) < 30:
                continue
            if txt in seen:
                continue
            seen.add(txt)
            texts.append(txt)
        if texts:
            break

    if not texts:
        return ""

    summary = " ".join(texts[:3])
    return summary[:200]


def get_total_pages(soup: BeautifulSoup, fallback_max=MAX_PAGES) -> int:
    text = soup.get_text(" ", strip=True)

    m = re.search(r"Page\s+\d+\s+of\s+(\d+)", text, re.I)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            pass

    nums = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        m = re.search(r"/page/(\d+)/?$", href)
        if m:
            try:
                nums.append(int(m.group(1)))
            except Exception:
                pass

    if nums:
        return max(nums)

    return fallback_max


def is_press_detail(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return bool(re.match(r"^/\d{4}/\d{2}/\d{2}/[^/]+$", path))


def is_hearing_detail(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    return path.startswith("/event/") and path not in {"/event", "/event/"}


def is_letter_detail(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    if re.match(r"^/\d{4}/\d{2}/\d{2}/[^/]+$", path):
        return True
    if path.startswith("/letters/") and path != "/letters":
        return True
    return False


def is_border_stats_detail(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    if path.startswith("/border-startling-stats/") and path != "/border-startling-stats":
        return True
    return False


def build_page_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    return urljoin(base_url, f"page/{page}/")


def collect_entries(list_url: str, mode: str):
    soup = fetch(list_url)
    total_pages = get_total_pages(soup)

    entries = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        full = normalize_link(urljoin(BASE_URL, href))
        if not full or full in seen:
            continue

        ok = False
        if mode == "press":
            ok = is_press_detail(full)
        elif mode == "hearings":
            ok = is_hearing_detail(full)
        elif mode == "letters":
            ok = is_letter_detail(full)
        elif mode == "border_stats":
            ok = is_border_stats_detail(full)

        if not ok:
            continue

        text_bits = []

        parent = a
        for _ in range(3):
            if parent is None:
                break
            txt = clean_text(parent.get_text(" ", strip=True))
            if txt:
                text_bits.append(txt)
            parent = parent.parent if hasattr(parent, "parent") else None

        merged_text = " | ".join(text_bits[:3])

        dt = parse_date(merged_text)
        title = clean_text(a.get_text(" ", strip=True))

        if len(title) < 5:
            title = ""

        entries.append(
            {
                "link": full,
                "list_date": dt,
                "list_title": title,
            }
        )
        seen.add(full)

    deduped = []
    seen2 = set()
    for item in entries:
        link = item["link"]
        if link in seen2:
            continue
        seen2.add(link)
        deduped.append(item)

    return deduped, total_pages


def parse_detail(link: str, list_title: str = "", list_date=None):
    soup = try_fetch(link)
    if soup is None:
        return "", None, ""

    title = extract_title(soup) or list_title
    dt = list_date or extract_date_from_detail(soup)
    summary = extract_summary(soup)

    return title, dt, summary


def scrape_section(section: dict, existing_links: set[str]):
    print(f"\n====== {section['category_en']} ======")

    cutoff = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    skip_count = 0
    items = []
    seen_links = set()

    first_soup = try_fetch(section["list_url"])
    if first_soup is None:
        print(f"[{section['key']}] 列表页无法访问")
        return items

    total_pages = get_total_pages(first_soup)
    total_pages = min(total_pages, MAX_PAGES)

    while page <= total_pages:
        url = build_page_url(section["list_url"], page)

        soup = try_fetch(url)
        if soup is None:
            print(f"[{section['key']}] 第{page}页无法访问，停止当前分类")
            break

        entries, _ = collect_entries(url, section["mode"])
        if not entries:
            print(f"[{section['key']}] 第{page}页无候选链接，停止当前分类")
            break

        print(f"第{page}页: {len(entries)}条")

        page_new_valid = 0

        for entry in entries:
            link = entry["link"]
            if link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                continue

            title, dt, summary = parse_detail(
                link=link,
                list_title=entry.get("list_title", ""),
                list_date=entry.get("list_date"),
            )

            if not title:
                print(f"跳过(无标题): {link}")
                continue

            if not dt:
                print(f"跳过(无日期): {title}")
                continue

            if dt.date() < cutoff:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                skip_count += 1
                if skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到 {SKIP_LIMIT} 次，停止当前分类")
                    return items
                continue

            skip_count = 0
            page_new_valid += 1

            items.append(
                {
                    "committee": COMMITTEE_ZH,
                    "committee_en": COMMITTEE_EN,
                    "chamber": CHAMBER,
                    "category": section["category_zh"],
                    "category_en": section["category_en"],
                    "title": title,
                    "summary": summary,
                    "date": f"{dt.year}年{dt.month}月{dt.day}日",
                    "sort_date": dt.strftime("%Y-%m-%d"),
                    "link": link,
                }
            )

            print(f"+ [{dt.strftime('%Y-%m-%d')}] {title}")
            time.sleep(0.15)

        if page_new_valid == 0:
            print(f"[{section['key']}] 第{page}页没有新增有效数据")

        page += 1

    return items


def run_committee(existing_links=None):
    existing_links = set(existing_links or [])
    all_items = []

    for section in SECTIONS:
        try:
            all_items.extend(scrape_section(section, existing_links))
        except Exception as e:
            print(f"[{section['key']}] 抓取失败: {e}")

    return all_items


if __name__ == "__main__":
    data = run_committee()

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row['sort_date']}] {row['category']} | {row['title']}")
        print("LINK:", row["link"])
        print("-" * 120)