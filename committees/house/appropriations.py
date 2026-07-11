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

COMMITTEE_EN = "House Appropriations Committee"
COMMITTEE_ZH = "美国众议院拨款委员会"
CHAMBER = "House"
BASE_URL = "https://appropriations.house.gov"

SECTIONS = [
    {
        "key": "press_releases",
        "category_en": "Press Release",
        "category_zh": "新闻稿",
        "list_url": "https://appropriations.house.gov/news/press-releases",
        "detail_prefixes": ["/news/press-releases/"],
        "blocked_paths": {
            "/news/press-releases",
        },
    },
    {
        "key": "remarks",
        "category_en": "Remarks",
        "category_zh": "讲话",
        "list_url": "https://appropriations.house.gov/news/remarks",
        "detail_prefixes": ["/news/remarks/"],
        "blocked_paths": {
            "/news/remarks",
        },
    },
    {
        "key": "hearings",
        "category_en": "Hearings",
        "category_zh": "听证会",
        "list_url": "https://appropriations.house.gov/schedule/hearings",
        "detail_prefixes": ["/schedule/hearings/"],
        "blocked_paths": {
            "/schedule/hearings",
        },
    },
    {
        "key": "markups",
        "category_en": "Markups",
        "category_zh": "审议会议",
        "list_url": "https://appropriations.house.gov/schedule/markups",
        "detail_prefixes": ["/schedule/markups/"],
        "blocked_paths": {
            "/schedule/markups",
        },
    },
    {
        "key": "business_meetings",
        "category_en": "Business Meetings",
        "category_zh": "业务会议",
        "list_url": "https://appropriations.house.gov/schedule/business-meetings",
        "detail_prefixes": ["/schedule/business-meetings/"],
        "blocked_paths": {
            "/schedule/business-meetings",
        },
    },
]


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
        "%a, %m/%d/%Y - %H:%M:%S",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%A, %B %d, %Y")
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%B %d, %Y")
        except Exception:
            pass

    m = re.search(r"([A-Z][a-z]{2} \d{1,2}, \d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%b %d, %Y")
        except Exception:
            pass

    m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y")
        except Exception:
            pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    bad_titles = {
        "press releases",
        "press release",
        "remarks",
        "remark",
        "hearings",
        "hearing",
        "markups",
        "markup",
        "business meetings",
        "business meeting",
        "news",
        "schedule",
    }

    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".node__title",
        ".field--name-title",
        ".content-header h1",
        ".main-content h1",
        "h2",
    ]

    for selector in selectors:
        nodes = soup.select(selector)
        for node in nodes:
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in bad_titles:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", ""))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
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
        ".entry-content p",
        ".field--name-body p",
        ".node__content p",
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


def looks_like_detail(path: str, detail_prefixes: list[str], blocked_paths: set[str]) -> bool:
    path = (path or "").rstrip("/")
    blocked = {x.rstrip("/") for x in (blocked_paths or set())}

    if path in blocked:
        return False

    for prefix in detail_prefixes or []:
        prefix = prefix.rstrip("/")
        if path.startswith(prefix) and path != prefix:
            return True

    return False


def collect_detail_links(list_url: str, detail_prefixes: list[str], blocked_paths: set[str]) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != urlparse(BASE_URL).netloc.lower().replace("www.", ""):
            continue

        path = parsed.path or ""
        if not looks_like_detail(path, detail_prefixes, blocked_paths):
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def build_item(category_en: str, category_zh: str, title: str, summary: str, article_dt: datetime, link: str) -> dict:
    return {
        "committee_en": COMMITTEE_EN,
        "committee_cn": COMMITTEE_ZH,
        "committee_zh": COMMITTEE_ZH,
        "committee": COMMITTEE_ZH,
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
            (item.get("sort_date") or "").strip(),
            (item.get("title") or "").strip().lower(),
            (item.get("category") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


def make_paged_url(list_url: str, page: int) -> str:
    # 该站分页规则：
    # 第1页：不带 ?page
    # 第2页：?page=1
    # 第3页：?page=2
    if page == 1:
        return list_url

    page_index = page - 1
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}page={page_index}"


def scrape_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]
    detail_prefixes = section["detail_prefixes"]
    blocked_paths = section["blocked_paths"]

    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    while not section_done:
        paged_url = make_paged_url(list_url, page)

        try:
            detail_urls = collect_detail_links(
                list_url=paged_url,
                detail_prefixes=detail_prefixes,
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

            if not title or not article_dt:
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

            summary = extract_summary(soup, limit=200)

            item = build_item(
                category_en=category_en,
                category_zh=category_zh,
                title=title,
                summary=summary,
                article_dt=article_dt,
                link=norm_link,
            )
            items.append(item)
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

    return items


def run_committee(existing_links=None):
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

    all_items = []

    for section in SECTIONS:
        try:
            section_items = scrape_section(section, existing_links)
            all_items.extend(section_items)
        except Exception as e:
            print(f"❌ 分类抓取失败: {section.get('key')} | {e}")

    all_items = dedupe_items(all_items)
    return all_items


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)