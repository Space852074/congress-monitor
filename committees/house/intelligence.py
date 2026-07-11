# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

TIME_WINDOW_DAYS = 10
MAX_PAGES = 10
SKIP_LIMIT = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
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


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str):
    text = clean_text(text)

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
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


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        ".entry-title",
        ".page-title",
        ".post-title",
        ".elementor-heading-title",
    ]
    for sel in selectors:
        node = soup.select_one(sel)
        if node:
            txt = clean_text(node.get_text(" ", strip=True))
            if txt:
                return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        if txt:
            return txt

    return ""


def extract_title_from_url(url: str) -> str:
    path = (urlparse(url).path or "").rstrip("/")
    slug = path.split("/")[-1] if path else ""
    if not slug:
        return ""

    title = slug.replace("-", " ").strip()
    title = re.sub(r"\s+", " ", title)
    return title.title()


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    paragraphs = []

    selectors = [
        "article p",
        ".entry-content p",
        ".post-content p",
        ".main-content p",
        ".content p",
        "main p",
    ]

    for sel in selectors:
        for p in soup.select(sel):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        for p in soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        return ""

    summary = " ".join(paragraphs[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def extract_date_from_detail(soup: BeautifulSoup):
    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
            candidates.append(txt)

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_date_from_url(url: str):
    path = urlparse(url).path or ""
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", path)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            return None
    return None


def collect_press_links(list_url: str, base_url: str):
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != urlparse(base_url).netloc.lower().replace("www.", ""):
            continue

        path = (parsed.path or "").rstrip("/")

        # 新闻稿真实详情页：/2026/03/23/xxx
        if not re.match(r"^/\d{4}/\d{2}/\d{2}/.+", path):
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def collect_hearing_links(list_url: str, base_url: str):
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != urlparse(base_url).netloc.lower().replace("www.", ""):
            continue

        path = (parsed.path or "").rstrip("/")

        # 听证会真实详情页：/event/xxx
        if not path.startswith("/event/"):
            continue

        # 排除 event-category
        if path.startswith("/event-category/"):
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def scrape_section(
    *,
    committee_en: str,
    committee_zh: str,
    chamber: str,
    category_en: str,
    category_zh: str,
    list_url: str,
    base_url: str,
    collector,
    existing_links: set[str],
):
    cutoff_date = datetime.now() - timedelta(days=TIME_WINDOW_DAYS)
    all_items = []
    seen_links = set()
    consecutive_skip_count = 0

    print(f"\n====== {category_en} ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = list_url if page == 1 else f"{list_url}?page={page}"

        try:
            detail_urls = collector(paged_url, base_url)
        except Exception as e:
            print(f"[{category_en}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_urls:
            print(f"[{category_en}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{category_en}] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

        found_new = False

        for detail_url in detail_urls:
            norm_link = normalize_link(detail_url)

            if not norm_link or norm_link in seen_links:
                continue
            seen_links.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            try:
                detail_soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            title = extract_title(detail_soup) or extract_title_from_url(norm_link)
            article_dt = extract_date_from_detail(detail_soup) or extract_date_from_url(norm_link)

            if not title or not article_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            if article_dt < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                consecutive_skip_count += 1

                if consecutive_skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到 {SKIP_LIMIT} 次，停止抓取当前分类")
                    return all_items
                continue

            consecutive_skip_count = 0

            summary = extract_summary(detail_soup, limit=200)

            item = {
                "committee_en": committee_en,
                "committee_cn": committee_zh,
                "committee_zh": committee_zh,
                "committee": committee_zh,
                "chamber": chamber,
                "category_en": category_en,
                "category": category_zh,
                "title": title,
                "summary": summary,
                "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
                "sort_date": article_dt.strftime("%Y-%m-%d"),
                "link": norm_link,
                "party": "",
            }

            all_items.append(item)
            found_new = True
            print(f"+ {title}")
            time.sleep(0.2)

        if not found_new:
            print(f"[{category_en}] 第 {page} 页没有新增有效数据")

    return all_items


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
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

    committee_en = "House Permanent Select Committee on Intelligence"
    committee_zh = "美国众议院情报特别委员会"
    chamber = "House"
    base_url = "https://intelligence.house.gov"

    press_items = scrape_section(
        committee_en=committee_en,
        committee_zh=committee_zh,
        chamber=chamber,
        category_en="Press Release",
        category_zh="新闻稿",
        list_url="https://intelligence.house.gov/category/press-releases/",
        base_url=base_url,
        collector=collect_press_links,
        existing_links=existing_links,
    )

    hearing_items = scrape_section(
        committee_en=committee_en,
        committee_zh=committee_zh,
        chamber=chamber,
        category_en="Hearing",
        category_zh="听证会",
        list_url="https://intelligence.house.gov/event-category/hearings/",
        base_url=base_url,
        collector=collect_hearing_links,
        existing_links=existing_links,
    )

    return dedupe_items(press_items + hearing_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")
    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))