# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.scraper_cms import run_cms_scraper

TIME_WINDOW_DAYS = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_date(text: str):
    text = clean_text(text)
    patterns = [
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

    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except Exception:
                pass

    return None


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def scrape_videos(existing_links=None):
    existing_links = existing_links or set()

    committee_en = "House Rules Committee"
    committee_zh = "美国众议院规则委员会"
    chamber = "House"
    base_url = "https://rules.house.gov"
    list_url = "https://rules.house.gov/media/videos"

    cutoff_date = datetime.now() - timedelta(days=TIME_WINDOW_DAYS)

    all_items = []
    seen_links = set()
    page = 1

    print("\n====== Video ======")

    while True:
        paged_url = list_url if page == 1 else f"{list_url}?page={page}"

        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[videos] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        cards = soup.select("div.views-row")
        if not cards:
            print(f"[videos] 第 {page} 页无卡片，停止当前分类")
            break

        print(f"[videos] 第 {page} 页候选卡片: {len(cards)} | {paged_url}")

        found_new = False

        for card in cards:
            a = card.select_one("a[href^='/media/videos/']")
            if not a:
                continue

            href = (a.get("href") or "").strip()
            if not href or href in {"/media/videos", "/media/videos/"}:
                continue

            link = urljoin(base_url, href)

            if link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if not title:
                continue

            card_text = clean_text(card.get_text(" ", strip=True))
            dt = parse_date(card_text)

            if not dt:
                m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", card_text)
                if m:
                    dt = parse_date(m.group(1))

            if not dt:
                print(f"跳过(列表页无日期): {link}")
                continue

            if dt < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                continue

            item = {
                "committee_en": committee_en,
                "committee_cn": committee_zh,
                "committee_zh": committee_zh,
                "committee": committee_zh,
                "chamber": chamber,
                "category_en": "Video",
                "category": "视频",
                "title": title,
                "summary": "",
                "date": f"{dt.year}年{dt.month}月{dt.day}日",
                "sort_date": dt.strftime("%Y-%m-%d"),
                "link": link,
                "party": "",
            }

            all_items.append(item)
            found_new = True
            print(f"+ {title}")

        if not found_new:
            print(f"[videos] 第 {page} 页没有新增有效数据")

        page += 1
        if page > 5:
            print("[videos] 达到分页上限，停止当前分类")
            break

    return all_items


CONFIG = {
    "committee_en": "House Rules Committee",
    "committee_zh": "美国众议院规则委员会",
    "chamber": "House",
    "base_url": "https://rules.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://rules.house.gov/media/press-releases",
            "detail_path_prefixes": [
                "/media/press-releases/",
            ],
            "blocked_paths": {
                "/media/press-releases",
                "/media/press-releases/",
            },
        },
        {
            "key": "announcements",
            "category_en": "Announcement",
            "category_zh": "公告",
            "list_url": "https://rules.house.gov/media/announcements",
            "detail_path_prefixes": [
                "/media/announcement/",
            ],
            "blocked_paths": {
                "/media/announcements",
                "/media/announcements/",
            },
        },
    ],
}


def run_committee(existing_links=None):
    existing_links = existing_links or set()

    cms_items = run_cms_scraper(CONFIG, existing_links)
    video_items = scrape_videos(existing_links)

    all_items = cms_items + video_items

    deduped = []
    seen = set()
    for item in all_items:
        key = (
            item.get("link", "").strip(),
            item.get("sort_date", "").strip(),
            item.get("title", "").strip().lower(),
            item.get("category", "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


if __name__ == "__main__":
    data = run_committee()
    print("\n====================")
    print(f"抓取到 {len(data)} 条")
    for row in data:
        print(f"[{row['sort_date']}] {row['category']} | {row['title']}")
        print(row["link"])