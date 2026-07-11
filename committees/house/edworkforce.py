# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.scraper_asp import run_asp_scraper

TIME_WINDOW_DAYS = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

ASP_CONFIG = {
    "committee_en": "House Education and Workforce Committee",
    "committee_zh": "美国众议院教育与劳工委员会",
    "chamber": "House",
    "base_url": "https://edworkforce.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://edworkforce.house.gov/news/documentquery.aspx?DocumentTypeID=1823",
            "detail_patterns": [
                "documentsingle.aspx?DocumentID=",
            ],
        },
        {
            "key": "ew_blog",
            "category_en": "E&W Blog",
            "category_zh": "博客",
            "list_url": "https://edworkforce.house.gov/news/documentquery.aspx?DocumentTypeID=1854",
            "detail_patterns": [
                "documentsingle.aspx?DocumentID=",
            ],
        },
        {
            "key": "hearings",
            "category_en": "Hearing",
            "category_zh": "听证会",
            "list_url": "https://edworkforce.house.gov/calendar/list.aspx?EventTypeID=189",
            "detail_patterns": [
                "eventsingle.aspx?EventID=",
            ],
        },
    ],
}


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


def parse_date(text: str):
    text = clean_text(text)

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y")
        except Exception:
            pass

    return None


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def extract_video_summary(block_text: str, limit: int = 200) -> str:
    txt = clean_text(block_text)
    if len(txt) > limit:
        txt = txt[:limit].rstrip() + "..."
    return txt


def scrape_videos(existing_links=None):
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    committee_en = "House Education and Workforce Committee"
    committee_zh = "美国众议院教育与劳工委员会"
    chamber = "House"
    base_url = "https://edworkforce.house.gov"
    list_url = "https://edworkforce.house.gov/videos/"

    cutoff_date = datetime.now() - timedelta(days=TIME_WINDOW_DAYS)
    all_items = []
    seen_links = set()

    print("\n====== Video ======")

    try:
        soup = fetch(list_url)
    except Exception as e:
        print(f"[videos] 列表页抓取失败: {list_url} | {e}")
        return []

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        title = clean_text(a.get_text(" ", strip=True))

        if not href:
            continue

        full_url = urljoin(base_url, href)
        norm_link = normalize_link(full_url)

        if "youtube.com" not in full_url.lower() and "youtu.be" not in full_url.lower():
            continue

        if not title:
            continue

        if norm_link in seen_links or norm_link in existing_links:
            continue
        seen_links.add(norm_link)

        parent = a
        block_text = ""
        dt = None
        for _ in range(5):
            if parent is None:
                break
            block_text = clean_text(parent.get_text(" ", strip=True))
            dt = parse_date(block_text)
            if dt:
                break
            parent = parent.parent

        if not dt:
            print(f"跳过(视频无日期): {title}")
            continue

        if dt < cutoff_date:
            print(f"跳过(视频超出最近{TIME_WINDOW_DAYS}天): {title}")
            continue

        summary = extract_video_summary(block_text, limit=200)

        item = {
            "committee_en": committee_en,
            "committee_cn": committee_zh,
            "committee_zh": committee_zh,
            "committee": committee_zh,
            "chamber": chamber,
            "category_en": "Video",
            "category": "视频",
            "title": title,
            "summary": summary,
            "date": f"{dt.year}年{dt.month}月{dt.day}日",
            "sort_date": dt.strftime("%Y-%m-%d"),
            "link": norm_link,
            "party": "",
        }

        all_items.append(item)
        print(f"+ {title}")
        time.sleep(0.2)

    return dedupe_items(all_items)


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


def run_committee(existing_links=None):
    existing_links = existing_links or set()

    asp_items = run_asp_scraper(ASP_CONFIG, existing_links)
    video_items = scrape_videos(existing_links)

    all_items = asp_items + video_items
    all_items = dedupe_items(all_items)

    return all_items


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")

    if not data:
        print("⚠️ 没有抓到数据，请优先检查：")
        print("1. run_asp_scraper 是否能正常抓 documentsingle / eventsingle")
        print("2. videos 页面结构是否变化")
        print("3. TIME_WINDOW_DAYS 是否过小")

    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))