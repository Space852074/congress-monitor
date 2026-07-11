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
MAX_PAGES = 200

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Committee on Finance"
COMMITTEE_ZH = "美国参议院财政委员会"
CHAMBER = "Senate"
BASE_HOST = "www.finance.senate.gov"
BASE_URL = f"https://{BASE_HOST}"

BAD_TITLES = {
    "hearings",
    "hearing",
    "chairman's news",
    "chairmans news",
    "ranking member's news",
    "ranking members news",
    "republican news",
    "democratic news",
    "committee reports",
    "committee report",
    "library",
    "newsroom",
    "the united states senate committee on finance",
    "senate committee on finance",
    "finance committee",
    "united states senate committee on finance",
    "search",
    "filter",
}

SECTIONS = [
    {
        "key": "hearings",
        "kind": "hearings",
        "list_url": "https://www.finance.senate.gov/hearings",
        "category_en": "Hearing",
        "category_zh": "听证会",
        "party": "",
    },
    {
        "key": "chairmans_news",
        "kind": "chairmans_news",
        "list_url": "https://www.finance.senate.gov/chairmans-news",
        "category_en": "Republican News",
        "category_zh": "共和党新闻",
        "party": "Republican",
    },
    {
        "key": "ranking_members_news",
        "kind": "ranking_members_news",
        "list_url": "https://www.finance.senate.gov/ranking-members-news",
        "category_en": "Democratic News",
        "category_zh": "民主党新闻",
        "party": "Democratic",
    },
    {
        "key": "committee_reports",
        "kind": "committee_reports",
        "list_url": "https://www.finance.senate.gov/library/committee-reports",
        "category_en": "Committee Report",
        "category_zh": "委员会报告",
        "party": "",
    },
]


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if not netloc:
        netloc = BASE_HOST
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", "", ""))


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def clean_href(href: str) -> str:
    return re.sub(r"\s+", "", (href or "").strip())


def fetch(url: str, timeout: int = 30) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_date(text: str) -> datetime | None:
    text = clean_text(text)
    if not text:
        return None

    patterns = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
        "%m/%d/%y %I:%M%p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %I:%M%p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%A, %B %d, %Y",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)", text)
    if m:
        iso = m.group(1)
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                return datetime.strptime(iso, fmt)
            except Exception:
                pass

    m = re.search(r"(\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}\s*[APap][Mm])", text)
    if m:
        raw = clean_text(m.group(1)).upper().replace(" ", "")
        for fmt in ("%m/%d/%y%I:%M%p", "%m/%d/%Y%I:%M%p"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                pass

    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(m.group(1), fmt)
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
        "h2",
    ]

    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in BAD_TITLES:
                return txt

    meta_title = soup.select_one('meta[property="og:title"]')
    if meta_title and meta_title.get("content"):
        txt = clean_text(meta_title.get("content", ""))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True))
        txt = txt.split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    return ""


def extract_date_from_soup(soup: BeautifulSoup) -> datetime | None:
    t = soup.find("time", attrs={"datetime": True})
    if t:
        dt = parse_date((t.get("datetime") or "").strip())
        if dt:
            return dt

    candidates = []

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li"]):
        txt = clean_text(tag.get_text(" ", strip=True))
        if not txt:
            continue

        if re.search(r"\d{4}-\d{2}-\d{2}", txt):
            candidates.append(txt)
        elif re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", txt):
            candidates.append(txt)
        elif re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt):
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
        ".entry-content p",
        ".content p",
        ".field--name-body p",
    ]

    for selector in selectors:
        for p in soup.select(selector):
            txt = clean_text(p.get_text(" ", strip=True))
            if txt and len(txt) > 20:
                low = txt.lower()
                if low in {"expand", "collapse", "filter", "search"}:
                    continue
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


def _same_site(netloc: str) -> bool:
    return netloc.lower().replace("www.", "") == BASE_HOST.replace("www.", "")


def _collect_hearings(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    for row in soup.select("tr.vevent"):
        a = row.select_one("a.url.summary")
        if not a:
            a = row.find("a", href=re.compile(r"^/hearings/[a-z0-9\-]+$"))
        if not a or not a.get("href"):
            continue

        href = clean_href(a.get("href", ""))
        if not href or "witnesses" in href or "add-to-calendar" in href:
            continue

        full = urljoin(BASE_URL, href)
        norm = normalize_link(full)
        if not norm or norm in seen:
            continue

        path = urlparse(full).path or ""
        if path.rstrip("/") in {"/hearings", "/hearings/witnesses"}:
            continue
        if not path.startswith("/hearings/"):
            continue

        list_dt = None
        tm = row.select_one("time.dtstart")
        if tm and tm.get("datetime"):
            list_dt = parse_date(tm.get("datetime", "").strip())
        if not list_dt and tm:
            list_dt = parse_date(tm.get_text(" ", strip=True))

        seen.add(norm)
        out.append({"link": norm, "list_date": list_dt})

    return out


def _collect_press_table(
    soup: BeautifulSoup,
    path_fragment: str,
) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    needle = f"/{path_fragment.strip('/')}/"

    for tr in soup.find_all("tr"):
        tcell = tr.find("td", class_=re.compile(r"date", re.I))
        if not tcell:
            continue

        tm = tcell.find("time", attrs={"datetime": True})
        list_dt = None
        if tm and tm.get("datetime"):
            list_dt = parse_date(tm.get("datetime", "").strip())
        if not list_dt:
            list_dt = parse_date(tcell.get_text(" ", strip=True))

        link_a = None
        for a in tr.find_all("a", href=True):
            raw = clean_href(a.get("href", ""))
            if not raw or raw.startswith("#"):
                continue
            full = urljoin(BASE_URL, raw)
            pth = (urlparse(full).path or "").lower()
            if needle not in pth.lower():
                continue
            if pth.rstrip("/") == needle.rstrip("/"):
                continue
            if "/download/" in pth:
                continue
            link_a = a
            break

        if not link_a:
            continue

        full = urljoin(BASE_URL, clean_href(link_a.get("href", "")))
        parsed = urlparse(full)
        if not _same_site(parsed.netloc):
            continue

        norm = normalize_link(full)
        if not norm or norm in seen:
            continue

        seen.add(norm)
        out.append({"link": norm, "list_date": list_dt})

    return out


def _collect_committee_reports(soup: BeautifulSoup) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()

    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"/download/", re.I))
        if not a or not a.get("href"):
            continue

        tcell = tr.find("td", class_=re.compile(r"date", re.I))
        list_dt = None
        if tcell:
            tm = tcell.find("time", attrs={"datetime": True})
            if tm and tm.get("datetime"):
                list_dt = parse_date(tm.get("datetime", "").strip())
            if not list_dt:
                list_dt = parse_date(tcell.get_text(" ", strip=True))

        full = urljoin(BASE_URL, clean_href(a.get("href", "")))
        parsed = urlparse(full)
        if not _same_site(parsed.netloc):
            continue
        if "/download/" not in (parsed.path or ""):
            continue

        norm = normalize_link(full)
        if not norm or norm in seen:
            continue

        seen.add(norm)
        out.append({"link": norm, "list_date": list_dt})

    return out


def collect_detail_links(list_url: str, section: dict) -> list[dict]:
    soup = fetch(list_url)
    kind = section.get("kind") or ""

    if kind == "hearings":
        return _collect_hearings(soup)
    if kind == "chairmans_news":
        return _collect_press_table(soup, "chairmans-news")
    if kind == "ranking_members_news":
        return _collect_press_table(soup, "ranking-members-news")
    if kind == "committee_reports":
        return _collect_committee_reports(soup)

    return []


def make_paged_url(list_url: str, page: int) -> str:
    base = list_url.split("?")[0].rstrip("/")
    if page <= 1:
        return base

    return f"{base}?page={page}&PageNum_rs={page}"


def build_item(
    category_en: str,
    category_zh: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
    party: str,
) -> dict:
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
        "party": party or "",
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []

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


def scrape_section(section: dict, existing_links: set[str]) -> list[dict]:
    key = section["key"]
    category_en = section["category_en"]
    category_zh = section["category_zh"]
    list_url = section["list_url"]
    party = section.get("party") or ""

    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()

    page = 1
    section_done = False
    consecutive_skip_count = 0
    seen_detail_urls: set[str] = set()
    items: list[dict] = []

    while not section_done:
        paged_url = make_paged_url(list_url, page)

        try:
            candidates = collect_detail_links(paged_url, section)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not candidates:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(candidates)} | {paged_url}")

        found_new_on_page = False

        for cand in candidates:
            norm_link = normalize_link(cand.get("link", ""))
            list_dt: datetime | None = cand.get("list_date")

            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            if list_dt and list_dt.date() < cutoff_date:
                print(f"跳过(列表日期超出最近{TIME_WINDOW_DAYS}天): {norm_link}")
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
            if not title:
                print(f"跳过(无标题): {norm_link}")
                continue

            article_dt = list_dt or extract_date_from_soup(soup)
            if not article_dt:
                print(f"跳过(无日期): {norm_link}")
                continue

            if article_dt.date() < cutoff_date:
                print(f"跳过(详情日期超出最近{TIME_WINDOW_DAYS}天): {title}")
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
                party=party,
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


def run_committee(existing_links=None) -> list[dict]:
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

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
