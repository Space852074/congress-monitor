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
MAX_PAGES = 50
MAX_EMPTY_PAGES = 5
REQUEST_TIMEOUT = 20
SLEEP_SECONDS = 0.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Special Committee on Aging"
COMMITTEE_ZH = "美国参议院老龄问题特别委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.aging.senate.gov"

BAD_TITLES = {
    "",
    "hearings",
    "hearing",
    "press room",
    "majority press",
    "minority press",
    "joint press",
    "calendar",
    "witness directory",
    "filter",
    "collapse",
    "search",
    "next",
    "previous",
    "update",
    "about",
    "contact",
    "resources",
    "home",
    "read more",
    "ranking member",
    "committee members",
    "resource library",
    "fraud and scams resources",
    "committee products",
    "featured button fraud hotline",
}

SECTIONS = [
    {
        "key": "hearings",
        "category_en": "Hearing",
        "category": "听证会",
        "party": "",
        "list_url": "https://www.aging.senate.gov/hearings",
        "blocked_paths": {
            "/hearings",
            "/hearings/",
            "/calendar",
            "/witness-directory",
        },
    },
    {
        "key": "majority_news",
        "category_en": "Republican News",
        "category": "共和党新闻",
        "party": "共和党",
        "list_url": "https://www.aging.senate.gov/press-room/majority",
        "blocked_paths": {
            "/press-room",
            "/press-room/",
            "/press-room/majority",
            "/press-room/majority/",
            "/press-room/minority",
            "/press-room/minority/",
            "/press-room/joint",
            "/press-room/joint/",
            "/hearings",
            "/about",
            "/resources",
            "/contact",
        },
    },
    {
        "key": "minority_news",
        "category_en": "Democratic News",
        "category": "民主党新闻",
        "party": "民主党",
        "list_url": "https://www.aging.senate.gov/press-room/minority",
        "blocked_paths": {
            "/press-room",
            "/press-room/",
            "/press-room/majority",
            "/press-room/majority/",
            "/press-room/minority",
            "/press-room/minority/",
            "/press-room/joint",
            "/press-room/joint/",
            "/hearings",
            "/about",
            "/resources",
            "/contact",
        },
    },
]

session = requests.Session()
session.headers.update(HEADERS)


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def fetch(url: str, timeout: int = REQUEST_TIMEOUT) -> BeautifulSoup:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_date(text: str):
    text = clean_text(text)
    if not text:
        return None

    text = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", text, flags=re.I)

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%b. %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regexes = [
        r"([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},\s+\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
    ]
    for pattern in regexes:
        m = re.search(pattern, text)
        if m:
            dt = parse_date(m.group(1))
            if dt:
                return dt

    return None


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".page-title",
        ".entry-title",
        "header h1",
        "h2",
    ]

    for selector in selectors:
        for node in soup.select(selector):
            title = clean_text(node.get_text(" ", strip=True))
            if title and title.lower() not in BAD_TITLES:
                return title

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        title = clean_text(meta_title.get("content", "")).split("|")[0].strip()
        if title and title.lower() not in BAD_TITLES:
            return title

    title_tag = soup.find("title")
    if title_tag:
        title = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if title and title.lower() not in BAD_TITLES:
            return title

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    candidates = []

    for selector in [
        "time",
        "main",
        "article",
        "header",
        "p",
        "div",
        "span",
        "li",
    ]:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if not txt:
                continue
            candidates.append(txt)

    preferred_patterns = [
        r"Published:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"Date:\s*([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"Date:\s*([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
    ]

    for txt in candidates:
        for pattern in preferred_patterns:
            m = re.search(pattern, txt)
            if m:
                dt = parse_date(m.group(1))
                if dt:
                    return dt

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates = []
    seen = set()

    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        "p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if not txt:
                continue
            if txt.lower().startswith(("published:", "date:", "time:", "location:", "watch:")):
                continue
            if len(txt) < 25:
                continue
            if txt in seen:
                continue
            seen.add(txt)
            candidates.append(txt)

    if not candidates:
        return ""

    summary = " ".join(candidates[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def parse_press_month_year(text: str):
    text = clean_text(text)
    m = re.search(r"([A-Z][a-z]+)\s+(\d{4})", text)
    if not m:
        return None
    month_name = m.group(1)
    year = int(m.group(2))
    try:
        month = datetime.strptime(month_name, "%B").month
        return year, month
    except Exception:
        return None


def parse_list_date_from_text(text: str, fallback_year: int | None = None):
    text = clean_text(text)
    if not text:
        return None

    dt = parse_date(text)
    if dt:
        return dt

    if fallback_year is not None:
        m = re.search(
            r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec))\.?\s+(\d{1,2})\b",
            text,
        )
        if m:
            month_abbr = m.group(1)
            day = int(m.group(2))
            month_abbr = "Sep" if month_abbr == "Sept" else month_abbr
            try:
                month = datetime.strptime(month_abbr, "%b").month
                return datetime(fallback_year, month, day)
            except Exception:
                pass

    return None


def looks_like_detail_url(url: str, section: dict) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    query = (parsed.query or "").lower()

    if host != "aging.senate.gov":
        return False

    if not path:
        return False

    blocked_paths = {p.rstrip("/").lower() for p in section.get("blocked_paths", set())}
    if path.lower() in blocked_paths:
        return False

    if "pagenum_rs=" in query:
        return False

    bad_roots = {
        "",
        "/",
        "/press-room",
        "/about",
        "/resources",
        "/contact",
        "/search",
        "/sitemap",
    }
    if path.lower() in bad_roots:
        return False

    if section["key"] == "hearings":
        if path.lower().startswith("/hearings/") and path.lower() not in {"/hearings", "/hearings/"}:
            return True
        return False

    if section["key"] in {"majority_news", "minority_news"}:
        if path.lower().startswith("/press-releases/") and path.lower() not in {
            "/press-releases",
            "/press-releases/",
        }:
            return True

        bad_prefixes = (
            "/wp-content/",
            "/wp-json/",
            "/tag/",
            "/category/",
            "/author/",
        )
        if path.lower().startswith(bad_prefixes):
            return False

        banned_slugs = {
            "majority",
            "minority",
            "joint",
            "hearings",
            "calendar",
            "witness-directory",
            "press-room",
            "about",
            "resources",
            "contact",
        }
        slug = path.strip("/").lower()
        if slug in banned_slugs:
            return False

        return True

    return False


def build_page_url(list_url: str, page: int) -> str:
    if page == 1:
        return list_url
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}pagenum_rs={page}"


def _unique_tag_blocks(tags):
    seen = set()
    result = []
    for tag in tags:
        if not isinstance(tag, Tag):
            continue
        ident = id(tag)
        if ident in seen:
            continue
        seen.add(ident)
        result.append(tag)
    return result



def collect_hearing_candidates(soup: BeautifulSoup, section: dict) -> list[dict]:
    candidates = []
    seen = set()

    main = soup.select_one("main") or soup

    # Aging hearing列表页更像“标题链接 + 若干文本行”的目录页，
    # 直接扫详情链接比先猜块结构更稳。
    for a in main.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = clean_text(a.get_text(" ", strip=True))

        if not href or not title:
            continue
        if len(title) < 8:
            continue
        if title.lower() in BAD_TITLES:
            continue

        full_url = urljoin(BASE_URL, href)
        if not looks_like_detail_url(full_url, section):
            continue

        norm_link = normalize_link(full_url)
        if norm_link in seen:
            continue

        # 优先从最近的可读容器里找日期；若还没有，再扩大到父级/祖父级。
        context_parts = []
        for node in [a, a.parent, getattr(a.parent, "parent", None), getattr(getattr(a.parent, "parent", None), "parent", None)]:
            if isinstance(node, Tag):
                txt = clean_text(node.get_text(" ", strip=True))
                if txt and txt not in context_parts:
                    context_parts.append(txt)

        context_text = " | ".join(context_parts)
        list_dt = parse_list_date_from_text(context_text)

        # 若容器中仍没解析出日期，再尝试从链接后面相邻文本补抓
        if list_dt is None:
            sibling_bits = []
            sib = a.next_sibling
            hop = 0
            while sib is not None and hop < 8:
                txt = clean_text(getattr(sib, "get_text", lambda *args, **kwargs: str(sib))(" ", strip=True) if isinstance(sib, Tag) else str(sib))
                if txt:
                    sibling_bits.append(txt)
                sib = getattr(sib, "next_sibling", None)
                hop += 1
            if sibling_bits:
                list_dt = parse_list_date_from_text(" | ".join(sibling_bits))

        seen.add(norm_link)
        candidates.append(
            {
                "title": title,
                "link": norm_link,
                "list_date": list_dt,
                "summary": "",
                "block_text": context_text,
            }
        )

    return candidates


def collect_press_candidates(soup: BeautifulSoup, section: dict) -> list[dict]:
    candidates = []
    seen = set()

    main = soup.select_one("main") or soup

    blocks = []
    for node in main.find_all(["li", "article", "div", "section"]):
        if not isinstance(node, Tag):
            continue

        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue

        # 新闻块需同时具备：日期 + press label + 至少一个详情链接
        has_date = bool(
            re.search(
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}\b",
                text,
                flags=re.I,
            )
        )
        has_press_label = any(
            label in text.lower()
            for label in ["majority press", "minority press", "joint press"]
        )

        if not (has_date and has_press_label):
            continue

        valid_link_found = False
        for a in node.select("a[href]"):
            href = (a.get("href") or "").strip()
            title = clean_text(a.get_text(" ", strip=True))
            if not href or not title or len(title) < 12:
                continue
            if title.lower() in BAD_TITLES:
                continue

            full_url = urljoin(BASE_URL, href)
            if looks_like_detail_url(full_url, section):
                valid_link_found = True
                break

        if valid_link_found:
            blocks.append(node)

    blocks = _unique_tag_blocks(blocks)

    fallback_year = None

    for block in blocks:
        block_text = clean_text(block.get_text(" ", strip=True))
        if not block_text:
            continue

        month_year = parse_press_month_year(block_text)
        if month_year:
            fallback_year = month_year[0]

        best_link = ""
        best_title = ""

        for a in block.select("a[href]"):
            href = (a.get("href") or "").strip()
            title = clean_text(a.get_text(" ", strip=True))

            if not href or not title:
                continue
            if len(title) < 12:
                continue
            if title.lower() in BAD_TITLES:
                continue

            full_url = urljoin(BASE_URL, href)
            if not looks_like_detail_url(full_url, section):
                continue

            best_link = normalize_link(full_url)
            best_title = title
            break

        if not best_link or not best_title:
            continue

        if best_link in seen:
            continue
        seen.add(best_link)

        list_dt = parse_list_date_from_text(block_text, fallback_year=fallback_year)

        summary = block_text
        if best_title in summary:
            summary = clean_text(summary.replace(best_title, "", 1))

        for label in ["Majority Press", "Minority Press", "Joint Press"]:
            summary = summary.replace(label, "")
        summary = clean_text(summary)

        if len(summary) > 200:
            summary = summary[:200].rstrip() + "..."

        candidates.append(
            {
                "title": best_title,
                "link": best_link,
                "list_date": list_dt,
                "summary": summary,
                "block_text": block_text,
            }
        )

    return candidates


def collect_detail_links(soup: BeautifulSoup, section: dict) -> list[dict]:
    if section["key"] == "hearings":
        return collect_hearing_candidates(soup, section)
    return collect_press_candidates(soup, section)


def build_item(section: dict, title: str, summary: str, article_dt: datetime, link: str) -> dict:
    summary = clean_text(summary or "")
    if len(summary) > 200:
        summary = summary[:200].rstrip() + "..."

    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": section["category_en"],
        "category": section["category"],
        "title": title,
        "summary": summary,
        "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": section["party"],
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    results = []

    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("sort_date", item.get("date", ""))),
        )
        if key in seen:
            continue
        seen.add(key)
        results.append(item)

    return results


def scrape_section(section: dict, existing_links=None) -> list[dict]:
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    results = []
    seen_links = set()
    consecutive_skip_count = 0
    consecutive_no_new_pages = 0

    print(f"\n====== {section['category_en']} ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = build_page_url(section["list_url"], page)

        try:
            soup = fetch(paged_url)
            candidates = collect_detail_links(soup, section)
        except Exception as e:
            print(f"[{section['key']}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not candidates:
            print(f"[{section['key']}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{section['key']}] 第 {page} 页候选链接: {len(candidates)} | {paged_url}")
        found_new_on_page = False

        for cand in candidates:
            norm_link = normalize_link(cand["link"])
            if not norm_link or norm_link in seen_links:
                continue
            seen_links.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            title = clean_text(cand.get("title", ""))
            if not title or title.lower() in BAD_TITLES:
                print(f"跳过(坏标题): {norm_link}")
                continue

            article_dt = cand.get("list_date")
            detail_soup = None

            if article_dt is None:
                try:
                    detail_soup = fetch(norm_link)
                    article_dt = extract_date_from_soup(detail_soup)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                    continue

                if article_dt is None:
                    print(f"跳过(无日期): {title}")
                    continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return dedupe_items(results)
                continue

            consecutive_skip_count = 0

            if detail_soup is None:
                try:
                    detail_soup = fetch(norm_link)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                    continue

            detail_title = extract_title(detail_soup) or title
            detail_dt = extract_date_from_soup(detail_soup) or article_dt

            if not detail_title or not detail_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            if detail_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {detail_title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return dedupe_items(results)
                continue

            summary = cand.get("summary") or extract_summary(detail_soup, limit=200)
            item = build_item(section, detail_title, summary, detail_dt, norm_link)
            results.append(item)
            found_new_on_page = True

            print(f"+ {detail_title}")
            time.sleep(SLEEP_SECONDS)

        if not found_new_on_page:
            consecutive_no_new_pages += 1
            print(f"[{section['key']}] 第 {page} 页没有新增有效数据")
            if consecutive_no_new_pages >= MAX_EMPTY_PAGES:
                print(f"[{section['key']}] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            consecutive_no_new_pages = 0

    return dedupe_items(results)


def run_committee(existing_links=None):
    all_items = []
    existing_links = existing_links or set()

    for section in SECTIONS:
        try:
            section_items = scrape_section(section, existing_links=existing_links)
            all_items.extend(section_items)
        except Exception as e:
            print(f"❌ 分类抓取失败: {section['key']} | {e}")

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)