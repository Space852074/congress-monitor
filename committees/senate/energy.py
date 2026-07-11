# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
MAX_PAGES = 50
PAGE_EMPTY_LIMIT = 5
REQUEST_GAP = 0.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Energy and Natural Resources Committee"
COMMITTEE_ZH = "美国参议院能源与自然资源委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.energy.senate.gov"

BAD_TITLES = {
    "republican news",
    "chairman's news",
    "democratic news",
    "hearings",
    "hearings and business meetings",
    "business meetings",
    "newsroom",
    "committee activity",
    "home",
}

SECTION_CONFIG = {
    "republican_news": {
        "category_en": "Republican News",
        "category": "共和党新闻",
        "party": "共和党",
        "list_url": "https://www.energy.senate.gov/republican-news",
    },
    "democratic_news": {
        "category_en": "Democratic News",
        "category": "民主党新闻",
        "party": "民主党",
        "list_url": "https://www.energy.senate.gov/democratic-news",
    },
    "hearings": {
        "category_en": "Hearing",
        "category": "听证会",
        "party": "",
        "list_url": "https://www.energy.senate.gov/hearings",
    },
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


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
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = SESSION.get(url, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str) -> Optional[datetime]:
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%b %d %Y",
        "%B %d %Y",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regexes = [
        r"([A-Z][a-z]+\s+\d{1,2},\s*\d{4})",
        r"([A-Z][a-z]{2}\s+\d{1,2},\s*\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pattern in regexes:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = clean_text(m.group(1))
        for fmt in patterns:
            try:
                return datetime.strptime(candidate, fmt)
            except Exception:
                pass

    # 兼容列表页中的 "Apr 8 Title" / "Mar 25 09:30 AM Title"
    m = re.match(r"^([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+\d{1,2}:\d{2}\s+[AP]M)?\b", text)
    if m:
        year = datetime.now().year
        candidate = f"{m.group(1)} {m.group(2)}, {year}"
        try:
            return datetime.strptime(candidate, "%b %d, %Y")
        except Exception:
            pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".main-content h1",
        ".content h1",
        "h2",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in BAD_TITLES:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", "")).split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup) -> Optional[datetime]:
    candidates: list[str] = []
    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if re.search(r"[A-Z][a-z]+\s+\d{1,2},\s*\d{4}", txt) or re.search(r"\d{4}-\d{2}-\d{2}", txt):
            candidates.append(txt)

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    full_text = clean_text(soup.get_text(" ", strip=True))
    return parse_date(full_text)


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    meta_desc = soup.select_one('meta[name="description"]')
    if meta_desc and meta_desc.get("content"):
        txt = clean_text(meta_desc.get("content", ""))
        if txt and len(txt) > 20:
            return txt[:limit].rstrip() + ("..." if len(txt) > limit else "")

    candidates: list[str] = []
    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
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


def is_valid_detail_url(section_key: str, url: str) -> bool:
    norm = normalize_link(url)
    if not norm:
        return False

    parsed = urlparse(norm)
    host = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    if host != "energy.senate.gov":
        return False

    if section_key == "hearings":
        if path in {"/hearings", "/business-meetings"}:
            return False
        return bool(re.match(r"^/hearings/\d{4}/\d{1,2}/[^/]+$", path))

    if path in {"/republican-news", "/democratic-news"}:
        return False
    if path.startswith("/hearings/"):
        return False
    return bool(re.match(r"^/\d{4}/\d{1,2}/[^/]+(?:/[^/]+)?$", path))


def parse_news_anchor_text(text: str) -> tuple[Optional[datetime], str]:
    text = clean_text(text)
    m = re.match(r"^([A-Z][a-z]{2}\s+\d{1,2})\s+(.+)$", text)
    if not m:
        return None, text
    dt = parse_date(f"{m.group(1)}, {datetime.now().year}")
    title = clean_text(m.group(2))
    return dt, title


def parse_hearing_anchor_text(text: str) -> tuple[Optional[datetime], str]:
    text = clean_text(text)
    m = re.match(r"^([A-Z][a-z]{2}\s+\d{1,2})(?:\s+\d{1,2}:\d{2}\s+[AP]M)?\s+(.+)$", text)
    if not m:
        return None, text
    dt = parse_date(f"{m.group(1)}, {datetime.now().year}")
    title = clean_text(m.group(2))
    return dt, title


def find_main_container(soup: BeautifulSoup) -> Tag:
    for selector in ["main", "article", ".main-content", ".content", "body"]:
        node = soup.select_one(selector)
        if node:
            return node
    return soup


def collect_detail_links(section_key: str, list_url: str) -> list[dict]:
    soup = fetch(list_url)
    container = find_main_container(soup)
    items: list[dict] = []
    seen: set[str] = set()

    # 先按块级结构找：月份标题 + 后续块
    headings = container.find_all(re.compile(r"^h[2-4]$"))
    for heading in headings:
        heading_text = clean_text(heading.get_text(" ", strip=True))
        if not re.match(r"^[A-Z][a-z]+\s+\d{4}$", heading_text):
            continue

        sibling = heading.find_next_sibling()
        while sibling:
            if isinstance(sibling, Tag) and sibling.name and re.match(r"^h[2-4]$", sibling.name):
                sibling_text = clean_text(sibling.get_text(" ", strip=True))
                if re.match(r"^[A-Z][a-z]+\s+\d{4}$", sibling_text):
                    break

            if isinstance(sibling, Tag):
                for a in sibling.find_all("a", href=True):
                    href = (a.get("href") or "").strip()
                    if not href or href.startswith("#") or href.startswith("javascript:"):
                        continue
                    full_url = urljoin(BASE_URL, href)
                    if not is_valid_detail_url(section_key, full_url):
                        continue

                    norm = normalize_link(full_url)
                    if norm in seen:
                        continue

                    anchor_text = clean_text(a.get_text(" ", strip=True))
                    if not anchor_text:
                        continue

                    if section_key == "hearings":
                        list_dt, title = parse_hearing_anchor_text(anchor_text)
                    else:
                        list_dt, title = parse_news_anchor_text(anchor_text)

                    items.append({
                        "link": norm,
                        "title": title,
                        "date": list_dt,
                    })
                    seen.add(norm)
            sibling = sibling.find_next_sibling()

    if items:
        return items

    # 回退：仍限制在主内容容器内，不扫全站导航
    for a in container.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full_url = urljoin(BASE_URL, href)
        if not is_valid_detail_url(section_key, full_url):
            continue

        norm = normalize_link(full_url)
        if norm in seen:
            continue

        anchor_text = clean_text(a.get_text(" ", strip=True))
        if not anchor_text:
            continue

        parent = a.find_parent(["li", "p", "div", "article", "section"]) or a
        row_text = clean_text(parent.get_text(" ", strip=True))

        if section_key == "hearings":
            list_dt, title = parse_hearing_anchor_text(anchor_text)
            if not list_dt:
                list_dt = parse_hearing_anchor_text(row_text)[0]
        else:
            list_dt, title = parse_news_anchor_text(anchor_text)
            if not list_dt:
                list_dt = parse_news_anchor_text(row_text)[0]

        items.append({
            "link": norm,
            "title": title,
            "date": list_dt,
        })
        seen.add(norm)

    return items


def build_item(section_key: str, title: str, summary: str, article_dt: datetime, link: str) -> dict:
    cfg = SECTION_CONFIG[section_key]
    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": cfg["category_en"],
        "category": cfg["category"],
        "title": title,
        "summary": summary[:200],
        "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": cfg["party"],
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("sort_date", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def make_paged_url(list_url: str, page: int) -> str:
    if page == 1:
        return list_url
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}page={page}"


def scrape_section(section_key: str, existing_links: Optional[set[str]] = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    cfg = SECTION_CONFIG[section_key]
    category_en = cfg["category_en"]
    list_url = cfg["list_url"]

    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()
    items: list[dict] = []
    seen_detail_urls: set[str] = set()
    consecutive_old_count = 0
    consecutive_no_new_pages = 0

    for page in range(1, MAX_PAGES + 1):
        paged_url = make_paged_url(list_url, page)
        try:
            candidates = collect_detail_links(section_key, paged_url)
        except Exception as e:
            print(f"[{section_key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not candidates:
            print(f"[{section_key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{section_key}] 第 {page} 页候选链接: {len(candidates)} | {paged_url}")

        page_new_count = 0

        for row in candidates:
            detail_url = normalize_link(row.get("link", ""))
            if not detail_url or detail_url in seen_detail_urls:
                continue
            seen_detail_urls.add(detail_url)

            if detail_url in existing_links:
                print(f"跳过(已存在): {detail_url}")
                continue

            title = clean_text(row.get("title", ""))
            list_dt = row.get("date")

            detail_soup = None
            try:
                detail_soup = fetch(detail_url)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {detail_url} | {e}")
                continue

            if not title:
                title = extract_title(detail_soup)
            else:
                detail_title = extract_title(detail_soup)
                if detail_title and detail_title.lower() not in BAD_TITLES:
                    title = detail_title

            article_dt = list_dt or extract_date_from_soup(detail_soup)

            if not article_dt:
                print(f"跳过(列表页无日期): {title or detail_url}")
                continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {title or detail_url}")
                consecutive_old_count += 1
                if consecutive_old_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return dedupe_items(items)
                continue

            if not title:
                print(f"跳过(无标题/日期): {detail_url}")
                continue

            consecutive_old_count = 0
            summary = extract_summary(detail_soup, limit=200)
            items.append(build_item(section_key, title, summary, article_dt, detail_url))
            page_new_count += 1
            print(f"+ {title}")
            time.sleep(REQUEST_GAP)

        if page_new_count == 0:
            consecutive_no_new_pages += 1
            print(f"[{section_key}] 第 {page} 页没有新增有效数据")
            if consecutive_no_new_pages >= PAGE_EMPTY_LIMIT:
                print(f"[{section_key}] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            consecutive_no_new_pages = 0

    return dedupe_items(items)


def run_committee(existing_links: Optional[set[str]] = None) -> list[dict]:
    existing_links = existing_links or set()
    all_items: list[dict] = []

    for section_key in ["republican_news", "democratic_news", "hearings"]:
        try:
            all_items.extend(scrape_section(section_key, existing_links))
        except Exception as e:
            print(f"❌ 分类抓取失败: {section_key} | {e}")

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)
