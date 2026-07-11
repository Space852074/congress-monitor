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
NO_NEW_PAGE_LIMIT = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Health, Education, Labor and Pensions Committee"
COMMITTEE_ZH = "美国参议院卫生、教育、劳工和养老金委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.help.senate.gov"

BAD_TITLES = {
    "",
    "press",
    "latest press",
    "all press",
    "hearings",
    "hearing",
    "calendar",
    "committee activity",
    "committee actions",
    "legislation",
    "nominations",
    "about",
    "members",
    "subcommittees",
    "issues",
    "rules of procedure",
    "accessibility",
    "filter",
    "filter results",
    "search",
    "update",
    "previous",
    "next",
    "print",
    "email",
    "share",
    "tweet",
    "home",
    "title",
    "bill",
    "last action",
    "check status",
    "date",
    "time",
    "location",
    "type",
    "open in new window",
    "download testimony",
}

SECTIONS = [
    {
        "key": "chair_news",
        "mode": "news",
        "category_en": "Republican News",
        "category": "共和党新闻",
        "party": "共和党",
        "list_url": "https://www.help.senate.gov/chair/newsroom",
        "detail_prefixes": [
            "/rep/newsroom/press/",
            "/chair/newsroom/press/",
        ],
        "stop_on_no_new_pages": True,
    },
    {
        "key": "ranking_news",
        "mode": "news",
        "category_en": "Democratic News",
        "category": "民主党新闻",
        "party": "民主党",
        "list_url": "https://www.help.senate.gov/ranking/newsroom",
        "detail_prefixes": [
            "/dem/newsroom/press/",
            "/ranking/newsroom/press/",
        ],
        "stop_on_no_new_pages": True,
    },
    {
        "key": "hearings",
        "mode": "hearings",
        "category_en": "Hearing",
        "category": "听证会",
        "party": "",
        "list_url": "https://www.help.senate.gov/hearings",
        "detail_prefixes": [
            "/hearings/",
        ],
        "stop_on_no_new_pages": True,
    },
    {
        "key": "legislation",
        "mode": "legislation",
        "category_en": "Legislation",
        "category": "立法",
        "party": "",
        "list_url": "https://www.help.senate.gov/committee-actions/legislation",
        "stop_on_no_new_pages": False,
    },
    {
        "key": "nominations",
        "mode": "nominations",
        "category_en": "Nomination",
        "category": "提名",
        "party": "",
        "list_url": "https://www.help.senate.gov/committee-actions/nominations",
        "stop_on_no_new_pages": False,
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

    text = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.I)

    direct_patterns = [
        "%m.%d.%Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
        "%A, %b %d, %Y",
        "%B %d %Y",
        "%b %d %Y",
    ]

    for fmt in direct_patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    patterns = [
        r"Published:\s*(\d{2}\.\d{2}\.\d{4})",
        r"Date:\s*(\d{2}/\d{2}/\d{2,4})",
        r"Last Action:?\s*(\d{2}/\d{2}/\d{4})",
        r"Received Date:\s*(\d{2}/\d{2}/\d{4})",
        r"\b(\d{2}\.\d{2}\.\d{4})\b",
        r"\b(\d{2}/\d{2}/\d{2,4})\b",
        r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b",
        r"\b([A-Z][a-z]{2} \d{1,2}, \d{4})\b",
        r"\b([A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}, \d{4})\b",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        candidate = m.group(1)
        for fmt in (
            "%m.%d.%Y",
            "%m/%d/%Y",
            "%m/%d/%y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%A, %B %d, %Y",
            "%A, %b %d, %Y",
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
        ".page-title",
        ".entry-title",
        ".content-title",
        ".post-title",
        "title",
    ]

    for selector in selectors:
        nodes = soup.select(selector)
        for node in nodes:
            txt = clean_text(node.get_text(" ", strip=True))
            if selector == "title":
                txt = txt.split("|")[0].strip()
            if txt and txt.lower() not in BAD_TITLES and len(txt) >= 6:
                return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if (
            re.search(r"Published:\s*\d{2}\.\d{2}\.\d{4}", txt)
            or re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", txt)
            or re.search(r"\b\d{2}/\d{2}/\d{2,4}\b", txt)
            or re.search(r"Date:\s*[A-Z][a-z]+day,\s*[A-Z][a-z]+\s+\d{1,2}(st|nd|rd|th)?,\s*\d{4}", txt, re.I)
            or re.search(r"Date:\s*[A-Z][a-z]+\s+\d{1,2}(st|nd|rd|th)?,\s*\d{4}", txt, re.I)
            or re.search(r"Date:\s*\d{2}/\d{2}/\d{2,4}", txt, re.I)
        ):
            candidates.append(txt)

    for txt in candidates:
        dt = parse_date(txt)
        if dt:
            return dt

    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    paragraphs = []

    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        ".post-content p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        for p in soup.find_all("p"):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                paragraphs.append(txt)

    if not paragraphs:
        return ""

    summary = " ".join(paragraphs[:3]).strip()
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def make_paged_url(list_url: str, page: int) -> str:
    if page == 1:
        return list_url
    sep = "&" if "?" in list_url else "?"
    return f"{list_url}{sep}page={page}"


def _is_bad_title(text: str) -> bool:
    text = clean_text(text)
    if not text:
        return True
    if text.lower() in BAD_TITLES:
        return True
    if len(text) < 5:
        return True
    return False


def _nearest_block(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", "") in {"article", "li", "div", "section", "tr"}:
            parent_text = clean_text(parent.get_text(" ", strip=True))
            if parent_text:
                return parent
    return anchor.parent


def _looks_like_detail_path(path: str, detail_prefixes: list[str]) -> bool:
    path = (path or "").rstrip("/")

    blocked = {
        "/chair/newsroom",
        "/ranking/newsroom",
        "/hearings",
        "/committee-actions/legislation",
        "/committee-actions/nominations",
        "/chair",
        "/ranking",
        "/about",
        "/members",
        "/subcommittees",
        "/issues",
    }

    if path in blocked:
        return False

    for prefix in detail_prefixes or []:
        prefix = prefix.rstrip("/")
        if path.startswith(prefix) and path != prefix:
            return True

    return False


def _truncate_summary(text: str, limit: int = 200) -> str:
    text = clean_text(text)
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


def _extract_inline_summary(block_text: str, title: str, limit: int = 200) -> str:
    text = clean_text(block_text)
    if not text:
        return ""

    if title and title in text:
        text = text.replace(title, "", 1).strip()

    text = re.sub(r"^Published:\s*\d{2}\.\d{2}\.\d{4}", "", text).strip()
    text = re.sub(r"^\d{2}\.\d{2}\.\d{4}", "", text).strip()
    text = re.sub(r"^Date:\s*\d{2}/\d{2}/\d{2,4}", "", text).strip()
    text = re.sub(r"^Time:\s*\d{1,2}:\d{2}\s*[ap]m", "", text, flags=re.I).strip()
    text = re.sub(r"\s+", " ", text).strip()

    return _truncate_summary(text, limit=limit)


def _parse_hearing_list_datetime(block_text: str):
    block_text = clean_text(block_text)
    if not block_text:
        return None

    date_m = re.search(r"Date:\s*(\d{2}/\d{2}/\d{2,4})", block_text, re.I)
    time_m = re.search(r"Time:\s*([0-9:]+\s*[ap]m)", block_text, re.I)

    if not date_m:
        return None

    date_part = date_m.group(1)

    base_dt = None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            base_dt = datetime.strptime(date_part, fmt)
            break
        except Exception:
            pass

    if not base_dt:
        return None

    if time_m:
        time_part = time_m.group(1).replace(" ", "").upper()
        for tfmt in ("%I:%M%p",):
            try:
                t = datetime.strptime(time_part, tfmt)
                base_dt = base_dt.replace(
                    hour=t.hour,
                    minute=t.minute,
                    second=0,
                    microsecond=0,
                )
                break
            except Exception:
                pass

    return base_dt


def collect_detail_links(list_url: str, section: dict) -> list[dict]:
    soup = fetch(list_url)
    mode = section["mode"]
    rows = []
    seen = set()

    if mode == "news":
        detail_prefixes = section.get("detail_prefixes", [])

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(BASE_URL, href)
            parsed = urlparse(full_url)
            host = parsed.netloc.lower().replace("www.", "")
            path = parsed.path or ""

            if host != urlparse(BASE_URL).netloc.lower().replace("www.", ""):
                continue
            if not _looks_like_detail_path(path, detail_prefixes):
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if _is_bad_title(title):
                continue

            block = _nearest_block(a)
            block_text = clean_text(block.get_text(" ", strip=True)) if block else title
            list_dt = parse_date(block_text)
            summary = _extract_inline_summary(block_text, title, limit=200)

            norm = normalize_link(full_url)
            if norm in seen:
                continue
            seen.add(norm)

            rows.append(
                {
                    "title": title,
                    "link": norm,
                    "list_date": list_dt,
                    "summary": summary,
                    "raw_text": block_text,
                }
            )

        return rows

    if mode == "hearings":
        detail_prefixes = section.get("detail_prefixes", [])

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue

            full_url = urljoin(BASE_URL, href)
            parsed = urlparse(full_url)
            host = parsed.netloc.lower().replace("www.", "")
            path = parsed.path or ""

            if host != urlparse(BASE_URL).netloc.lower().replace("www.", ""):
                continue
            if not _looks_like_detail_path(path, detail_prefixes):
                continue

            title = clean_text(a.get_text(" ", strip=True))
            if _is_bad_title(title):
                continue

            row = a.find_parent("tr")
            if row:
                block_text = clean_text(row.get_text(" ", strip=True))
            else:
                block = _nearest_block(a)
                block_text = clean_text(block.get_text(" ", strip=True)) if block else title

            list_dt = _parse_hearing_list_datetime(block_text)
            summary = _extract_inline_summary(block_text, title, limit=200)

            norm = normalize_link(full_url)
            if norm in seen:
                continue
            seen.add(norm)

            rows.append(
                {
                    "title": title,
                    "link": norm,
                    "list_date": list_dt,
                    "summary": summary,
                    "raw_text": block_text,
                }
            )

        return rows

    if mode == "legislation":
        blocks = soup.find_all(["article", "li", "div", "section", "tr"])
        for block in blocks:
            block_text = clean_text(block.get_text(" ", strip=True))
            if "Bill" not in block_text or "Last Action" not in block_text or "Title" not in block_text:
                continue

            dt = parse_date(block_text)
            if not dt:
                continue

            link = ""
            title = ""

            for a in block.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if href and "congress.gov" in href.lower():
                    link = normalize_link(href)
                    title = clean_text(a.get_text(" ", strip=True))
                    break

            if not link or _is_bad_title(title):
                continue
            if link in seen:
                continue
            seen.add(link)

            bill_m = re.search(r"Bill\s+([A-Z0-9\.\-]+)", block_text, re.I)
            last_action_m = re.search(r"Last Action\s+(\d{2}/\d{2}/\d{4})", block_text, re.I)

            parts = []
            if bill_m:
                parts.append(f"Bill: {bill_m.group(1)}")
            if last_action_m:
                parts.append(f"Last Action: {last_action_m.group(1)}")
            summary = _truncate_summary(" | ".join(parts), limit=200)

            rows.append(
                {
                    "title": title,
                    "link": link,
                    "list_date": dt,
                    "summary": summary,
                    "raw_text": block_text,
                }
            )

        return rows

    if mode == "nominations":
        for block in soup.find_all(["article", "li", "div", "section", "tr"]):
            block_text = clean_text(block.get_text(" ", strip=True))
            if "Nomination Number:" not in block_text:
                continue
            if "Check Status" not in block_text:
                continue

            dt = parse_date(block_text)
            if not dt:
                continue

            title_m = re.search(
                r"^\s*(\d{2}/\d{2}/\d{4})\s+(.*?)\s+Nomination Number:",
                block_text,
                re.S,
            )
            if not title_m:
                continue

            title = clean_text(title_m.group(2))
            if _is_bad_title(title):
                continue

            link = ""
            for a in block.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if href and "congress.gov" in href.lower():
                    link = normalize_link(href)
                    break

            if not link or link in seen:
                continue
            seen.add(link)

            nom_m = re.search(r"Nomination Number:\s*([A-Z0-9\-]+)", block_text, re.I)
            recv_m = re.search(r"Received Date:\s*(\d{2}/\d{2}/\d{4})", block_text, re.I)
            last_m = re.search(r"Last Action:\s*(.+?)(?:Check Status|$)", block_text, re.I)

            parts = []
            if nom_m:
                parts.append(f"Nomination Number: {nom_m.group(1)}")
            if recv_m:
                parts.append(f"Received Date: {recv_m.group(1)}")
            if last_m:
                parts.append(f"Last Action: {clean_text(last_m.group(1))}")

            summary = _truncate_summary(" | ".join(parts), limit=200)

            rows.append(
                {
                    "title": title,
                    "link": link,
                    "list_date": dt,
                    "summary": summary,
                    "raw_text": block_text,
                }
            )

        return rows

    return []


def build_item(
    *,
    category_en: str,
    category: str,
    party: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
) -> dict:
    summary = _truncate_summary(summary or "", limit=200)

    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": category_en,
        "category": category,
        "title": title,
        "summary": summary,
        "date": f"{article_dt.year}年{article_dt.month}月{article_dt.day}日",
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": party,
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []

    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            (item.get("sort_date", "") or "").strip(),
            (item.get("title", "") or "").strip().lower(),
            (item.get("category_en", "") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


def scrape_section(section: dict, existing_links=None) -> list[dict]:
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

    key = section["key"]
    mode = section["mode"]
    category_en = section["category_en"]
    category = section["category"]
    party = section["party"]
    list_url = section["list_url"]
    stop_on_no_new_pages = section.get("stop_on_no_new_pages", False)

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    items = []
    page = 1
    consecutive_skip_count = 0
    seen_links = set()
    consecutive_no_new_pages = 0

    print(f"\n====== {category_en} ======")

    while page <= MAX_PAGES:
        paged_url = make_paged_url(list_url, page)

        try:
            rows = collect_detail_links(paged_url, section)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not rows:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(rows)} | {paged_url}")

        found_new_on_page = False

        for row in rows:
            link = normalize_link(row.get("link", ""))
            title_from_list = clean_text(row.get("title", ""))
            list_dt = row.get("list_date")
            summary_from_list = clean_text(row.get("summary", ""))

            if not link or link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            if mode in {"legislation", "nominations"}:
                if list_dt:
                    if list_dt.date() < cutoff_date:
                        print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title_from_list}")
                        consecutive_skip_count += 1
                        if consecutive_skip_count >= SKIP_LIMIT:
                            print(f"连续跳过达到{SKIP_LIMIT}条，停止当前分类")
                            return items
                        continue
                else:
                    print(f"跳过(列表页无日期): {title_from_list}")
                    continue

            else:
                if list_dt and list_dt.date() < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title_from_list}")
                    consecutive_skip_count += 1
                    if consecutive_skip_count >= SKIP_LIMIT:
                        print(f"连续跳过达到{SKIP_LIMIT}条，停止当前分类")
                        return items
                    continue

            if mode in {"legislation", "nominations"}:
                consecutive_skip_count = 0
                found_new_on_page = True

                item = build_item(
                    category_en=category_en,
                    category=category,
                    party=party,
                    title=title_from_list,
                    summary=summary_from_list,
                    article_dt=list_dt,
                    link=link,
                )
                items.append(item)
                print(f"+ {title_from_list}")
                time.sleep(0.2)
                continue

            try:
                soup = fetch(link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {link} | {e}")
                continue

            detail_title = extract_title(soup) or title_from_list
            detail_dt = extract_date_from_soup(soup) or list_dt
            detail_summary = extract_summary(soup, limit=200) or summary_from_list

            if not detail_title or not detail_dt:
                print(f"跳过(无标题/日期): {link}")
                continue

            if detail_dt.date() < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {detail_title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print(f"连续跳过达到{SKIP_LIMIT}条，停止当前分类")
                    return items
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            item = build_item(
                category_en=category_en,
                category=category,
                party=party,
                title=detail_title,
                summary=detail_summary,
                article_dt=detail_dt,
                link=link,
            )
            items.append(item)
            print(f"+ {detail_title}")
            time.sleep(0.2)

        if not found_new_on_page:
            print(f"[{key}] 第 {page} 页没有新增有效数据")
            if stop_on_no_new_pages:
                consecutive_no_new_pages += 1
                if consecutive_no_new_pages >= 5:
                    print(f"[{key}] 连续5页没有新增有效数据，停止当前分类")
                    break
        else:
            consecutive_no_new_pages = 0

        page += 1

    return items


def run_committee(existing_links=None):
    existing_links = existing_links or set()

    all_items = []
    for section in SECTIONS:
        try:
            section_items = scrape_section(section, existing_links=existing_links)
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