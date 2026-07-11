# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "close",
}


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)

    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )

    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_session()

COMMITTEE_EN = "Senate Foreign Relations Committee"
COMMITTEE_ZH = "美国参议院外交关系委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.foreign.senate.gov"

BAD_TITLES = {
    "",
    "press",
    "majority",
    "minority",
    "hearings",
    "committee events",
    "calendar",
    "nominations",
    "treaties",
    "legislation",
    "filter",
    "filter results",
    "search",
    "next",
    "previous",
    "home",
    "published",
    "check status",
    "title",
    "doc",
    "bill",
    "last action",
}

SECTIONS = [
    {
        "key": "chair_press",
        "mode": "press",
        "category_en": "Republican News",
        "category": "共和党新闻",
        "party": "共和党",
        "list_url": "https://www.foreign.senate.gov/press/chair",
        "detail_prefixes": [
            "/press/rep/release/",
            "/press/chair/release/",
            "/press/release/",
        ],
    },
    {
        "key": "ranking_press",
        "mode": "press",
        "category_en": "Democratic News",
        "category": "民主党新闻",
        "party": "民主党",
        "list_url": "https://www.foreign.senate.gov/press/ranking",
        "detail_prefixes": [
            "/press/dem/release/",
            "/press/ranking/release/",
            "/press/release/",
        ],
    },
    {
        "key": "hearings",
        "mode": "hearings",
        "category_en": "Hearing",
        "category": "听证会",
        "party": "",
        "list_url": "https://www.foreign.senate.gov/hearings",
        "detail_prefixes": [
            "/hearings/",
        ],
    },
    {
        "key": "nominations",
        "mode": "nominations",
        "category_en": "Nomination",
        "category": "提名",
        "party": "",
        "list_url": "https://www.foreign.senate.gov/activities-and-reports/nominations",
    },
    {
        "key": "treaties",
        "mode": "treaties",
        "category_en": "Treaty",
        "category": "条约",
        "party": "",
        "list_url": "https://www.foreign.senate.gov/activities-and-reports/treaties",
    },
    {
        "key": "legislation",
        "mode": "legislation",
        "category_en": "Legislation",
        "category": "立法",
        "party": "",
        "list_url": "https://www.foreign.senate.gov/activities-and-reports/legislation",
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


def fetch(url: str, timeout: int = 30) -> BeautifulSoup:
    """
    稳定抓取页面：
    - 使用全局 Session 复用连接配置
    - 对 429/5xx、连接断开、读取失败自动重试
    - 对 foreign.senate.gov 偶发 SSLEOFError 更友好
    """
    last_error = None

    for attempt in range(1, 4):
        try:
            resp = SESSION.get(url, timeout=(10, timeout))
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.SSLError as e:
            last_error = e
            print(f"请求SSL失败，准备重试({attempt}/3): {url} | {e}")
            time.sleep(1.5 * attempt)
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"请求失败，准备重试({attempt}/3): {url} | {e}")
            time.sleep(1.5 * attempt)

    raise last_error


def parse_date(text: str):
    text = clean_text(text)
    if not text:
        return None

    now = datetime.now()

    m = re.search(r"Received Date:\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y")
        except Exception:
            pass

    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d")
        except Exception:
            pass

    direct_patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
        "%b %d %I:%M %p %Y",
        "%b %d %H:%M %Y",
        "%b %d %I:%M%p %Y",
        "%b %d %H:%M%Y",
    ]

    for fmt in direct_patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    patterns = [
        r"Published:\s*([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]{2} \d{1,2}, \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        candidate = m.group(1)
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(candidate, fmt)
            except Exception:
                pass

    m = re.search(
        r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{1,2}:\d{2})\s*([AP]M)\b",
        text,
    )
    if m:
        candidate = f"{m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)} {now.year}"
        try:
            return datetime.strptime(candidate, "%b %d %I:%M %p %Y")
        except Exception:
            pass

    m = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b", text)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {now.year}", "%b %d %Y")
        except Exception:
            pass

    m = re.search(r"Last Action\s+(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1), "%m/%d/%Y")
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
            txt_l = txt.lower()
            if txt and txt_l not in BAD_TITLES and len(txt) >= 8:
                return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup):
    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if (
            re.search(r"Published:\s*[A-Z][a-z]+ \d{1,2}, \d{4}", txt)
            or re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt)
            or re.search(r"\d{1,2}/\d{1,2}/\d{4}", txt)
            or re.search(r"\b[A-Z][a-z]{2}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*[AP]M\b", txt)
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


def _is_bad_anchor_title(title: str) -> bool:
    title = clean_text(title)
    if not title:
        return True
    if title.lower() in BAD_TITLES:
        return True
    if len(title) < 6:
        return True
    return False


def _nearest_block(anchor):
    for parent in anchor.parents:
        if getattr(parent, "name", "") in {"article", "li", "div", "section", "tr"}:
            text = clean_text(parent.get_text(" ", strip=True))
            if text:
                return parent
    return anchor.parent


def _looks_like_detail_path(path: str, detail_prefixes: list[str]) -> bool:
    path = (path or "").rstrip("/")

    blocked = {
        "/press/chair",
        "/press/ranking",
        "/press",
        "/hearings",
        "/hearings/calendar",
        "/activities-and-reports/nominations",
        "/activities-and-reports/treaties",
        "/activities-and-reports/legislation",
    }
    if path in blocked:
        return False

    for prefix in detail_prefixes or []:
        prefix = prefix.rstrip("/")
        if path.startswith(prefix) and path != prefix:
            return True
    return False


def _extract_inline_summary(block_text: str, title: str, limit: int = 200) -> str:
    text = clean_text(block_text)
    if not text:
        return ""

    if title and title in text:
        text = text.replace(title, "", 1).strip()

    text = re.sub(r"^(Published:\s*)?[A-Z][a-z]+ \d{1,2}, \d{4}", "", text).strip()
    text = re.sub(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{1,2}:\d{2}\s*[AP]M", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


def collect_detail_links(list_url: str, section: dict) -> list[dict]:
    soup = fetch(list_url)
    mode = section["mode"]
    rows = []
    seen = set()

    if mode in {"press", "hearings"}:
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
            if _is_bad_anchor_title(title):
                continue

            block = _nearest_block(a)
            block_text = clean_text(block.get_text(" ", strip=True)) if block else title
            list_dt = parse_date(block_text)

            norm = normalize_link(full_url)
            if norm in seen:
                continue
            seen.add(norm)

            rows.append(
                {
                    "title": title,
                    "link": norm,
                    "list_date": list_dt,
                    "summary": _extract_inline_summary(block_text, title, limit=200),
                    "raw_text": block_text,
                }
            )

        return rows

    if mode == "nominations":
        for block in soup.find_all(["article", "li", "div", "section", "tr"]):
            text = clean_text(block.get_text(" ", strip=True))
            if "Nomination Number:" not in text:
                continue
            if "Check Status" not in text:
                continue

            recv_m = re.search(r"Received Date:\s*(\d{1,2}/\d{1,2}/\d{4})", text)
            dt = parse_date(recv_m.group(1)) if recv_m else parse_date(text)
            if not dt:
                continue

            m = re.search(
                r"\d{1,2}/\d{1,2}/\d{4}\s+(.*?)\s+Nomination Number:",
                text,
                re.S,
            )
            if not m:
                continue

            title = clean_text(m.group(1))
            if _is_bad_anchor_title(title):
                continue

            link = ""
            for a in block.find_all("a", href=True):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                if "congress.gov" in href.lower():
                    link = normalize_link(href)
                    break

            if not link:
                continue
            if link in seen:
                continue
            seen.add(link)

            nom_m = re.search(r"Nomination Number:\s*([A-Z0-9\-]+)", text)
            parts = []
            if nom_m:
                parts.append(f"Nomination Number: {nom_m.group(1)}")
            if recv_m:
                parts.append(f"Received Date: {recv_m.group(1)}")

            summary_text = " | ".join(parts)
            if len(summary_text) > 200:
                summary_text = summary_text[:200].rstrip() + "..."

            rows.append(
                {
                    "title": title,
                    "link": link,
                    "list_date": dt,
                    "summary": summary_text,
                    "raw_text": text,
                }
            )

        return rows

    if mode == "treaties":
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            title = clean_text(a.get_text(" ", strip=True))

            if not href or _is_bad_anchor_title(title):
                continue
            if "congress.gov" not in href.lower():
                continue

            block = _nearest_block(a)
            text = clean_text(block.get_text(" ", strip=True)) if block else title
            if "Last Action" not in text:
                continue
            if "Doc" not in text:
                continue

            dt = parse_date(text)
            if not dt:
                continue

            link = normalize_link(href)
            if link in seen:
                continue
            seen.add(link)

            doc_m = re.search(r"Doc\s+([A-Z0-9\-\.]+)", text, re.I)
            summary_text = f"Doc: {doc_m.group(1)}" if doc_m else ""
            if len(summary_text) > 200:
                summary_text = summary_text[:200].rstrip() + "..."

            rows.append(
                {
                    "title": title,
                    "link": link,
                    "list_date": dt,
                    "summary": summary_text,
                    "raw_text": text,
                }
            )

        return rows

    if mode == "legislation":
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            text = clean_text(a.get_text(" ", strip=True))

            if not href or "congress.gov" not in href.lower():
                continue
            if "Last Action" not in text or "Bill" not in text or "Title" not in text:
                continue

            dt = parse_date(text)
            if not dt:
                continue

            bill_m = re.search(r"Bill\s+([A-Z0-9\.\-]+)", text, re.I)
            title_m = re.search(r"Title\s+(.+)$", text, re.I)

            title = clean_text(title_m.group(1)) if title_m else text
            if _is_bad_anchor_title(title):
                continue

            link = normalize_link(href)
            if link in seen:
                continue
            seen.add(link)

            summary_text = f"Bill: {bill_m.group(1)}" if bill_m else ""
            if len(summary_text) > 200:
                summary_text = summary_text[:200].rstrip() + "..."

            rows.append(
                {
                    "title": title,
                    "link": link,
                    "list_date": dt,
                    "summary": summary_text,
                    "raw_text": text,
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
    if len(summary or "") > 200:
        summary = (summary or "")[:200].rstrip() + "..."

    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": category_en,
        "category": category,
        "title": title,
        "summary": summary or "",
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

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    items = []
    page = 1
    consecutive_skip_count = 0
    seen_detail_urls = set()

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

            if not link or link in seen_detail_urls:
                continue
            seen_detail_urls.add(link)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            check_dt = list_dt

            if mode in {"press", "hearings"} and check_dt:
                if check_dt.date() < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title_from_list}")
                    consecutive_skip_count += 1
                    if consecutive_skip_count >= SKIP_LIMIT:
                        print(f"连续跳过达到{SKIP_LIMIT}条，停止当前分类")
                        return items
                    continue

            if mode in {"nominations", "treaties", "legislation"}:
                if not check_dt:
                    print(f"跳过(列表页无日期): {title_from_list}")
                    continue
                if check_dt.date() < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {title_from_list}")
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
                    title=title_from_list,
                    summary=summary_from_list,
                    article_dt=check_dt,
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
            detail_dt = parse_date(detail_title) or list_dt or extract_date_from_soup(soup)
            detail_summary = extract_summary(soup, limit=200) or summary_from_list

            if not detail_title or not detail_dt:
                print(f"跳过(无标题/日期): {link}")
                continue

            if mode in {"press", "hearings"} and not list_dt:
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
