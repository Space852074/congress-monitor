# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
NO_NEW_PAGE_LIMIT = 5
MAX_PAGES = 120
REQUEST_SLEEP = 0.2
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Judiciary Committee"
COMMITTEE_ZH = "美国参议院司法委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.judiciary.senate.gov"

BAD_TITLES = {
    "hearings",
    "hearing",
    "legislation",
    "committee documents",
    "library",
    "confirmed nominations",
    "majority press",
    "minority press",
    "press",
    "news",
    "search",
    "filter",
    "update",
    "calendar",
    "nominations",
    "title",
    "date",
    "bill",
    "last action",
    "check status",
    "next",
    "previous",
    "committee activity",
    "committee documents search",
    "all library types",
    "all congressional sessions",
    "business meeting results",
    "nominee questionnaires",
}

HEARINGS_URL = "https://www.judiciary.senate.gov/committee-activity/hearings"
LEGISLATION_URL = "https://www.judiciary.senate.gov/committee-activity/legislation"
LIBRARY_URL = "https://www.judiciary.senate.gov/committee-activity/library"
NOMINATIONS_URL = "https://www.judiciary.senate.gov/nominations/confirmed?keyword=confirmed"
PRESS_MAJORITY_URL = "https://www.judiciary.senate.gov/press/majority"
PRESS_MINORITY_URL = "https://www.judiciary.senate.gov/press/minority"


# -----------------------------
# 基础工具函数
# -----------------------------

def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    query = parsed.query or ""

    return urlunparse((scheme, netloc, path, "", query, ""))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def fetch(url: str, timeout: int = TIMEOUT, retries: int = 3) -> BeautifulSoup:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(1.2 * attempt)
            else:
                raise last_error


def parse_date(text: str):
    text = clean_text(text)
    if not text:
        return None

    text = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", text, flags=re.I)

    patterns = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m.%d.%Y",
        "%m.%d.%y",
        "%Y-%m-%d",
        "%m/%d/%Y at %I:%M%p",
        "%m/%d/%y at %I:%M%p",
        "%m/%d/%Y at %I:%M %p",
        "%m/%d/%y at %I:%M %p",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    regex_candidates = [
        r"(\d{1,2}/\d{1,2}/\d{2,4}\s+at\s+\d{1,2}:\d{2}\s*[ap]m)",
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
        r"(\d{1,2}\.\d{1,2}\.\d{2,4})",
    ]

    for pattern in regex_candidates:
        m = re.search(pattern, text, flags=re.I)
        if not m:
            continue
        candidate = clean_text(m.group(1))
        candidate = re.sub(r"(\d{1,2})(st|nd|rd|th)\b", r"\1", candidate, flags=re.I)

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
        ".content-header h1",
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
    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue
        dt = parse_date(txt)
        if dt:
            return dt
    return None


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        ".field--name-body p",
    ]

    paragraphs: list[str] = []
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

    summary = clean_text(" ".join(paragraphs[:3]))
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary


def is_recent(dt: datetime) -> bool:
    cutoff = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()
    return dt.date() >= cutoff


def build_item(
    *,
    category_en: str,
    category: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
    party: str = "",
) -> dict:
    summary = clean_text(summary or "")
    if len(summary) > 200:
        summary = summary[:200].rstrip() + "..."

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
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("sort_date", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def make_rs_page_url(url: str, page: int) -> str:
    if page <= 1:
        return url

    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["pagenum_rs"] = [str(page)]
    new_query = urlencode(query, doseq=True)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", new_query, ""))


def slugify(text: str) -> str:
    text = clean_text(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def find_anchor_by_text(soup: BeautifulSoup, title: str) -> str:
    title_norm = clean_text(title).lower()
    for a in soup.find_all("a", href=True):
        txt = clean_text(a.get_text(" ", strip=True)).lower()
        if txt == title_norm:
            return normalize_link(urljoin(BASE_URL, a.get("href", "")))
    return ""


def pn_link_from_text(soup: BeautifulSoup, pn: str) -> str:
    pn_norm = clean_text(pn).lower()
    for a in soup.find_all("a", href=True):
        txt = clean_text(a.get_text(" ", strip=True)).lower()
        if txt == pn_norm:
            return normalize_link(urljoin(BASE_URL, a.get("href", "")))
    return ""


def summarize_block_text(block_text: str, title: str, limit: int = 200) -> str:
    txt = clean_text(block_text)
    if not txt:
        return ""

    txt = re.sub(re.escape(title), "", txt, flags=re.I)
    txt = re.sub(r"^\d{2}[\./]\d{2}[\./]\d{2,4}\s*", "", txt)
    txt = clean_text(txt)

    if len(txt) > limit:
        txt = txt[:limit].rstrip() + "..."
    return txt


def extract_nearby_date_and_summary(soup: BeautifulSoup, title: str):
    """
    适配标题 + 补充文本 + 日期的连续流式结构
    """
    full_text = soup.get_text("\n", strip=True)
    full_text = re.sub(r"\n+", "\n", full_text)

    title_escaped = re.escape(clean_text(title))

    patterns = [
        rf"{title_escaped}\s+(?P<body>.*?)(?P<date>\d{{2}}/\d{{2}}/\d{{2,4}}\s+at\s+\d{{1,2}}:\d{{2}}[ap]m)",
        rf"{title_escaped}\s+(?P<body>.*?)(?P<date>\d{{2}}\.\d{{2}}\.\d{{2,4}})",
        rf"{title_escaped}\s+(?P<body>.*?)(?P<date>[A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{{1,2}},\s+\d{{4}})",
        rf"{title_escaped}\s+(?P<body>.*?)(?P<date>[A-Z][a-z]+\s+\d{{1,2}},\s+\d{{4}})",
    ]

    for pattern in patterns:
        m = re.search(pattern, full_text, flags=re.I | re.S)
        if not m:
            continue

        raw_body = clean_text(m.group("body"))
        raw_date = clean_text(m.group("date"))

        dt = parse_date(raw_date)
        if not dt:
            continue

        summary = raw_body
        if len(summary) > 200:
            summary = summary[:200].rstrip() + "..."

        return dt, summary

    return None, ""


# -----------------------------
# 通用 section 外壳（给 hearings / press 用）
# -----------------------------

def collect_detail_links(list_url: str, mode: str = "generic") -> list[dict]:
    soup = fetch(list_url)

    if mode == "hearings":
        return collect_hearing_candidates(soup)
    if mode == "press_majority":
        return collect_press_candidates(soup, party_slug="rep")
    if mode == "press_minority":
        return collect_press_candidates(soup, party_slug="dem")

    return []


def scrape_section(
    *,
    key: str,
    list_url: str,
    category_en: str,
    category: str,
    party: str = "",
    mode: str = "generic",
    existing_links: set[str] | None = None,
) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    items: list[dict] = []
    seen_links: set[str] = set()
    consecutive_skip_count = 0
    no_new_pages = 0

    print(f"\n====== {category_en} ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = make_rs_page_url(list_url, page)

        try:
            candidates = collect_detail_links(paged_url, mode=mode)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not candidates:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(candidates)} | {paged_url}")

        found_new_on_page = False

        for candidate in candidates:
            link = normalize_link(candidate.get("link", ""))
            title = clean_text(candidate.get("title", ""))
            list_dt = candidate.get("date")

            if not link or link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            detail_soup = None
            article_dt = list_dt
            summary = clean_text(candidate.get("summary", ""))

            if not article_dt:
                try:
                    detail_soup = fetch(link)
                    article_dt = extract_date_from_soup(detail_soup)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {link} | {e}")
                    continue

            if not title:
                try:
                    if detail_soup is None:
                        detail_soup = fetch(link)
                    title = extract_title(detail_soup)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {link} | {e}")
                    continue

            if not article_dt:
                print(f"跳过(列表页无日期): {title or link}")
                continue

            if not is_recent(article_dt):
                print(f"跳过(超出最近10天): {title or link}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            if detail_soup is None:
                try:
                    detail_soup = fetch(link)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {link} | {e}")
                    continue

            if not title:
                title = extract_title(detail_soup)
            if not title:
                print(f"跳过(无标题): {link}")
                continue

            if not summary:
                summary = extract_summary(detail_soup, limit=200)

            consecutive_skip_count = 0
            found_new_on_page = True

            items.append(
                build_item(
                    category_en=category_en,
                    category=category,
                    title=title,
                    summary=summary,
                    article_dt=article_dt,
                    link=link,
                    party=party,
                )
            )
            print(f"+ {title}")
            time.sleep(REQUEST_SLEEP)

        if not found_new_on_page:
            no_new_pages += 1
            print(f"[{key}] 第 {page} 页没有新增有效数据")
            if no_new_pages >= NO_NEW_PAGE_LIMIT:
                print(f"[{key}] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            no_new_pages = 0

    return items


# -----------------------------
# Hearings
# -----------------------------

def collect_hearing_candidates(soup: BeautifulSoup) -> list[dict]:
    results: list[dict] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)
        path = (parsed.path or "").rstrip("/")

        if parsed.netloc.lower().replace("www.", "") != "judiciary.senate.gov":
            continue
        if not path.startswith("/committee-activity/hearings/"):
            continue
        if path == "/committee-activity/hearings":
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        norm = normalize_link(full_url)
        if norm in seen:
            continue
        seen.add(norm)

        dt, summary = extract_nearby_date_and_summary(soup, title)

        results.append({
            "link": norm,
            "title": title,
            "date": dt,
            "summary": summary,
        })

    return results


# -----------------------------
# Press Majority / Minority
# -----------------------------

def collect_press_candidates(soup: BeautifulSoup, party_slug: str) -> list[dict]:
    results: list[dict] = []
    seen = set()
    prefix = f"/press/{party_slug}/releases/"

    for a in soup.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)
        path = (parsed.path or "").rstrip("/")

        if parsed.netloc.lower().replace("www.", "") != "judiciary.senate.gov":
            continue
        if not path.startswith(prefix.rstrip("/")):
            continue
        if path in {f"/press/{party_slug}", f"/press/{party_slug}/releases"}:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        norm = normalize_link(full_url)
        if norm in seen:
            continue
        seen.add(norm)

        dt, summary = extract_nearby_date_and_summary(soup, title)

        results.append({
            "link": norm,
            "title": title,
            "date": dt,
            "summary": summary,
        })

    return results


# -----------------------------
# Legislation
# -----------------------------

def scrape_legislation(existing_links: set[str] | None = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    items: list[dict] = []
    seen_keys = set()
    consecutive_skip_count = 0

    print("\n====== Legislation ======")

    try:
        soup = fetch(LEGISLATION_URL)
    except Exception as e:
        print(f"[legislation] 抓取失败: {LEGISLATION_URL} | {e}")
        return []

    rows = parse_legislation_rows(soup)
    if not rows:
        print("[legislation] 第 1 页无候选链接，停止当前分类")
        return []

    print(f"[legislation] 第 1 页候选链接: {len(rows)} | {LEGISLATION_URL}")

    for row in rows:
        title = row["title"]
        link = normalize_link(row["link"])
        dt = row["date"]
        summary = row["summary"]

        row_key = (link, clean_text(title).lower(), dt.strftime("%Y-%m-%d") if dt else "")
        if row_key in seen_keys:
            continue
        seen_keys.add(row_key)

        if link in existing_links:
            print(f"跳过(已存在): {link}")
            continue

        if not dt:
            print(f"跳过(列表页无日期): {title}")
            continue

        if not is_recent(dt):
            print(f"跳过(超出最近10天): {title}")
            consecutive_skip_count += 1
            if consecutive_skip_count >= SKIP_LIMIT:
                print("连续跳过达到5条，停止当前分类")
                break
            continue

        consecutive_skip_count = 0
        items.append(
            build_item(
                category_en="Legislation",
                category="立法",
                title=title,
                summary=summary,
                article_dt=dt,
                link=link,
            )
        )
        print(f"+ {title}")

    return items


def _clean_legislation_title(title: str) -> str:
    """
    Senate Judiciary legislation page sometimes exposes the whole page text in one block.
    This trims pagination/footer/menu pollution after the real bill title.
    """
    title = clean_text(title)

    # Hard stop markers seen in polluted output.
    stop_patterns = [
        r"\bShowing\s+page\s+\d+\b",
        r"\bNext\s+About\b",
        r"\bAbout\s+Latest\s+News\b",
        r"\bCommittee\s+Activity\s+Privacy\s+Policy\b",
        r"\b224\s+Dirksen\s+Senate\s+Office\s+Building\b",
        r"\bsite-search\b",
        r"\bSite\s+Search\b",
    ]
    for pat in stop_patterns:
        title = re.split(pat, title, maxsplit=1, flags=re.I)[0].strip()

    # Remove trailing table labels if the regex captured too far.
    title = re.sub(r"\s+(Last\s+Action|Bill|Title)\s*$", "", title, flags=re.I).strip()
    return clean_text(title)


def _is_bad_legislation_title(title: str) -> bool:
    title = clean_text(title)
    title_l = title.lower()
    if not title or title_l in BAD_TITLES:
        return True
    if len(title) < 3:
        return True
    # Reject obvious navigation/pagination garbage.
    if re.fullmatch(r"(?:\d+\s*)+", title):
        return True
    if "showing page" in title_l or "privacy policy" in title_l or "site search" in title_l:
        return True
    return False


def _legislation_link_from_container(container: Tag, fallback_title: str) -> str:
    """Prefer a congress.gov link inside the same record block."""
    for a in container.find_all("a", href=True):
        href = clean_text(a.get("href", ""))
        if "congress.gov" in href.lower():
            return normalize_link(href)

    # Fallback to exact visible title match.
    anchor = find_anchor_by_text(container, fallback_title)
    if anchor:
        return anchor

    return f"{LEGISLATION_URL}#legislation-{slugify(fallback_title)}"


def parse_legislation_rows(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    seen = set()

    # First pass: parse bounded record containers instead of the entire page text.
    for container in soup.find_all(["article", "li", "tr", "div", "section"]):
        block = clean_text(container.get_text(" ", strip=True))
        if not block:
            continue
        if not re.search(r"\bLast\s+Action\s+\d{2}/\d{2}/\d{4}\b", block, flags=re.I):
            continue
        if not re.search(r"\bTitle\b", block, flags=re.I):
            continue

        # Avoid parsing the full-page wrapper that contains pagination/footer/navigation.
        if len(block) > 2500 or block.count("Last Action") > 3:
            continue

        date_match = re.search(r"Last\s+Action\s+(\d{2}/\d{2}/\d{4})", block, flags=re.I)
        title_match = re.search(
            r"Title\s+(.+?)(?:\s+Bill\s+[A-Za-z]|\s+Last\s+Action|$)",
            block,
            flags=re.I,
        )
        bill_match = re.search(r"Bill\s+([A-Za-z0-9\.\-]+)", block, flags=re.I)

        if not date_match or not title_match:
            continue

        dt = parse_date(date_match.group(1))
        title = _clean_legislation_title(title_match.group(1))
        if _is_bad_legislation_title(title):
            continue

        bill = clean_text(bill_match.group(1)) if bill_match else ""
        link = _legislation_link_from_container(container, title)
        summary = f"{bill} | Last Action {date_match.group(1)}" if bill else f"Last Action {date_match.group(1)}"

        key = (title.lower(), date_match.group(1), link)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title,
            "link": link,
            "date": dt,
            "summary": summary[:200],
        })

    if rows:
        return rows

    # Fallback: old full-text parser, but with strict cleanup and pollution stops.
    text = soup.get_text("\n", strip=True)
    blocks = re.split(r"(?=Last\s+Action\s+\d{2}/\d{2}/\d{4})", text)

    for block in blocks:
        block = clean_text(block)
        if not block.startswith("Last Action"):
            continue

        date_match = re.search(r"Last\s+Action\s+(\d{2}/\d{2}/\d{4})", block, flags=re.I)
        title_match = re.search(r"Title\s+(.+?)(?:\s+Bill\s+[A-Za-z]|\s+Last\s+Action|$)", block, flags=re.I)
        bill_match = re.search(r"Bill\s+([A-Za-z0-9\.\-]+)", block, flags=re.I)

        if not date_match or not title_match:
            continue

        dt = parse_date(date_match.group(1))
        title = _clean_legislation_title(title_match.group(1))
        bill = clean_text(bill_match.group(1)) if bill_match else ""
        if _is_bad_legislation_title(title):
            continue

        anchor = find_anchor_by_text(soup, title)
        link = anchor if anchor else f"{LEGISLATION_URL}#legislation-{slugify(title)}"
        summary = f"{bill} | Last Action {date_match.group(1)}" if bill else f"Last Action {date_match.group(1)}"

        key = (title.lower(), date_match.group(1), link)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title,
            "link": link,
            "date": dt,
            "summary": summary[:200],
        })

    return rows


# -----------------------------
# Library
# -----------------------------

def scrape_library(existing_links: set[str] | None = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    items: list[dict] = []
    seen_links: set[str] = set()
    consecutive_skip_count = 0
    no_new_pages = 0

    print("\n====== Library ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = make_rs_page_url(LIBRARY_URL, page)

        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[library] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        rows = parse_library_rows(soup)
        if not rows:
            print(f"[library] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[library] 第 {page} 页候选链接: {len(rows)} | {paged_url}")

        found_new_on_page = False

        for row in rows:
            title = row["title"]
            dt = row["date"]
            link = normalize_link(row["link"])

            if not link or link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            if not dt:
                print(f"跳过(列表页无日期): {title}")
                continue

            if not is_recent(dt):
                print(f"跳过(超出最近10天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            items.append(
                build_item(
                    category_en="Library",
                    category="资料库",
                    title=title,
                    summary=row["summary"],
                    article_dt=dt,
                    link=link,
                )
            )
            print(f"+ {title}")

        if not found_new_on_page:
            no_new_pages += 1
            print(f"[library] 第 {page} 页没有新增有效数据")
            if no_new_pages >= NO_NEW_PAGE_LIMIT:
                print("[library] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            no_new_pages = 0

    return items


def parse_library_rows(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    seen = set()

    # 主逻辑：按“整行记录块”解析
    for container in soup.find_all(["div", "li", "tr", "article", "section"]):
        text = clean_text(container.get_text(" ", strip=True))
        if not text:
            continue

        date_match = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", text)
        if not date_match:
            continue

        dt = parse_date(date_match.group(1))
        if not dt:
            continue

        a = container.find("a", href=True)
        if not a:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        href = clean_text(a.get("href", ""))
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "judiciary.senate.gov":
            continue

        if not (
            parsed.path.startswith("/download/")
            or parsed.path.startswith("/committee-activity/library/")
        ):
            continue

        doc_type = extract_library_type(text)
        summary = f"{doc_type} | {date_match.group(1)}" if doc_type else date_match.group(1)

        norm = normalize_link(full_url)
        key = (norm, title.lower(), dt.strftime("%Y-%m-%d"))
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title,
            "link": norm,
            "date": dt,
            "summary": summary[:200],
        })

    if rows:
        return rows

    # 兜底逻辑：从 a 标签往上爬，直到拿到包含日期的整块文本
    for a in soup.find_all("a", href=True):
        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        href = clean_text(a.get("href", ""))
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)
        parsed = urlparse(full_url)

        if parsed.netloc.lower().replace("www.", "") != "judiciary.senate.gov":
            continue

        if not (
            parsed.path.startswith("/download/")
            or parsed.path.startswith("/committee-activity/library/")
        ):
            continue

        node = a
        block_text = ""
        dt = None

        for _ in range(8):
            if node is None:
                break
            if isinstance(node, Tag):
                block_text = clean_text(node.get_text(" ", strip=True))
                dt = parse_date(block_text)
                if dt:
                    break
            node = node.parent

        if not dt:
            continue

        doc_type = extract_library_type(block_text)
        summary = f"{doc_type} | {dt.strftime('%m/%d/%Y')}" if doc_type else dt.strftime("%m/%d/%Y")

        norm = normalize_link(full_url)
        key = (norm, title.lower(), dt.strftime("%Y-%m-%d"))
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title,
            "link": norm,
            "date": dt,
            "summary": summary[:200],
        })

    return rows


def extract_library_type(block_text: str) -> str:
    options = [
        "Hearing",
        "Business Meeting Results",
        "Nominee Questionnaires",
        "Committee Questionnaire",
        "Committee Report",
        "Legislation",
        "Letters",
        "Member's Statement",
        "Opening Remarks",
        "Questions for the Record",
        "Testimony",
        "Official Correspondence",
    ]
    for option in options:
        if re.search(rf"\b{re.escape(option)}\b", block_text, flags=re.I):
            return option
    return ""


# -----------------------------
# Nominations
# -----------------------------

def scrape_nominations(existing_links: set[str] | None = None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    items: list[dict] = []
    seen_links: set[str] = set()
    consecutive_skip_count = 0
    no_new_pages = 0

    print("\n====== Nomination ======")

    for page in range(1, MAX_PAGES + 1):
        paged_url = make_rs_page_url(NOMINATIONS_URL, page)

        try:
            soup = fetch(paged_url)
        except Exception as e:
            print(f"[nominations] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        rows = parse_nomination_rows(soup)
        if not rows:
            print(f"[nominations] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[nominations] 第 {page} 页候选链接: {len(rows)} | {paged_url}")

        found_new_on_page = False

        for row in rows:
            title = row["title"]
            dt = row["date"]
            link = normalize_link(row["link"])
            summary = row["summary"]

            if not link or link in seen_links:
                continue
            seen_links.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            if not dt:
                print(f"跳过(列表页无日期): {title}")
                continue

            if not is_recent(dt):
                print(f"跳过(超出最近10天): {title}")
                consecutive_skip_count += 1
                if consecutive_skip_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            consecutive_skip_count = 0
            found_new_on_page = True

            items.append(
                build_item(
                    category_en="Nomination",
                    category="提名",
                    title=title,
                    summary=summary,
                    article_dt=dt,
                    link=link,
                )
            )
            print(f"+ {title}")

        if not found_new_on_page:
            no_new_pages += 1
            print(f"[nominations] 第 {page} 页没有新增有效数据")
            if no_new_pages >= NO_NEW_PAGE_LIMIT:
                print("[nominations] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            no_new_pages = 0

    return items


def parse_nomination_rows(soup: BeautifulSoup) -> list[dict]:
    rows: list[dict] = []
    text = soup.get_text("\n", strip=True)
    blocks = re.split(r"(?=\d{2}/\d{2}/\d{4}\s+)", text)
    seen = set()

    for block in blocks:
        block = clean_text(block)
        if not re.match(r"^\d{2}/\d{2}/\d{4}\s+", block):
            continue
        if "Nomination Number:" not in block:
            continue

        dt_match = re.match(r"^(\d{2}/\d{2}/\d{4})", block)
        title_match = re.search(r"^\d{2}/\d{2}/\d{4}\s+(.+?)\s+Nomination Number:", block)
        pn_match = re.search(r"Nomination Number:\s*(PN[0-9\-]+(?:-[0-9]+)?)", block, flags=re.I)
        last_action_match = re.search(r"Last Action:\s*(.+?)\s*(?:Check Status|$)", block, flags=re.I)

        if not dt_match or not title_match:
            continue

        dt = parse_date(dt_match.group(1))
        title = clean_text(title_match.group(1))
        pn = clean_text(pn_match.group(1)) if pn_match else ""
        last_action = clean_text(last_action_match.group(1)) if last_action_match else ""
        if not title:
            continue

        link = pn_link_from_text(soup, pn) if pn else ""
        if not link:
            link = f"{NOMINATIONS_URL}#nomination-{slugify(title)}"

        summary_parts = []
        if pn:
            summary_parts.append(pn)
        if last_action:
            summary_parts.append(last_action)
        summary = " | ".join(summary_parts)[:200]

        key = (title.lower(), dt.strftime("%Y-%m-%d") if dt else "", link)
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "title": title,
            "date": dt,
            "link": link,
            "summary": summary,
        })

    return rows


# -----------------------------
# 运行入口
# -----------------------------

def run_committee(existing_links=None):
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}

    all_items: list[dict] = []

    all_items.extend(
        scrape_section(
            key="hearings",
            list_url=HEARINGS_URL,
            category_en="Hearing",
            category="听证会",
            mode="hearings",
            existing_links=existing_links,
        )
    )

    all_items.extend(scrape_legislation(existing_links))
    all_items.extend(scrape_library(existing_links))
    all_items.extend(scrape_nominations(existing_links))

    all_items.extend(
        scrape_section(
            key="press_majority",
            list_url=PRESS_MAJORITY_URL,
            category_en="Republican News",
            category="共和党新闻",
            party="共和党",
            mode="press_majority",
            existing_links=existing_links,
        )
    )

    all_items.extend(
        scrape_section(
            key="press_minority",
            list_url=PRESS_MINORITY_URL,
            category_en="Democratic News",
            category="民主党新闻",
            party="民主党",
            mode="press_minority",
            existing_links=existing_links,
        )
    )

    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)