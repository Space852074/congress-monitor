# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
MAX_PAGES = 20
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Homeland Security and Governmental Affairs Committee"
COMMITTEE_ZH = "美国参议院国土安全与政府事务委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.hsgac.senate.gov"

BAD_TITLES = {
    "hearings",
    "hearing",
    "majority news",
    "minority news",
    "media",
    "legislation",
    "nominations",
    "legislation & nominations",
    "library",
    "search",
    "filter",
    "clear filters",
    "expand",
    "collapse",
    "update",
    "details",
    "pdf",
    "committee on homeland security & governmental affairs",
    "committee on homeland security and governmental affairs",
}

SECTIONS = [
    {
        "key": "hearings",
        "type": "hearings",
        "category_en": "Hearing",
        "category": "听证会",
        "list_url": "https://www.hsgac.senate.gov/hearings/",
        "party": "",
        "paged_mode": "page",
    },
    {
        "key": "majority_news",
        "type": "news",
        "category_en": "Republican News",
        "category": "共和党新闻",
        "list_url": "https://www.hsgac.senate.gov/media/majority-news/?jsf=jet-engine:press-list&meta=congress:119",
        "party": "共和党",
        "news_prefixes": ["/media/reps/", "/media/majority-news/"],
        "paged_mode": "page",
    },
    {
        "key": "minority_news",
        "type": "news",
        "category_en": "Democratic News",
        "category": "民主党新闻",
        "list_url": "https://www.hsgac.senate.gov/media/minority-news/?jsf=jet-engine:press-list&meta=congress:119",
        "party": "民主党",
        "news_prefixes": ["/media/dems/", "/media/minority-news/"],
        "paged_mode": "page",
    },
    {
        "key": "legislation",
        "type": "legislation",
        "category_en": "Legislation",
        "category": "立法",
        "list_url": "https://www.hsgac.senate.gov/legislation/",
        "party": "",
        "paged_mode": "bill_page",
    },
    {
        "key": "nominations",
        "type": "nominations",
        "category_en": "Nomination",
        "category": "提名",
        "list_url": "https://www.hsgac.senate.gov/legislation/nominations/",
        "party": "",
        "paged_mode": "nom_page",
    },
]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normalize_link(url: str) -> str:
    url = clean_text(url)
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = parsed.query
    return urlunparse((scheme, netloc, path, "", query, ""))


def fetch(url: str, timeout: int = REQUEST_TIMEOUT) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str) -> Optional[datetime]:
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        "%A, %B %d, %Y",
        "%a, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]
    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regexes = [
        (r"([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})", "%A, %B %d, %Y"),
        (r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", "%B %d, %Y"),
        (r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})", "%b %d, %Y"),
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{1,2}/\d{1,2}/\d{4})", "%m/%d/%Y"),
    ]
    for pattern, fmt in regexes:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            return datetime.strptime(m.group(1), fmt)
        except Exception:
            pass

    # 兼容新闻列表常见的月+日无年份格式（只用于最近10天判断）
    m = re.search(r"\b([A-Z][a-z]{2,8})\s+(\d{1,2})\b", text)
    if m:
        month_name, day_text = m.group(1), m.group(2)
        now = datetime.now()
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                candidate = datetime.strptime(f"{month_name} {day_text} {now.year}", fmt)
                if candidate.date() > now.date() + timedelta(days=31):
                    candidate = candidate.replace(year=now.year - 1)
                return candidate
            except Exception:
                continue

    return None


def extract_title(soup: BeautifulSoup) -> str:
    selectors = [
        "h1",
        "main h1",
        "article h1",
        ".entry-title",
        ".page-title",
        ".post-title",
        ".elementor-heading-title",
        "meta[property='og:title']",
        "title",
    ]

    for selector in selectors:
        nodes = soup.select(selector)
        for node in nodes:
            if getattr(node, "name", "") == "meta":
                text = clean_text(node.get("content", ""))
            else:
                text = clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            text = re.sub(r"\s*[|\-–—]\s*Committee on Homeland Security.*$", "", text, flags=re.I)
            if text and text.lower() not in BAD_TITLES:
                return text
    return ""


def extract_date_from_soup(soup: BeautifulSoup) -> Optional[datetime]:
    candidates: list[str] = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td"]):
        text = clean_text(tag.get_text(" ", strip=True))
        if not text:
            continue
        if any(
            re.search(pattern, text)
            for pattern in [
                r"[A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4}",
                r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}",
                r"\d{4}-\d{2}-\d{2}",
                r"\d{1,2}/\d{1,2}/\d{4}",
                r"\b[A-Z][a-z]{2,8}\s+\d{1,2}\b",
            ]
        ):
            candidates.append(text)

    for text in candidates:
        dt = parse_date(text)
        if dt:
            return dt
    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    paragraphs: list[str] = []
    selectors = [
        "article p",
        "main p",
        ".entry-content p",
        ".post-content p",
        ".elementor-widget-text-editor p",
        ".main-content p",
        ".content p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            text = clean_text(p.get_text(" ", strip=True))
            if text and len(text) > 20:
                paragraphs.append(text)

    if not paragraphs:
        for p in soup.find_all("p"):
            text = clean_text(p.get_text(" ", strip=True))
            if text and len(text) > 20:
                paragraphs.append(text)

    summary = clean_text(" ".join(paragraphs[:3]))
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def is_bad_link(url: str) -> bool:
    if not url:
        return True
    lowered = url.lower()
    return any(
        bad in lowered
        for bad in [
            "javascript:",
            "mailto:",
            "/feed/",
            "/privacy-policy/",
            "/privacy-policy",
            "/contact/",
            "/search/",
            "#",
        ]
    )


def make_paged_url(list_url: str, page: int, mode: str) -> str:
    if page == 1:
        return list_url

    parsed = urlparse(list_url)
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if mode == "page":
        qs["page"] = str(page)
    elif mode == "bill_page":
        qs["bill_page"] = str(page)
    elif mode == "nom_page":
        qs["nom_page"] = str(page)
    else:
        qs["page"] = str(page)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(qs),
            "",
        )
    )


def make_item(*, category_en: str, category: str, title: str, summary: str, article_dt: datetime, link: str, party: str) -> dict:
    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": category_en,
        "category": category,
        "title": title,
        "summary": summary[:200] if summary else "",
        "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": party,
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    deduped: list[dict] = []
    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("sort_date", "")),
            clean_text(item.get("category_en", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _first_valid_anchor(container: Tag, prefixes: list[str]) -> str:
    for a in container.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        if not href:
            continue
        full = normalize_link(urljoin(BASE_URL, href))
        path = urlparse(full).path
        if any(path.startswith(prefix) and path.rstrip("/") != prefix.rstrip("/") for prefix in prefixes):
            return full
    return ""


def _extract_title_near_anchor(container: Tag, anchor: Optional[Tag] = None) -> str:
    title_selectors = ["h3", "h4", "h5", ".entry-title", ".jet-listing-dynamic-field__content"]
    for selector in title_selectors:
        node = container.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text and text.lower() not in BAD_TITLES:
                return text

    if anchor:
        text = clean_text(anchor.get_text(" ", strip=True))
        if text and text.lower() not in BAD_TITLES:
            return text
    return ""


def _candidate_blocks(soup: BeautifulSoup, tags: list[str]) -> list[Tag]:
    blocks: list[Tag] = []
    seen_ids = set()
    for tag_name in tags:
        for node in soup.find_all(tag_name):
            text = clean_text(node.get_text(" ", strip=True))
            if not text:
                continue
            ident = id(node)
            if ident in seen_ids:
                continue
            seen_ids.add(ident)
            blocks.append(node)
    return blocks


def _collect_hearing_candidates(soup: BeautifulSoup) -> list[dict]:
    candidates: list[dict] = []
    seen_links = set()

    for row in soup.find_all("tr"):
        row_text = clean_text(row.get_text(" ", strip=True))
        if not row_text:
            continue
        link = _first_valid_anchor(row, ["/hearings/"])
        if not link or link in seen_links:
            continue
        if normalize_link(link) == normalize_link("https://www.hsgac.senate.gov/hearings"):
            continue
        title = _extract_title_near_anchor(row, row.find("a", href=True))
        list_dt = parse_date(row_text)
        seen_links.add(link)
        candidates.append({
            "title": title,
            "link": link,
            "list_date": list_dt,
            "row_text": row_text,
        })

    if candidates:
        return candidates

    for block in _candidate_blocks(soup, ["article", "li", "div", "section"]):
        block_text = clean_text(block.get_text(" ", strip=True))
        if not block_text:
            continue
        link = _first_valid_anchor(block, ["/hearings/"])
        if not link or link in seen_links:
            continue
        if normalize_link(link) == normalize_link("https://www.hsgac.senate.gov/hearings"):
            continue
        title = _extract_title_near_anchor(block, block.find("a", href=True))
        if not title:
            continue
        list_dt = parse_date(block_text)
        seen_links.add(link)
        candidates.append({
            "title": title,
            "link": link,
            "list_date": list_dt,
            "row_text": block_text,
        })
    return candidates



def _is_archive_like_title(title: str) -> bool:
    title = clean_text(title)
    if not title:
        return True

    if re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}", title, flags=re.I):
        return True

    if re.fullmatch(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{4}", title, flags=re.I):
        return True

    lowered = title.lower()
    bad_words = [
        "archive",
        "archives",
        "category",
        "categories",
        "older posts",
        "newer posts",
    ]

    return any(word in lowered for word in bad_words)


def _collect_news_candidates(soup: BeautifulSoup, prefixes: list[str]) -> list[dict]:
    candidates: list[dict] = []
    seen_links = set()

    for block in _candidate_blocks(soup, ["article", "li", "div", "section"]):
        block_text = clean_text(block.get_text(" ", strip=True))
        if not block_text:
            continue

        chosen_anchor = None
        chosen_link = ""
        for a in block.find_all("a", href=True):
            href = clean_text(a.get("href", ""))
            full = normalize_link(urljoin(BASE_URL, href))
            path = urlparse(full).path
            if any(path.startswith(prefix) and path.rstrip("/") != prefix.rstrip("/") for prefix in prefixes):
                chosen_anchor = a
                chosen_link = full
                break

        if not chosen_link or chosen_link in seen_links:
            continue

        title = _extract_title_near_anchor(block, chosen_anchor)
        if not title:
            continue

        if _is_archive_like_title(title):
            continue

        # 先取块级日期；无年份则允许用块内月/日兜底
        list_dt = parse_date(block_text)
        seen_links.add(chosen_link)
        candidates.append({
            "title": title,
            "link": chosen_link,
            "list_date": list_dt,
            "row_text": block_text,
        })

    if candidates:
        return candidates

    for a in soup.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        full = normalize_link(urljoin(BASE_URL, href))
        path = urlparse(full).path
        if not any(path.startswith(prefix) and path.rstrip("/") != prefix.rstrip("/") for prefix in prefixes):
            continue
        if full in seen_links:
            continue
        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        if _is_archive_like_title(title):
            continue
        parent = a.find_parent(["article", "li", "div", "section"]) or a.parent
        row_text = clean_text(parent.get_text(" ", strip=True)) if parent else title
        list_dt = parse_date(row_text)
        seen_links.add(full)
        candidates.append({
            "title": title,
            "link": full,
            "list_date": list_dt,
            "row_text": row_text,
        })

    return candidates


def _extract_legislation_blocks(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    seen = set()

    for block in _candidate_blocks(soup, ["article", "li", "div", "section", "tr"]):
        text = clean_text(block.get_text(" ", strip=True))
        if "Title:" not in text or "Latest Action:" not in text:
            continue

        date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        title_match = re.search(r"Title:\s*(.+?)(?:\s+Sponsored by:|\s+Latest Action:|\s+Details:|\s+PDF\b)", text)
        sponsor_match = re.search(r"Sponsored by:\s*(.+?)(?:\s+Latest Action:|\s+Details:|\s+PDF\b)", text)
        action_match = re.search(r"Latest Action:\s*(.+?)(?:\s+Details:|\s+PDF\b|$)", text)

        if not date_match or not title_match:
            continue

        title = clean_text(title_match.group(1))
        if not title or title.lower() in BAD_TITLES:
            continue

        detail_link = ""
        pdf_link = ""
        for a in block.find_all("a", href=True):
            full = normalize_link(urljoin(BASE_URL, a.get("href", "")))
            parsed = urlparse(full)
            if parsed.netloc.lower() == urlparse(BASE_URL).netloc.lower():
                path = parsed.path.rstrip("/")
                if path.startswith("/legislation/") and path not in {"/legislation", "/legislation/nominations"}:
                    detail_link = full
                    break
            elif "congress.gov" in parsed.netloc.lower():
                pdf_link = full

        summary_parts = []
        if sponsor_match:
            summary_parts.append(f"Sponsored by: {clean_text(sponsor_match.group(1))}")
        if action_match:
            summary_parts.append(f"Latest Action: {clean_text(action_match.group(1))}")
        summary = clean_text(" ".join(summary_parts))[:200]

        key = (date_match.group(1), title.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "link": detail_link or pdf_link or BASE_URL + "/legislation/",
            "list_date": parse_date(date_match.group(1)),
            "row_text": text,
            "summary": summary,
        })
    return items


def _extract_nomination_blocks(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    seen = set()

    for block in _candidate_blocks(soup, ["article", "li", "div", "section", "tr"]):
        text = clean_text(block.get_text(" ", strip=True))
        if "Description:" not in text or "Latest Action:" not in text:
            continue

        date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        desc_match = re.search(r"Description:\s*(.+?)(?:\s+Latest Action:|$)", text)
        action_match = re.search(r"Latest Action:\s*(.+?)(?:\s+Description:|$)", text)
        if not date_match or not desc_match:
            continue

        title = clean_text(desc_match.group(1))
        summary = ""
        if action_match:
            summary = clean_text(f"Latest Action: {action_match.group(1)}")[:200]

        link = ""
        for a in block.find_all("a", href=True):
            full = normalize_link(urljoin(BASE_URL, a.get("href", "")))
            path = urlparse(full).path.rstrip("/")
            if path.startswith("/legislation/nominations/") and path != "/legislation/nominations":
                link = full
                break

        key = (date_match.group(1), title.lower())
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "title": title,
            "link": link or BASE_URL + "/legislation/nominations/",
            "list_date": parse_date(date_match.group(1)),
            "row_text": text,
            "summary": summary,
        })
    return items


def collect_detail_links(soup: BeautifulSoup, section: dict) -> list[dict]:
    section_type = section["type"]

    if section_type == "hearings":
        return _collect_hearing_candidates(soup)
    if section_type == "news":
        return _collect_news_candidates(soup, section.get("news_prefixes", []))
    if section_type == "legislation":
        return _extract_legislation_blocks(soup)
    if section_type == "nominations":
        return _extract_nomination_blocks(soup)
    return []


def scrape_section(section: dict, existing_links: Optional[set[str]] = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if clean_text(x)}
    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    key = section["key"]
    category_en = section["category_en"]
    category = section["category"]
    party = section.get("party", "")
    list_url = section["list_url"]
    paged_mode = section.get("paged_mode", "page")
    section_type = section["type"]

    print(f"\n====== {category_en} ======")

    page = 1
    no_new_valid_page_count = 0
    consecutive_skip_count = 0
    seen_links = set()
    items: list[dict] = []

    while page <= MAX_PAGES:
        paged_url = make_paged_url(list_url, page, paged_mode)

        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        candidates = collect_detail_links(soup, section)
        if not candidates:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(candidates)} | {paged_url}")

        found_new_on_page = False

        for candidate in candidates:
            detail_link = normalize_link(candidate.get("link", ""))
            title_from_list = clean_text(candidate.get("title", ""))
            list_dt = candidate.get("list_date")
            row_text = clean_text(candidate.get("row_text", ""))
            preset_summary = clean_text(candidate.get("summary", ""))

            if detail_link in seen_links:
                continue
            if detail_link:
                seen_links.add(detail_link)

            if detail_link and detail_link in existing_links:
                print(f"跳过(已存在): {detail_link}")
                continue

            detail_soup = None
            article_dt = list_dt
            title = title_from_list
            summary = preset_summary

            # Hearings / News：优先列表日期，拿不到时再进详情页兜底
            if section_type in {"hearings", "news"} and not article_dt:
                try:
                    detail_soup = fetch(detail_link)
                    article_dt = extract_date_from_soup(detail_soup)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {detail_link} | {e}")
                    continue

            # Legislation / Nominations：优先块级解析；若能进详情页则补标题/摘要
            if section_type in {"legislation", "nominations"} and detail_link.startswith(BASE_URL):
                try:
                    detail_soup = fetch(detail_link)
                except Exception:
                    detail_soup = None

            if not detail_soup and detail_link and section_type not in {"nominations"}:
                try:
                    detail_soup = fetch(detail_link)
                except Exception:
                    detail_soup = None

            if detail_soup:
                if not title:
                    title = extract_title(detail_soup)
                if not article_dt:
                    article_dt = extract_date_from_soup(detail_soup)
                if not summary:
                    summary = extract_summary(detail_soup, limit=200)

            if not article_dt:
                if section_type == "news":
                    print(f"跳过(列表页无日期且详情页无日期): {title or detail_link}")
                elif section_type == "hearings":
                    print(f"跳过(列表页无日期): {title or detail_link}")
                else:
                    print(f"跳过(无日期): {title or detail_link}")
                continue

            if not title:
                print(f"跳过(无标题): {detail_link or row_text[:80]}")
                continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            if not summary and detail_soup:
                summary = extract_summary(detail_soup, limit=200)
            summary = clean_text(summary)[:200]

            items.append(
                make_item(
                    category_en=category_en,
                    category=category,
                    title=title,
                    summary=summary,
                    article_dt=article_dt,
                    link=detail_link or paged_url,
                    party=party,
                )
            )
            print(f"+ {title}")
            time.sleep(0.2)

        if not found_new_on_page:
            no_new_valid_page_count += 1
            print(f"[{key}] 第 {page} 页没有新增有效数据")
        else:
            no_new_valid_page_count = 0

        if no_new_valid_page_count >= 5:
            print(f"[{key}] 连续5页没有新增有效数据，停止当前分类")
            break

        page += 1

    return items


def run_committee(existing_links: Optional[set[str]] = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if clean_text(x)}
    all_items: list[dict] = []

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
