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

COMMITTEE_EN = "House Financial Services Committee"
COMMITTEE_ZH = "美国众议院金融服务委员会"
CHAMBER = "House"
BASE_URL = "https://financialservices.house.gov"

# 只保留你指定的栏目：Hearing / Markup / Press Release
SECTIONS = [
    {
        "key": "hearings",
        "category_en": "Hearing",
        "category_zh": "听证会",
        "mode": "event",
        "list_url": "https://financialservices.house.gov/calendar/?EventTypeID=309",
        "detail_pattern": "eventsingle.aspx?EventID=",
    },
    {
        "key": "markups",
        "category_en": "Markup",
        "category_zh": "审议会议",
        "mode": "event",
        "list_url": "https://financialservices.house.gov/calendar/?EventTypeID=311",
        "detail_pattern": "eventsingle.aspx?EventID=",
    },
    {
        "key": "press_releases",
        "category_en": "Press Release",
        "category_zh": "新闻稿",
        "mode": "document",
        "list_url": "https://financialservices.house.gov/news/documentquery.aspx?DocumentTypeID=2092",
        "detail_pattern": "documentsingle.aspx?DocumentID=",
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
    if not text:
        return None

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%A, %B %d, %Y | %I:%M %p",
        "%A, %B %d, %Y | %H:%M",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regex_candidates = [
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{4}-\d{2}-\d{2})",
    ]

    for pattern in regex_candidates:
        m = re.search(pattern, text)
        if not m:
            continue
        candidate = clean_text(m.group(1))
        for fmt in patterns:
            try:
                return datetime.strptime(candidate, fmt)
            except Exception:
                pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    bad_titles = {
        "hearings",
        "hearing",
        "markups",
        "markup",
        "press releases",
        "press release",
        "news",
        "calendar",
    }

    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".documentTitle",
        ".newsTitle",
        ".content-header h1",
        ".main-content h1",
        ".page-header h1",
        "h2",
    ]

    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in bad_titles:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", "")).split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    # 优先取 meta / time
    meta_selectors = [
        'meta[property="article:published_time"]',
        'meta[name="article:published_time"]',
        'meta[property="og:updated_time"]',
    ]
    for selector in meta_selectors:
        node = soup.select_one(selector)
        if node and node.get("content"):
            content = clean_text(node.get("content", ""))
            dt = parse_date(content)
            if dt:
                return dt
            try:
                return datetime.fromisoformat(content.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

    for time_tag in soup.find_all("time"):
        for value in [
            clean_text(time_tag.get("datetime", "")),
            clean_text(time_tag.get_text(" ", strip=True)),
        ]:
            if not value:
                continue
            dt = parse_date(value)
            if dt:
                return dt
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                pass

    # 通用扫描
    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td"]):
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
        ".field-content p",
        ".entry-content p",
        ".newsbody p",
        ".article-body p",
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


def build_item(
    category_en: str,
    category_zh: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
) -> dict:
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


def collect_document_links(list_url: str, detail_pattern: str) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        # 必须基于当前列表页拼接，保留 /news/ 路径
        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "financialservices.house.gov":
            continue

        if detail_pattern.lower() not in full_url.lower():
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def collect_event_links(list_url: str) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "financialservices.house.gov":
            continue

        href_l = full_url.lower()
        if "/calendar/eventsingle.aspx?eventid=" not in href_l:
            continue

        norm = normalize_link(full_url)
        if norm and norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def extract_date_from_event_list_item(anchor) -> datetime | None:
    """
    尝试从 hearing / markup 列表页里，直接从链接附近抽取日期。
    这样可避免详情页日期解析偶发失误，也避免旧 EventID 混杂导致误判。
    """
    candidates = []

    # 当前 a 标签文本
    txt = clean_text(anchor.get_text(" ", strip=True))
    if txt:
        candidates.append(txt)

    # 上级块文本
    parent = anchor.parent
    for _ in range(4):
        if not parent:
            break
        parent_txt = clean_text(parent.get_text(" ", strip=True))
        if parent_txt:
            candidates.append(parent_txt)
        parent = parent.parent

    # 前面的兄弟节点文本
    prev = anchor.previous_sibling
    hop = 0
    while prev is not None and hop < 3:
        try:
            prev_txt = clean_text(prev.get_text(" ", strip=True))
        except Exception:
            prev_txt = clean_text(str(prev))
        if prev_txt:
            candidates.append(prev_txt)
        prev = getattr(prev, "previous_sibling", None)
        hop += 1

    for text in candidates:
        dt = parse_date(text)
        if dt:
            return dt

        # 兼容 Apr 15 2026 这种格式
        m = re.search(r"([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})", text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%b %d %Y")
            except Exception:
                pass

        # 兼容 April 15, 2026
        m = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%B %d, %Y")
            except Exception:
                pass

    return None


def collect_event_links_with_dates(list_url: str) -> list[dict]:
    soup = fetch(list_url)
    results = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(list_url, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "financialservices.house.gov":
            continue

        href_l = full_url.lower()
        if "/calendar/eventsingle.aspx?eventid=" not in href_l:
            continue

        norm = normalize_link(full_url)
        if not norm or norm in seen:
            continue

        seen.add(norm)
        list_dt = extract_date_from_event_list_item(a)

        results.append({
            "url": norm,
            "list_dt": list_dt,
        })

    return results


def scrape_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]
    mode = section["mode"]

    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    while not section_done:
        paged_url = list_url if page == 1 else f"{list_url}&Page={page}"

        try:
            if mode == "document":
                detail_entries = [
                    {"url": x, "list_dt": None}
                    for x in collect_document_links(paged_url, section["detail_pattern"])
                ]
            else:
                detail_entries = collect_event_links_with_dates(paged_url)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_entries:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(detail_entries)} | {paged_url}")

        found_new_on_page = False

        for entry in detail_entries:
            detail_url = entry["url"]
            list_dt = entry.get("list_dt")

            norm_link = normalize_link(detail_url)
            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            # event 类优先使用列表页日期判断，避免详情页解析失误
            if mode == "event" and list_dt:
                if list_dt.date() < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {norm_link}")
                    consecutive_skip_count += 1
                    if consecutive_skip_count >= SKIP_LIMIT:
                        print(f"连续跳过达到 {SKIP_LIMIT} 次，停止当前分类")
                        section_done = True
                        break
                    continue

            try:
                soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            title = extract_title(soup)
            article_dt = extract_date_from_soup(soup)

            # event 如果详情页日期没拿到，就回退到列表页日期
            if mode == "event" and not article_dt and list_dt:
                article_dt = list_dt

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
            item = build_item(category_en, category_zh, title, summary, article_dt, norm_link)
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