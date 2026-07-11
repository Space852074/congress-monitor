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
MAX_PAGES = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


CONFIG = {
    "committee_en": "House Science, Space, and Technology Committee",
    "committee_zh": "美国众议院科学、空间与技术委员会",
    "committee": "美国众议院科学、空间与技术委员会",
    "chamber": "House",
    "base_url": "https://science.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://science.house.gov/press-releases",
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


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str):
    text = clean_text(text)

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
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

    m = re.search(r"([A-Z][a-z]+ \d{1,2})", text)
    if m:
        # science 列表页很多时候只有 March 18，没有年份
        year = datetime.now().year
        candidate = f"{m.group(1)}, {year}"
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(candidate, fmt)
            except Exception:
                pass

    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4})", text)
    if m:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except Exception:
                pass

    return None


def extract_title(detail_soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        ".page-title",
        ".field--name-title",
        ".entry-title",
        ".hero__title",
    ]
    for sel in selectors:
        node = detail_soup.select_one(sel)
        if node:
            txt = clean_text(node.get_text(" ", strip=True))
            if txt:
                return txt

    title_tag = detail_soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        if txt:
            return txt
    return ""


def extract_summary(detail_soup: BeautifulSoup, limit: int = 200) -> str:
    paragraphs = []

    selectors = [
        "article p",
        ".field--name-body p",
        ".main-content p",
        ".content p",
        "main p",
    ]

    for sel in selectors:
        for p in detail_soup.select(sel):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        for p in detail_soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        return ""

    summary = " ".join(paragraphs[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def collect_press_rows(soup: BeautifulSoup, base_url: str):
    rows = []
    seen = set()

    bad_keywords = {
        "/privacy",
        "/accessibility",
        "/copyright",
        "/contact",
        "/about",
    }

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)
        path = (parsed.path or "").rstrip("/")

        if parsed.netloc.lower().replace("www.", "") != urlparse(base_url).netloc.lower().replace("www.", ""):
            continue

        if any(k in path.lower() for k in bad_keywords):
            continue

        # Science 新闻稿真实详情页一般是 /2026/3/xxxx 这种
        if not re.search(r"^/\d{4}/\d{1,2}/.+", path):
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or len(title) < 8:
            continue

        parent = a.find_parent(["article", "div", "li", "section"]) or a.parent
        row_text = clean_text(parent.get_text(" ", strip=True))

        norm_link = normalize_link(full_url)
        if norm_link in seen:
            continue
        seen.add(norm_link)

        rows.append({
            "title": title,
            "link": norm_link,
            "row_text": row_text,
        })

    return rows


def run_section(section: dict, existing_links: set[str]):
    committee_en = CONFIG["committee_en"]
    committee_zh = CONFIG["committee_zh"]
    chamber = CONFIG["chamber"]
    base_url = CONFIG["base_url"]

    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]

    cutoff_date = datetime.now() - timedelta(days=TIME_WINDOW_DAYS)
    all_items = []
    seen_detail = set()

    print(f"\n====== {category_en} ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = list_url if page == 1 else f"{list_url}?page={page}"

        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[{section['key']}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        rows = collect_press_rows(soup, base_url)

        if not rows:
            print(f"[{section['key']}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{section['key']}] 第 {page} 页候选链接: {len(rows)} | {paged_url}")

        found_new = False
        old_count_on_page = 0

        for row in rows:
            link = row["link"]
            title_from_list = row["title"]
            row_text = row["row_text"]

            if not link or link in seen_detail:
                continue
            seen_detail.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            dt = parse_date(row_text)

            if not dt:
                try:
                    detail_soup = fetch(link)
                    detail_text = clean_text(detail_soup.get_text(" ", strip=True))
                    dt = parse_date(detail_text)
                except Exception:
                    dt = None
                    detail_soup = None
            else:
                detail_soup = None

            if not dt:
                print(f"跳过(无日期): {link}")
                continue

            if dt < cutoff_date:
                old_count_on_page += 1
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title_from_list}")
                continue

            if detail_soup is None:
                try:
                    detail_soup = fetch(link)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {link} | {e}")
                    continue

            title = extract_title(detail_soup) or title_from_list
            if not title:
                print(f"跳过(无标题): {link}")
                continue

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
                "date": f"{dt.year}年{dt.month}月{dt.day}日",
                "sort_date": dt.strftime("%Y-%m-%d"),
                "link": link,
                "party": "",
            }
            all_items.append(item)
            found_new = True
            print(f"+ {title}")
            time.sleep(0.2)

        if not found_new:
            print(f"[{section['key']}] 第 {page} 页没有新增有效数据")

        if old_count_on_page == len(rows):
            print(f"[{section['key']}] 第 {page} 页全部超出最近{TIME_WINDOW_DAYS}天，停止当前分类")
            break

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

    all_items = []
    for section in CONFIG["sections"]:
        try:
            items = run_section(section, existing_links)
            all_items.extend(items)
        except Exception as e:
            print(f"❌ {section['key']} 抓取失败: {e}")

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")
    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))