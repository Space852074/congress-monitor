# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

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

COMMITTEE_EN = "Senate Budget Committee"
COMMITTEE_ZH = "美国参议院预算委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.budget.senate.gov"

PRESS_SECTIONS = [
    {
        "key": "chairman_press",
        "category_en": "Press Release",
        "category_zh": "新闻稿",
        "list_url": "https://www.budget.senate.gov/chairman/newsroom/press/?type=press_release",
        "detail_prefix": "/chairman/newsroom/press/",
    },
    {
        "key": "ranking_member_press",
        "category_en": "Press Release",
        "category_zh": "新闻稿",
        "list_url": "https://www.budget.senate.gov/ranking-member/newsroom/press/?type=press_release",
        "detail_prefix": "/ranking-member/newsroom/press/",
    },
]

HEARING_SECTION = {
    "key": "hearings",
    "category_en": "Hearing",
    "category_zh": "听证会",
    "list_url": "https://www.budget.senate.gov/hearings",
    "detail_prefix": "/hearings/",
    "blocked_paths": {
        "/hearings",
        "/hearings/calendar",
        "/hearings/witnesses",
        "/hearings/add-to-calendar",
    },
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
        "%m.%d.%y",   # 04.03.26
        "%m.%d.%Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
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
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except Exception:
                pass

    m = re.search(r"(\d{2}\.\d{2}\.\d{2,4})", text)
    if m:
        for fmt in ("%m.%d.%y", "%m.%d.%Y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except Exception:
                pass

    m = re.search(r"(\d{2}/\d{2}/\d{2,4})", text)
    if m:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(m.group(1), fmt)
            except Exception:
                pass

    return None


def extract_title(detail_soup: BeautifulSoup) -> str:
    bad_titles = {
        "press",
        "press release",
        "press releases",
        "newsroom",
        "hearings",
        "hearing",
        "chairman's press",
        "ranking member press",
        "senate budget committee",
        "budget committee",
    }

    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".hero__title",
        ".entry-title",
        ".field--name-title",
        "h2",
    ]

    for selector in selectors:
        for node in detail_soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in bad_titles:
                return txt

    meta_title = detail_soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", "")).split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    title_tag = detail_soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if txt and txt.lower() not in bad_titles:
            return txt

    return ""


def extract_date_from_detail(detail_soup: BeautifulSoup):
    special_selectors = [
        ".submitted-date",
        ".date-display-single",
        ".field--name-field-date",
        "time",
    ]

    for selector in special_selectors:
        node = detail_soup.select_one(selector)
        if node:
            dt = parse_date(node.get_text(" ", strip=True))
            if dt:
                return dt

    for tag in detail_soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_summary_from_detail(detail_soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []

    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        ".field--name-body p",
        ".wysiwyg p",
    ]

    for selector in selectors:
        for p in detail_soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                candidates.append(txt)

    if not candidates:
        for p in detail_soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                candidates.append(txt)

    if not candidates:
        return ""

    summary = " ".join(candidates[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


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


def is_press_detail_url(full_url: str, detail_prefix: str) -> bool:
    parsed = urlparse(full_url)
    if parsed.netloc.lower().replace("www.", "") != "budget.senate.gov":
        return False

    path = (parsed.path or "").rstrip("/")
    prefix = detail_prefix.rstrip("/")

    # 必须在对应 press 前缀下
    if not path.startswith(prefix):
        return False

    # 不能等于栏目页本身
    if path == prefix:
        return False

    lower_path = path.lower()

    # 这里只排除明确不是详情页的栏目
    banned = [
        "/vote-a-rama",
        "/votearama",
        "/budget-bulletins",
    ]
    if any(x in lower_path for x in banned):
        return False

    return True


def collect_press_rows(list_url: str, detail_prefix: str) -> list[dict]:
    soup = fetch(list_url)
    rows = []
    seen = set()

    # 预算委员会新闻页结构：
    # 日期通常靠近 h2/h3 标题之前
    # 标题在 h2/h3 > a
    # 摘要通常在标题之后的文本块
    heading_nodes = soup.find_all(["h2", "h3"])

    for heading in heading_nodes:
        a = heading.find("a", href=True)
        if not a:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or len(title) < 8:
            continue

        full_url = urljoin(BASE_URL, a.get("href", "").strip())
        if not is_press_detail_url(full_url, detail_prefix):
            continue

        article_dt = None

        # 往前找最近日期
        prev = heading.previous_sibling
        back_steps = 0
        while prev is not None and back_steps < 8:
            if isinstance(prev, Tag):
                txt = clean_text(prev.get_text(" ", strip=True))
                article_dt = parse_date(txt)
                if article_dt:
                    break
            prev = prev.previous_sibling
            back_steps += 1

        # 兜底：父块整体文本里找日期
        if not article_dt:
            parent = heading.parent
            if parent:
                article_dt = parse_date(parent.get_text(" ", strip=True))

        if not article_dt:
            continue

        summary = ""

        # 往后取摘要
        nxt = heading.next_sibling
        forward_steps = 0
        while nxt is not None and forward_steps < 8:
            if isinstance(nxt, Tag):
                txt = clean_text(nxt.get_text(" ", strip=True))
                if txt and "Continue Reading" in txt:
                    txt = txt.replace("Continue Reading", "").strip()
                if len(txt) > 30:
                    summary = txt
                    break
            nxt = nxt.next_sibling
            forward_steps += 1

        # 再兜底：父块整体提炼摘要
        if not summary:
            parent = heading.parent
            if parent:
                block_text = clean_text(parent.get_text(" ", strip=True))
                block_text = block_text.replace(title, "").strip()
                block_text = block_text.replace("Continue Reading", "").strip()
                if len(block_text) > 30:
                    summary = block_text[:200]

        norm_link = normalize_link(full_url)
        if norm_link in seen:
            continue
        seen.add(norm_link)

        rows.append({
            "title": title,
            "summary": summary[:200],
            "date": article_dt,
            "link": norm_link,
        })

    return rows


def scrape_press_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]
    detail_prefix = section["detail_prefix"]

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
            rows = collect_press_rows(paged_url, detail_prefix)
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

            title = row["title"]
            article_dt = row["date"]
            summary = row["summary"]

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

            # 进入详情页补全
            try:
                detail_soup = fetch(norm_link)
                detail_title = extract_title(detail_soup)
                detail_dt = extract_date_from_detail(detail_soup)
                detail_summary = extract_summary_from_detail(detail_soup, limit=200)

                if detail_title:
                    title = detail_title
                if detail_dt:
                    article_dt = detail_dt
                if detail_summary:
                    summary = detail_summary
            except Exception as e:
                print(f"提示(详情页补全失败，保留列表页数据): {norm_link} | {e}")

            if article_dt.date() < cutoff_date:
                print(f"跳过(详情页日期超出最近{TIME_WINDOW_DAYS}天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到 {SKIP_LIMIT} 次，停止当前分类")
                    section_done = True
                    break
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

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


def collect_hearing_links(list_url: str, detail_prefix: str, blocked_paths: set[str]) -> list[str]:
    soup = fetch(list_url)
    detail_urls = []
    seen = set()
    blocked = {x.rstrip("/") for x in blocked_paths}

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "budget.senate.gov":
            continue

        path = (parsed.path or "").rstrip("/")
        if not path.startswith(detail_prefix.rstrip("/")):
            continue
        if path in blocked:
            continue

        norm = normalize_link(full_url)
        if norm not in seen:
            seen.add(norm)
            detail_urls.append(norm)

    return detail_urls


def scrape_hearings(existing_links=None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    section = HEARING_SECTION
    list_url = section["list_url"]

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls = set()
    items = []

    print("\n====== Hearing ======")

    while not section_done:
        paged_url = make_paged_url(list_url, page)

        try:
            detail_urls = collect_hearing_links(
                paged_url,
                detail_prefix=section["detail_prefix"],
                blocked_paths=section["blocked_paths"],
            )
        except Exception as e:
            print(f"[hearings] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not detail_urls:
            print(f"[hearings] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[hearings] 第 {page} 页候选链接: {len(detail_urls)} | {paged_url}")

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
            article_dt = extract_date_from_detail(soup)
            summary = extract_summary_from_detail(soup, limit=200)

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

            item = build_item("Hearing", "听证会", title, summary, article_dt, norm_link)
            items.append(item)
            print(f"+ {title}")
            time.sleep(0.2)

        if section_done:
            break

        if not found_new_on_page:
            print(f"[hearings] 第 {page} 页没有新增有效数据")

        page += 1
        if page > MAX_PAGES:
            print("[hearings] 达到分页上限，停止当前分类")
            break

    return items


def run_committee(existing_links=None):
    existing_links = existing_links or set()

    all_items = []
    for section in PRESS_SECTIONS:
        all_items.extend(scrape_press_section(section, existing_links))

    all_items.extend(scrape_hearings(existing_links))

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)