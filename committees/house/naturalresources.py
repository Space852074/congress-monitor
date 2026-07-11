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
SKIP_LIMIT = 5
MAX_PAGES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "House Natural Resources Committee"
COMMITTEE_ZH = "美国众议院自然资源委员会"
CHAMBER = "House"
BASE_URL = "https://naturalresources.house.gov"


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
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    for pattern in [
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]:
        m = re.search(pattern, text)
        if m:
            candidate = m.group(1)
            for fmt in patterns:
                try:
                    return datetime.strptime(candidate, fmt)
                except Exception:
                    pass
    return None


def extract_title(soup: BeautifulSoup) -> str:
    bad_titles = {
        "newsletter sign up",
        "press release",
        "press releases",
        "news",
    }

    for selector in ["h1", "main h1", "article h1", ".page-title", ".entry-title", "h2"]:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in bad_titles:
                return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        dt = parse_date(txt)
        if dt:
            return dt
    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []
    for selector in ["article p", "main p", ".main-content p", ".content p", ".entry-content p"]:
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


def collect_news_links(list_url: str) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)
        path = (parsed.path or "").rstrip("/")

        if parsed.netloc.lower().replace("www.", "") != "naturalresources.house.gov":
            continue

        if path in {"/news", "/news/"}:
            continue

        if not path.startswith("/news/"):
            continue

        # 必须是 /news/2026/... 或 /news/article-slug 这种真实详情页
        # 过滤掉公用组件和栏目页
        if path.lower() in {
            "/news/newsletter-sign-up",
        }:
            continue

        title_text = clean_text(a.get_text(" ", strip=True)).lower()
        if title_text in {"newsletter sign up", "sign up", "read more"}:
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def scrape_news(existing_links: set[str]) -> list[dict]:
    print("\n====== Press Release ======")
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    while not section_done:
        paged_url = "https://naturalresources.house.gov/news/" if page == 1 else f"https://naturalresources.house.gov/news/?page={page}"

        try:
            detail_urls = collect_news_links(paged_url)
        except Exception as e:
            print(f"[news] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_urls:
            print(f"[news] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[news] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

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

            if not title or title.lower() == "newsletter sign up":
                print(f"跳过(无效标题): {norm_link}")
                continue

            if not article_dt:
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

            items.append({
                "committee_en": COMMITTEE_EN,
                "committee_cn": COMMITTEE_ZH,
                "committee_zh": COMMITTEE_ZH,
                "committee": COMMITTEE_ZH,
                "chamber": CHAMBER,
                "category_en": "Press Release",
                "category": "新闻稿",
                "title": title,
                "summary": extract_summary(soup, 200),
                "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
                "sort_date": article_dt.strftime("%Y-%m-%d"),
                "link": norm_link,
                "party": "",
            })
            print(f"+ {title}")
            time.sleep(0.2)

        if section_done:
            break

        if not found_new_on_page:
            print(f"[news] 第 {page} 页没有新增有效数据")

        page += 1
        if page > MAX_PAGES:
            print("[news] 达到分页上限，停止当前分类")
            break

    return items


ASP_CONFIG = {
    "committee_en": COMMITTEE_EN,
    "committee_zh": COMMITTEE_ZH,
    "chamber": CHAMBER,
    "base_url": BASE_URL,
    "sections": [
        {
            "key": "events",
            "category_en": "Event",
            "category_zh": "会议",
            "list_url": "https://naturalresources.house.gov/calendar/eventslisting.aspx",
            "detail_patterns": [
                "EventSingle.aspx?EventID=",
                "eventsingle.aspx?EventID=",
            ],
        },
    ],
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


def run_committee(existing_links=None):
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    news_items = scrape_news(existing_links)
    event_items = run_asp_scraper(ASP_CONFIG, existing_links)
    return dedupe_items(news_items + event_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")
    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))