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
    "e&w blog",
    "blog",
    "blogs",
    "get connected",
    "member corner",
    "in the news",
    "icymi",
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
            txt_l = txt.lower()
            if txt and txt_l not in BAD_TITLES:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", ""))
        txt = txt.split("|")[0].strip()
        txt_l = txt.lower()
        if txt and txt_l not in BAD_TITLES:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        txt = txt.split("|")[0].strip()
        txt_l = txt.lower()
        if txt and txt_l not in BAD_TITLES:
            return txt

    return ""


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


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []

    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".article-content p",
        ".newsContent p",
        ".entry-content p",
        ".field-content p",
        ".field--name-body p",
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


def build_detail_candidates(base_url: str, list_url: str, href: str) -> list[str]:
    """
    ASP 老站详情页常见问题：
    1) href 是相对路径，必须相对 list_url 去拼
    2) documentsingle.aspx 真实在 /news/documentsingle.aspx
    3) eventsingle.aspx 真实在 /calendar/eventsingle.aspx
    """
    href = (href or "").strip()
    if not href:
        return []

    base_host = urlparse(base_url).netloc
    parsed_href = urlparse(href)
    filename = parsed_href.path.split("/")[-1]
    query = parsed_href.query

    candidates = []

    # 1) 最优先：相对 list_url 拼接
    candidates.append(urljoin(list_url, href))

    # 2) 相对 base_url 拼接
    candidates.append(urljoin(base_url.rstrip("/") + "/", href))

    # 3) documentsingle 强制补 /news/
    if filename.lower() == "documentsingle.aspx":
        candidates.append(f"https://{base_host}/news/{filename}?{query}" if query else f"https://{base_host}/news/{filename}")

    # 4) eventsingle 强制补 /calendar/
    if filename.lower() == "eventsingle.aspx":
        candidates.append(f"https://{base_host}/calendar/{filename}?{query}" if query else f"https://{base_host}/calendar/{filename}")

    # 5) 最后兜底：根目录
    if filename:
        candidates.append(f"https://{base_host}/{filename}?{query}" if query else f"https://{base_host}/{filename}")

    result = []
    seen = set()
    for url in candidates:
        norm = normalize_link(url)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)

    return result


def try_fetch_detail(detail_candidates: list[str]):
    last_error = None

    for candidate in detail_candidates:
        try:
            soup = fetch(candidate)
            return candidate, soup
        except Exception as e:
            last_error = e

    raise last_error if last_error else RuntimeError("详情页抓取失败")


def collect_detail_links(list_url: str, base_url: str, detail_patterns: list[str]):
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        href_l = href.lower()
        if not any(p.lower() in href_l for p in (detail_patterns or [])):
            continue

        candidates = build_detail_candidates(base_url, list_url, href)
        if not candidates:
            continue

        # 这里只取第一个“规范链接”作为去重入口
        norm = candidates[0]
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append((norm, candidates))

    return detail_urls


def run_asp_scraper(config: dict, existing_links=None):
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
        detail_patterns = section.get("detail_patterns", [])

        print(f"\n====== {category_en} ======")

        page = 1
        section_done = False
        seen_detail_urls = set()
        consecutive_skip_count = 0

        while not section_done:
            paged_url = list_url
            if page > 1:
                sep = "&" if "?" in list_url else "?"
                paged_url = f"{list_url}{sep}Page={page}"

            try:
                detail_rows = collect_detail_links(
                    list_url=paged_url,
                    base_url=base_url,
                    detail_patterns=detail_patterns,
                )
            except Exception as e:
                print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
                break

            if not detail_rows:
                print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
                break

            print(f"[{key}] 第 {page} 页候选链接: {len(detail_rows)} | {paged_url}")

            found_new_on_page = False

            for norm_entry, detail_candidates in detail_rows:
                if not norm_entry or norm_entry in seen_detail_urls:
                    continue
                seen_detail_urls.add(norm_entry)

                if norm_entry in existing_links:
                    print(f"跳过(已存在): {norm_entry}")
                    continue

                try:
                    real_url, detail_soup = try_fetch_detail(detail_candidates)
                    real_norm = normalize_link(real_url)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {norm_entry} | {e}")
                    continue

                title = extract_title(detail_soup)
                article_dt = extract_date_from_soup(detail_soup)

                if not title or title.lower() in BAD_TITLES:
                    print(f"跳过(无效标题): {real_norm}")
                    continue

                if not article_dt:
                    print(f"跳过(无标题/日期): {real_norm}")
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
                    "link": real_norm,
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