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

COMMITTEE_EN = "Senate Commerce Committee"
COMMITTEE_ZH = "美国参议院商务、科学与交通委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.commerce.senate.gov"

SECTIONS = [
    {
        "key": "republican_news",
        "category_en": "Republican News",
        "category_zh": "共和党新闻",
        "list_url": "https://www.commerce.senate.gov/press/republican-news/",
        "mode": "detail_links",
        "detail_prefixes": ["/press/rep/release/"],
        "blocked_paths": {
            "/press/republican-news",
            "/press/republican-news/",
        },
    },
    {
        "key": "democratic_news",
        "category_en": "Democratic News",
        "category_zh": "民主党新闻",
        "list_url": "https://www.commerce.senate.gov/press/democratic-news/",
        "mode": "detail_links",
        "detail_prefixes": ["/press/dem/release/"],
        "blocked_paths": {
            "/press/democratic-news",
            "/press/democratic-news/",
        },
    },
    {
        "key": "hearings",
        "category_en": "Hearing",
        "category_zh": "听证会",
        "list_url": "https://www.commerce.senate.gov/hearings/",
        "mode": "detail_links",
        "detail_prefixes": ["/meetings/"],
        "blocked_paths": {
            "/hearings",
            "/hearings/",
            "/hearings/markups",
            "/hearings/markups/",
            "/meetings",
            "/meetings/",
        },
        "required_detail_type": "hearing",
    },
    {
        "key": "markups",
        "category_en": "Markup",
        "category_zh": "审议会议",
        "list_url": "https://www.commerce.senate.gov/hearings/markups/",
        "mode": "detail_links",
        "detail_prefixes": ["/meetings/"],
        "blocked_paths": {
            "/hearings/markups",
            "/hearings/markups/",
            "/meetings",
            "/meetings/",
        },
        "required_detail_type": "markup",
    },
    {
        "key": "legislation",
        "category_en": "Legislation",
        "category_zh": "立法",
        "list_url": "https://www.commerce.senate.gov/legislation/",
        "mode": "legislation_list",
    },
]

BAD_TITLES = {
    "republican news",
    "democratic news",
    "hearings",
    "hearing",
    "markups",
    "markup",
    "legislation",
    "press",
    "news",
    "commerce committee",
    "senate commerce committee",
    "previous article",
    "next article",
    "previous hearing",
    "next hearing",
    "previous markup",
    "next markup",
}


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
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
    if not text:
        return None

    candidates = [text]
    regexes = [
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{2}\.\d{2}\.\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pattern in regexes:
        m = re.search(pattern, text)
        if m:
            candidates.append(m.group(1))

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%m.%d.%y",
        "%m/%d/%Y",
    ]

    for candidate in candidates:
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
        ".entry-title",
        ".hero__title",
        ".node__title",
        ".content-header h1",
        "h2",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            low = txt.lower()
            if txt and low not in BAD_TITLES and "filter" not in low:
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
    text = soup.get_text("\n", strip=True)

    # 优先识别 Commerce 详情页上的 Date: ...
    m = re.search(r"Date:\s*([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text)
    if m:
        dt = parse_date(m.group(1))
        if dt:
            return dt

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue
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
        ".node__content p",
        ".field--name-body p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            low = txt.lower()
            if not txt or len(txt) <= 20:
                continue
            if low in {"print", "email", "share"}:
                continue
            candidates.append(txt)

    if not candidates:
        for p in soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                candidates.append(txt)

    if not candidates:
        return ""

    summary = re.sub(r"\s+", " ", " ".join(candidates[:3])).strip()
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

        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)
        if parsed.netloc.lower() != "www.commerce.senate.gov":
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
    if page == 1:
        return list_url
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}page={page}"


def detail_type_matches(soup: BeautifulSoup, required_detail_type: str | None) -> bool:
    if not required_detail_type:
        return True
    text = soup.get_text("\n", strip=True).lower()
    if required_detail_type == "hearing":
        return "\nhearing\n" in f"\n{text}\n" or "nomination hearing" in text
    if required_detail_type == "markup":
        return "\nmarkup\n" in f"\n{text}\n" or "executive session" in text
    return True


def scrape_detail_links_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]
    detail_prefixes = section["detail_prefixes"]
    blocked_paths = section["blocked_paths"]
    required_detail_type = section.get("required_detail_type")

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
            detail_urls = collect_detail_links(paged_url, detail_prefixes, blocked_paths)
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

            if not detail_type_matches(soup, required_detail_type):
                continue

            title = extract_title(soup)
            article_dt = extract_date_from_soup(soup)
            if not title:
                print(f"跳过(无标题): {norm_link}")
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
            summary = extract_summary(soup, limit=200)
            items.append(build_item(category_en, category_zh, title, summary, article_dt, norm_link))
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


def extract_legislation_records(soup: BeautifulSoup) -> list[dict]:
    text = soup.get_text("\n", strip=True)
    text = text.replace("\xa0", " ")

    pattern = re.compile(
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+"
        r"Title:\s*(?P<title>.*?)\s+"
        r"Sponsored by:\s*(?P<sponsor>.*?)\s+"
        r"Latest Action:\s*(?P<action>.*?)(?=(?:\d{4}-\d{2}-\d{2})\s+Title:|(?:\d{4}-\d{2}-\d{2})\s+Sponsored by:|Details:|Filter|$)",
        re.S,
    )

    records = []
    seen = set()
    for m in pattern.finditer(text):
        date_str = clean_text(m.group("date"))
        title = clean_text(m.group("title"))
        sponsor = clean_text(m.group("sponsor"))
        action = clean_text(m.group("action"))
        if not title or title.lower() in BAD_TITLES:
            continue
        key = (date_str, title.lower())
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "date_str": date_str,
            "title": title,
            "sponsor": sponsor,
            "action": action,
        })

    pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        txt = clean_text(a.get_text(" ", strip=True)).lower()
        if "congress.gov" in href and txt == "pdf":
            pdf_links.append(href)

    for idx, rec in enumerate(records):
        rec["link"] = pdf_links[idx] if idx < len(pdf_links) else "https://www.commerce.senate.gov/legislation/"

    return records


def scrape_legislation_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]

    print(f"\n====== {category_en} ======")
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()
    page = 1
    section_done = False
    consecutive_skip_count = 0
    items = []

    while not section_done:
        paged_url = make_paged_url(list_url, page)
        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        records = extract_legislation_records(soup)
        if not records:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(records)} | {paged_url}")
        found_new_on_page = False

        for rec in records:
            link = normalize_link(rec.get("link", ""))
            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            article_dt = parse_date(rec["date_str"])
            title = rec["title"]
            if not article_dt:
                print(f"跳过(无标题/日期): {title}")
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
            summary = clean_text(f"Sponsored by: {rec['sponsor']} Latest Action: {rec['action']}")
            if len(summary) > 200:
                summary = summary[:200].rstrip() + "..."
            items.append(build_item(category_en, category_zh, title, summary, article_dt, link or list_url))
            print(f"+ {title}")

        if section_done:
            break
        if not found_new_on_page:
            print(f"[{key}] 第 {page} 页没有新增有效数据")

        page += 1
        if page > MAX_PAGES:
            print(f"[{key}] 达到分页上限，停止当前分类")
            break

    return items


def scrape_section(section: dict, existing_links: set[str]) -> list[dict]:
    mode = section.get("mode", "detail_links")
    if mode == "legislation_list":
        return scrape_legislation_section(section, existing_links)
    return scrape_detail_links_section(section, existing_links)


def run_committee(existing_links=None):
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    all_items = []

    for section in SECTIONS:
        try:
            section_items = scrape_section(section, existing_links)
            all_items.extend(section_items)
        except Exception as e:
            print(f"❌ 分类抓取失败: {section.get('key')} | {e}")

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)
