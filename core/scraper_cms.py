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
MAX_PAGES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

BAD_TITLES = {
    "press releases",
    "press release",
    "news",
    "documents",
    "document",
    "hearings",
    "hearing",
    "events",
    "event",
    "calendar",
    "announcement",
    "announcements",
    "videos",
    "video",
    "blog",
    "blogs",
    "in the news",
    "updates",
    "press release updates",
    "in the news updates",
    "get connected",
    "e&w blog",
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
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%a, %m/%d/%Y - %H:%M",
        "%a, %m/%d/%Y - %I:%M %p",
        "%a, %m/%d/%Y - %H:%M:%S",
        "%a, %m/%d/%Y - %I:%M:%S %p",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regexes = [
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]{2},\s+\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}:\d{2}(?:\s*[AP]M)?)",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]

    for pattern in regexes:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = m.group(1)
        for fmt in patterns:
            try:
                return datetime.strptime(candidate, fmt)
            except Exception:
                pass

    return None


def extract_date_from_soup(soup: BeautifulSoup):
    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if re.search(r"[A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
            candidates.append(txt)
        elif re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
            candidates.append(txt)
        elif re.search(r"\d{1,2}/\d{1,2}/\d{4}", txt):
            candidates.append(txt)
        elif re.search(r"[A-Z][a-z]{2},\s+\d{1,2}/\d{1,2}/\d{4}\s*-\s*\d{1,2}:\d{2}", txt):
            candidates.append(txt)

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".documentTitle",
        ".newsTitle",
        ".entry-title",
        ".field--name-title",
        ".content-header h1",
        "h2",
    ]

    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in BAD_TITLES:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", ""))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    return ""


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []

    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".article-content p",
        ".entry-content p",
        ".field-content p",
        ".field--name-body p",
        ".newsContent p",
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
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def looks_like_detail(path: str, detail_path_prefixes: list[str], blocked_paths: set[str]) -> bool:
    path = (path or "").rstrip("/")
    blocked = {x.rstrip("/") for x in (blocked_paths or set())}

    if path in blocked:
        return False

    for prefix in detail_path_prefixes or []:
        prefix = prefix.rstrip("/")
        if path.startswith(prefix) and path != prefix:
            return True

    return False


def collect_detail_links(list_url: str, base_url: str, detail_path_prefixes: list[str], blocked_paths: set[str]):
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != urlparse(base_url).netloc.lower().replace("www.", ""):
            continue

        path = parsed.path or ""
        if not looks_like_detail(path, detail_path_prefixes, blocked_paths):
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def run_cms_scraper(config: dict, existing_links=None):
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    committee_en = config["committee_en"]
    committee_zh = config["committee_zh"]
    chamber = config["chamber"]
    base_url = config["base_url"]
    sections = config["sections"]

    all_items = []
    cutoff_date = datetime.now() - timedelta(days=TIME_WINDOW_DAYS)

    for section in sections:
        key = section["key"]
        category_en = section["category_en"]
        category_zh = section["category_zh"]
        list_url = section["list_url"]
        detail_path_prefixes = section.get("detail_path_prefixes", [])
        blocked_paths = section.get("blocked_paths", set())

        print(f"\n====== {category_en} ======")

        page = 1
        section_done = False
        seen_detail_urls = set()
        consecutive_skip_count = 0

        while not section_done:
            paged_url = list_url
            if page > 1:
                sep = "&" if "?" in list_url else "?"
                paged_url = f"{list_url}{sep}page={page}"

            try:
                detail_urls = collect_detail_links(
                    list_url=paged_url,
                    base_url=base_url,
                    detail_path_prefixes=detail_path_prefixes,
                    blocked_paths=blocked_paths,
                )
            except Exception as e:
                print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
                break

            if not detail_urls:
                print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
                break

            print(f"[{key}] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

            found_new_on_page = False

            for detail_url in detail_urls:
                norm_detail = normalize_link(detail_url)

                if not norm_detail or norm_detail in seen_detail_urls:
                    continue
                seen_detail_urls.add(norm_detail)

                if norm_detail in existing_links:
                    print(f"跳过(已存在): {norm_detail}")
                    continue

                try:
                    detail_soup = fetch(norm_detail)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {norm_detail} | {e}")
                    continue

                title = extract_title(detail_soup)
                article_dt = extract_date_from_soup(detail_soup)

                if not title or title.lower() in BAD_TITLES:
                    print(f"跳过(无效标题): {norm_detail}")
                    continue

                if not article_dt:
                    print(f"跳过(无标题/日期): {norm_detail}")
                    continue

                if article_dt < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title}")
                    consecutive_skip_count += 1
                    if consecutive_skip_count >= SKIP_LIMIT:
                        print(f"连续跳过达到 {SKIP_LIMIT} 次，停止抓取当前分类")
                        section_done = True
                        break
                    continue

                consecutive_skip_count = 0
                found_new_on_page = True

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
                    "link": norm_detail,
                    "party": "",
                }

                all_items.append(item)
                print(f"+ {title}")
                time.sleep(0.2)

            if section_done:
                break

            if not found_new_on_page:
                print(f"[{key}] 第 {page} 页没有新增有效数据")

            page += 1
            if page > MAX_PAGES:
                print(f"[{key}] 达到分页上限，停止当前分类")
                break

    return all_items