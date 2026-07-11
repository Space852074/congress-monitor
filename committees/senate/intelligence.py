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
NO_NEW_PAGE_LIMIT = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Intelligence Committee"
COMMITTEE_ZH = "美国参议院情报委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.intelligence.senate.gov"

LEGISLATION_URL = "https://www.intelligence.senate.gov/legislation/"
HEARINGS_URL = "https://www.intelligence.senate.gov/category/hearings/open-hearings/"

BAD_TITLES = {
    "all legislation",
    "legislation",
    "senate bills",
    "public laws",
    "intelligence authorization acts",
    "all hearings & meetings",
    "open hearings",
    "closed meetings",
    "nominations",
    "transcripts",
    "committee calendar",
    "hearings & meetings",
    "hearing videos",
    "search for:",
    "print",
    "reports",
    "press releases",
    "committee members",
    "contact information",
    "rules of procedure",
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
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    query = parsed.query or ""

    return urlunparse((scheme, netloc, path, "", query, ""))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def fetch(url: str, timeout: int = 20) -> BeautifulSoup:
    resp = SESSION.get(url, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str):
    text = clean_text(text)
    if not text:
        return None

    text = (
        text.replace("Date & Time:", "")
        .replace("Date:", "")
        .replace("at", " ")
        .replace("A.M.", "AM")
        .replace("P.M.", "PM")
        .replace("a.m.", "AM")
        .replace("p.m.", "PM")
        .replace("am", "AM")
        .replace("pm", "PM")
    )
    text = re.sub(r"\s+", " ", text).strip()

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d, %Y %I:%M%p",
        "%b %d, %Y %I:%M%p",
        "%B %d, %Y %I:%M %p",
        "%b %d, %Y %I:%M %p",
        "%Y-%m-%d",
        "%m/%d/%Y",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    date_patterns = [
        r"([A-Z][a-z]{2,8} \d{1,2}, \d{4}\s+\d{1,2}:\d{2}\s*[AP]M)",
        r"([A-Z][a-z]{2,8} \d{1,2}, \d{4})",
    ]

    for pat in date_patterns:
        m = re.search(pat, text)
        if not m:
            continue
        candidate = re.sub(r"\s+", " ", m.group(1)).strip()
        for fmt in (
            "%B %d, %Y %I:%M%p",
            "%b %d, %Y %I:%M%p",
            "%B %d, %Y %I:%M %p",
            "%b %d, %Y %I:%M %p",
            "%B %d, %Y",
            "%b %d, %Y",
        ):
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
        ".entry-title",
        ".post-title",
        ".page-title",
        "header h1",
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


def extract_date_from_soup(soup: BeautifulSoup):
    selectors = [
        "time",
        ".post-date",
        ".entry-date",
        ".published",
        ".meta",
        ".post-meta",
        ".entry-meta",
        "span",
        "p",
        "div",
        "li",
    ]

    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if not txt or txt in seen:
                continue
            seen.add(txt)
            dt = parse_date(txt)
            if dt:
                return dt

    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    selectors = [
        "article p",
        ".entry-content p",
        ".post-content p",
        ".content p",
        "main p",
    ]

    parts = []
    seen = set()
    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if not txt or len(txt) < 20:
                continue
            low = txt.lower()
            if low in seen:
                continue
            seen.add(low)
            parts.append(txt)

    if not parts:
        return ""

    summary = " ".join(parts[:3]).strip()
    summary = re.sub(r"\s+", " ", summary)
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def is_date_permalink(link: str) -> bool:
    parsed = urlparse(link)
    host = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    if host != "intelligence.senate.gov":
        return False
    return bool(re.match(r"^/\d{4}/\d{2}/\d{2}/[^/]+$", path))


def is_valid_legislation_detail(link: str) -> bool:
    if not is_date_permalink(link):
        return False
    path = (urlparse(link).path or "").lower()
    bad_tokens = [
        "/open-hearing",
        "/closed-briefing",
        "/closed-hearing",
        "/nomination-hearing",
        "/hearing-",
    ]
    return not any(token in path for token in bad_tokens)


def is_valid_hearing_detail(link: str) -> bool:
    if not is_date_permalink(link):
        return False
    path = (urlparse(link).path or "").lower()
    hearing_tokens = [
        "/open-hearing",
        "/closed-briefing",
        "/closed-hearing",
        "/nomination-hearing",
        "/hearing-",
    ]
    return any(token in path for token in hearing_tokens)


def _find_candidate_container(a_tag):
    for parent in a_tag.parents:
        if getattr(parent, "name", None) in {"h1", "h2", "h3", "h4", "li", "div", "section"}:
            return parent
    return a_tag


def _collect_generic_blocks(list_url: str, validator):
    soup = fetch(list_url)
    rows = []
    seen = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = clean_text(a.get_text(" ", strip=True))
        if not href or not title:
            continue
        if title.lower() in BAD_TITLES:
            continue

        full_url = urljoin(BASE_URL, href)
        norm_link = normalize_link(full_url)
        if not validator(norm_link):
            continue
        if norm_link in seen:
            continue
        seen.add(norm_link)

        container = _find_candidate_container(a)
        container_text = clean_text(container.get_text(" ", strip=True))
        if len(container_text) < len(title):
            container_text = title

        row_dt = parse_date(container_text)
        rows.append(
            {
                "title": title,
                "link": norm_link,
                "row_dt": row_dt,
                "row_text": container_text,
            }
        )

    return rows


def collect_legislation_blocks(list_url: str):
    return _collect_generic_blocks(list_url, is_valid_legislation_detail)


def collect_hearing_blocks(list_url: str):
    return _collect_generic_blocks(list_url, is_valid_hearing_detail)


def build_item(category_en: str, category_zh: str, title: str, summary: str, article_dt: datetime, link: str) -> dict:
    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
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

    if list_url.endswith("/"):
        return f"{list_url}page/{page}/"
    return f"{list_url}/page/{page}/"


def scrape_section(
    *,
    key: str,
    category_en: str,
    category_zh: str,
    list_url: str,
    collector,
    existing_links: set[str],
) -> list[dict]:
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    items = []
    seen_detail_urls = set()
    consecutive_skip_count = 0
    consecutive_no_new_pages = 0

    print(f"\n====== {category_en} ======")

    while page <= MAX_PAGES:
        paged_url = make_paged_url(list_url, page)

        try:
            rows = collector(paged_url)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not rows:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(rows)} | {paged_url}")

        found_new_on_page = False

        for row in rows:
            norm_link = normalize_link(row["link"])
            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            title = clean_text(row.get("title", ""))
            row_dt = row.get("row_dt")
            detail_soup = None

            try:
                detail_soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            if not title:
                title = extract_title(detail_soup)

            if not row_dt:
                row_dt = extract_date_from_soup(detail_soup)

            if not title or title.lower() in BAD_TITLES or not row_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            if row_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            consecutive_skip_count = 0
            summary = extract_summary(detail_soup, limit=200)
            item = build_item(category_en, category_zh, title, summary, row_dt, norm_link)
            items.append(item)
            found_new_on_page = True
            print(f"+ {title}")
            time.sleep(0.2)

        if not found_new_on_page:
            consecutive_no_new_pages += 1
            print(f"[{key}] 第 {page} 页没有新增有效数据")
            if consecutive_no_new_pages >= NO_NEW_PAGE_LIMIT:
                print("连续5页没有新增有效数据，停止当前分类")
                break
        else:
            consecutive_no_new_pages = 0

        page += 1

    return items


def run_committee(existing_links=None):
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

    legislation_items = scrape_section(
        key="legislation",
        category_en="Legislation",
        category_zh="立法",
        list_url=LEGISLATION_URL,
        collector=collect_legislation_blocks,
        existing_links=existing_links,
    )

    hearing_items = scrape_section(
        key="hearings",
        category_en="Hearing",
        category_zh="听证会",
        list_url=HEARINGS_URL,
        collector=collect_hearing_blocks,
        existing_links=existing_links,
    )

    return dedupe_items(legislation_items + hearing_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)
