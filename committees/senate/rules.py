# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup, Tag

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
NO_NEW_PAGE_LIMIT = 5
MAX_PAGES = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Rules Committee"
COMMITTEE_ZH = "美国参议院规则与行政委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.rules.senate.gov"

HEARINGS_URL = "https://www.rules.senate.gov/hearings/list"
LEGISLATION_URL = "https://www.rules.senate.gov/hearings/legislation"
NOMINATIONS_URL = "https://www.rules.senate.gov/hearings/nominations"
MAJORITY_NEWS_URL = "https://www.rules.senate.gov/news/majority-news"
MINORITY_NEWS_URL = "https://www.rules.senate.gov/news/minority-news"

BAD_TITLES = {
    "hearings",
    "hearings list",
    "legislation",
    "nominations",
    "news",
    "press releases",
    "majority news",
    "minority news",
    "calendar",
    "update",
    "search",
    "check status",
    "next",
    "previous",
    "home",
    "postponed",
}


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(urljoin(BASE_URL, url))
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    query_items = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    query = urlencode(query_items)
    return urlunparse((scheme, netloc, path, "", query, ""))



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

    direct_formats = [
        "%A, %B %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
    ]
    for fmt in direct_formats:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    patterns = [
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
        r"(\d{1,2}/\d{1,2}/\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        candidate = m.group(1)
        for fmt in direct_formats:
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
        ".news-title",
        ".main-content h1",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if txt and txt.lower() not in BAD_TITLES:
                return txt

    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        txt = clean_text(og.get("content", "")).split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    title_tag = soup.find("title")
    if title_tag:
        txt = clean_text(title_tag.get_text(" ", strip=True)).split("|")[0].strip()
        if txt and txt.lower() not in BAD_TITLES:
            return txt

    return ""



def extract_date_from_soup(soup: BeautifulSoup):
    selectors = [
        "time",
        ".published",
        ".date",
        ".publish-date",
        "article",
        "main",
        "body",
    ]
    seen = set()
    for selector in selectors:
        for node in soup.select(selector):
            txt = clean_text(node.get_text(" ", strip=True))
            if not txt or txt in seen:
                continue
            seen.add(txt)
            dt = parse_date(txt)
            if dt:
                return dt
    return None



def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates: list[str] = []
    selectors = [
        "article p",
        "main p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        ".rich-text p",
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

    summary = clean_text(" ".join(candidates[:3]))
    if len(summary) > limit:
        summary = summary[:limit].rstrip() + "..."
    return summary



def build_item(*, category_en: str, category: str, title: str, summary: str, dt: datetime, link: str, party: str = "") -> dict:
    return {
        "committee_en": COMMITTEE_EN,
        "committee_zh": COMMITTEE_ZH,
        "chamber": CHAMBER,
        "category_en": category_en,
        "category": category,
        "title": title,
        "summary": summary[:200],
        "date": f"{dt.year}年{dt.month}月{dt.day}日",
        "sort_date": dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": party,
    }



def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            clean_text(item.get("title", "")).lower(),
            item.get("sort_date", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out



def is_real_rules_link(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower().replace("www.", "") == "rules.senate.gov"



def extract_section_root(soup: BeautifulSoup, marker_text: str) -> Tag | BeautifulSoup:
    marker_text = marker_text.lower()
    for node in soup.find_all(["main", "section", "div", "article"]):
        txt = clean_text(node.get_text(" ", strip=True)).lower()
        if marker_text in txt:
            return node
    return soup



def collect_hearing_blocks(soup: BeautifulSoup) -> list[dict]:
    root = extract_section_root(soup, "hearing type")
    text_nodes = root.find_all(string=True)
    blocks: list[dict] = []
    current: dict | None = None

    def finalize():
        nonlocal current
        if not current:
            return
        title = clean_text(current.get("title", ""))
        link = normalize_link(current.get("link", ""))
        if title and link:
            blocks.append(current)
        current = None

    for raw in text_nodes:
        text = clean_text(str(raw))
        if not text:
            continue

        if text.startswith("Hearing type:"):
            finalize()
            current = {"hearing_type": clean_text(text.split(":", 1)[1]), "title": "", "link": "", "date_text": "", "location": ""}
            continue

        if current is None:
            continue

        parent = raw.parent if isinstance(raw.parent, Tag) else None
        if parent and parent.name == "a":
            href = parent.get("href", "")
            full = normalize_link(urljoin(BASE_URL, href))
            title = clean_text(parent.get_text(" ", strip=True))
            if (
                title
                and title.lower() not in BAD_TITLES
                and is_real_rules_link(full)
                and "/hearings/" in urlparse(full).path
            ):
                current["title"] = title
                current["link"] = full
                continue

        if text.startswith("Date:"):
            current["date_text"] = clean_text(text.split(":", 1)[1])
            continue

        if text.startswith("Location:"):
            current["location"] = clean_text(text.split(":", 1)[1])
            continue

    finalize()
    return blocks



def collect_legislation_blocks(soup: BeautifulSoup) -> list[dict]:
    root = extract_section_root(soup, "last action")
    text_blob = clean_text(root.get_text("\n", strip=True))

    pattern = re.compile(
        r"Last Action\s*(\d{2}/\d{2}/\d{4})\s*Bill\s*([A-Za-z0-9.\-]+)\s*Title\s*(.+?)(?=\s*Last Action\s*\d{2}/\d{2}/\d{4}|\s*Showing page|\Z)",
        re.S,
    )

    blocks: list[dict] = []
    raw_matches = list(pattern.finditer(text_blob))

    congress_links: list[str] = []
    seen = set()
    for a in root.find_all("a", href=True):
        href = normalize_link(a.get("href", ""))
        if "congress.gov" not in href:
            continue
        if href in seen:
            continue
        seen.add(href)
        congress_links.append(href)

    for idx, m in enumerate(raw_matches):
        dt_text = clean_text(m.group(1))
        bill = clean_text(m.group(2))
        title = clean_text(m.group(3))
        title = re.sub(r"\s*†?www\.congress\.gov\s*$", "", title, flags=re.I).strip()
        if not dt_text or not bill or not title:
            continue

        link = congress_links[idx] if idx < len(congress_links) else ""
        blocks.append({
            "date_text": dt_text,
            "bill": bill,
            "title": title,
            "link": link,
        })

    return blocks



def collect_nomination_blocks(soup: BeautifulSoup) -> list[dict]:
    root = extract_section_root(soup, "nomination number")
    text_nodes = root.find_all(string=True)
    blocks: list[dict] = []
    current: dict | None = None

    def looks_like_start(text: str) -> bool:
        return bool(re.fullmatch(r"\d{2}/\d{2}/\d{4}", text))

    def finalize():
        nonlocal current
        if not current:
            return
        if current.get("title") and current.get("date_text"):
            blocks.append(current)
        current = None

    for raw in text_nodes:
        text = clean_text(str(raw))
        if not text:
            continue

        if looks_like_start(text):
            finalize()
            current = {
                "date_text": text,
                "title": "",
                "nomination_number": "",
                "received_date": "",
                "last_action": "",
                "link": "",
            }
            continue

        if current is None:
            continue

        if text.startswith("Nomination Number:"):
            current["nomination_number"] = clean_text(text.split(":", 1)[1])
            continue
        if text.startswith("Received Date:"):
            current["received_date"] = clean_text(text.split(":", 1)[1])
            continue
        if text.startswith("Last Action:"):
            current["last_action"] = clean_text(text.split(":", 1)[1])
            continue

        parent = raw.parent if isinstance(raw.parent, Tag) else None
        if parent and parent.name == "a":
            href = (parent.get("href") or "").strip()
            label = clean_text(parent.get_text(" ", strip=True))
            if "check status" in label.lower() and href:
                current["link"] = normalize_link(href)
            continue

        low = text.lower()
        if (
            not current.get("title")
            and not low.startswith("received date")
            and not low.startswith("last action")
            and not low.startswith("nomination number")
            and low not in BAD_TITLES
            and len(text) > 12
        ):
            current["title"] = text

    finalize()

    for item in blocks:
        if not item.get("link"):
            anchor = re.sub(r"[^A-Za-z0-9\-_.]+", "-", item.get("nomination_number", "")).strip("-")
            item["link"] = normalize_link(f"{NOMINATIONS_URL}#{anchor}") if anchor else normalize_link(NOMINATIONS_URL)

    return blocks



def collect_news_blocks(soup: BeautifulSoup, section_prefix: str) -> list[dict]:
    blocks: list[dict] = []
    used = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        full = normalize_link(urljoin(BASE_URL, href))
        if not is_real_rules_link(full):
            continue

        path = urlparse(full).path.rstrip("/")
        # 该站 minority news 列表里的详情链接实际也会落在 /news/majority-news/ 下
        if not (path.startswith("/news/majority-news/") or path.startswith("/news/minority-news/")):
            continue
        if path in {"/news/majority-news", "/news/minority-news"}:
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue
        if full in used:
            continue

        container = a.find_parent(["li", "article", "div", "section"]) or a.parent
        block_text = clean_text(container.get_text(" ", strip=True)) if container else title
        date_match = re.search(r"([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", block_text)
        date_text = date_match.group(1) if date_match else ""
        summary = block_text
        if date_text:
            summary = clean_text(summary.replace(date_text, "", 1))
        summary = clean_text(summary.replace(title, "", 1))

        blocks.append({
            "title": title,
            "link": full,
            "date_text": date_text,
            "summary": summary,
        })
        used.add(full)

    return blocks



def collect_detail_links(section_key: str, soup: BeautifulSoup) -> list[dict]:
    if section_key == "hearings":
        return collect_hearing_blocks(soup)
    if section_key == "legislation":
        return collect_legislation_blocks(soup)
    if section_key == "nominations":
        return collect_nomination_blocks(soup)
    if section_key == "majority_news":
        return collect_news_blocks(soup, "/news/majority-news/")
    if section_key == "minority_news":
        return collect_news_blocks(soup, "/news/minority-news/")
    return []



def make_paged_url(base_url: str, page: int) -> str:
    if page <= 1:
        return base_url
    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["pagenum_rs"] = str(page)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(query), ""))



def scrape_section(section: dict, existing_links=None) -> list[dict]:
    existing_links = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    key = section["key"]
    list_url = section["list_url"]
    category_en = section["category_en"]
    category = section["category"]
    party = section.get("party", "")

    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()
    items: list[dict] = []
    seen_keys = set()
    consecutive_old = 0
    empty_new_pages = 0

    for page in range(1, MAX_PAGES + 1):
        page_url = make_paged_url(list_url, page)
        try:
            soup = fetch(page_url)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {page_url} | {e}")
            break

        blocks = collect_detail_links(key, soup)
        if not blocks:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(blocks)} | {page_url}")

        found_new_on_page = False

        for block in blocks:
            title = clean_text(block.get("title", ""))
            link = normalize_link(block.get("link", ""))
            if not title or not link:
                continue

            dedupe_key = (link, title.lower(), block.get("date_text", ""))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)

            if link in existing_links:
                print(f"跳过(已存在): {link}")
                continue

            if key == "legislation":
                dt = parse_date(block.get("date_text", ""))
                if not dt:
                    print(f"跳过(列表页无日期): {title}")
                    continue
                if dt.date() < cutoff_date:
                    print(f"跳过(超出最近10天): {title}")
                    consecutive_old += 1
                    if consecutive_old >= SKIP_LIMIT:
                        print("连续跳过达到5条，停止当前分类")
                        return dedupe_items(items)
                    continue

                consecutive_old = 0
                summary_parts = []
                if block.get("bill"):
                    summary_parts.append(f"Bill: {block['bill']}")
                if block.get("title"):
                    summary_parts.append(block["title"])
                summary = clean_text(" | ".join(summary_parts))[:200]
                items.append(build_item(
                    category_en=category_en,
                    category=category,
                    title=title,
                    summary=summary,
                    dt=dt,
                    link=link,
                    party=party,
                ))
                found_new_on_page = True
                print(f"+ {title}")
                continue

            if key == "nominations":
                dt = parse_date(block.get("date_text", ""))
                if not dt:
                    print(f"跳过(列表页无日期): {title}")
                    continue
                if dt.date() < cutoff_date:
                    print(f"跳过(超出最近10天): {title}")
                    consecutive_old += 1
                    if consecutive_old >= SKIP_LIMIT:
                        print("连续跳过达到5条，停止当前分类")
                        return dedupe_items(items)
                    continue

                consecutive_old = 0
                summary_bits = []
                if block.get("nomination_number"):
                    summary_bits.append(f"Nomination Number: {block['nomination_number']}")
                if block.get("received_date"):
                    summary_bits.append(f"Received Date: {block['received_date']}")
                if block.get("last_action"):
                    summary_bits.append(f"Last Action: {block['last_action']}")
                summary = clean_text(" | ".join(summary_bits))[:200]
                items.append(build_item(
                    category_en=category_en,
                    category=category,
                    title=title,
                    summary=summary,
                    dt=dt,
                    link=link,
                    party=party,
                ))
                found_new_on_page = True
                print(f"+ {title}")
                continue

            list_dt = parse_date(block.get("date_text", ""))
            detail_soup = None
            if not list_dt:
                try:
                    detail_soup = fetch(link)
                    list_dt = extract_date_from_soup(detail_soup)
                except Exception:
                    list_dt = None

            if not list_dt:
                print(f"跳过(列表页无日期): {title}")
                continue

            if list_dt.date() < cutoff_date:
                print(f"跳过(超出最近10天): {title}")
                consecutive_old += 1
                if consecutive_old >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return dedupe_items(items)
                continue

            consecutive_old = 0

            if key == "hearings":
                summary_parts = []
                if block.get("hearing_type"):
                    summary_parts.append(f"Hearing type: {block['hearing_type']}")
                if block.get("location"):
                    summary_parts.append(f"Location: {block['location']}")
                summary = clean_text(" | ".join(summary_parts))[:200]
                items.append(build_item(
                    category_en=category_en,
                    category=category,
                    title=title,
                    summary=summary,
                    dt=list_dt,
                    link=link,
                    party=party,
                ))
                found_new_on_page = True
                print(f"+ {title}")
                continue

            if detail_soup is None:
                try:
                    detail_soup = fetch(link)
                except Exception as e:
                    print(f"跳过(详情页抓取失败): {link} | {e}")
                    continue

            detail_title = extract_title(detail_soup) or title
            detail_dt = list_dt or extract_date_from_soup(detail_soup)
            if not detail_dt:
                print(f"跳过(无标题/日期): {title}")
                continue

            summary = block.get("summary", "") or extract_summary(detail_soup, limit=200)
            summary = clean_text(summary)[:200]

            items.append(build_item(
                category_en=category_en,
                category=category,
                title=detail_title,
                summary=summary,
                dt=detail_dt,
                link=link,
                party=party,
            ))
            found_new_on_page = True
            print(f"+ {detail_title}")
            time.sleep(0.2)

        if key in {"hearings", "majority_news", "minority_news"}:
            if not found_new_on_page:
                empty_new_pages += 1
                print(f"[{key}] 第 {page} 页没有新增有效数据")
                if empty_new_pages >= NO_NEW_PAGE_LIMIT:
                    print(f"[{key}] 连续5页没有新增有效数据，停止当前分类")
                    break
            else:
                empty_new_pages = 0
        else:
            if not found_new_on_page:
                print(f"[{key}] 第 {page} 页没有新增有效数据")

    return dedupe_items(items)



def run_committee(existing_links=None):
    sections = [
        {
            "key": "hearings",
            "list_url": HEARINGS_URL,
            "category_en": "Hearing",
            "category": "听证会",
            "party": "",
        },
        {
            "key": "legislation",
            "list_url": LEGISLATION_URL,
            "category_en": "Legislation",
            "category": "立法",
            "party": "",
        },
        {
            "key": "nominations",
            "list_url": NOMINATIONS_URL,
            "category_en": "Nomination",
            "category": "提名",
            "party": "",
        },
        {
            "key": "majority_news",
            "list_url": MAJORITY_NEWS_URL,
            "category_en": "Republican News",
            "category": "共和党新闻",
            "party": "共和党",
        },
        {
            "key": "minority_news",
            "list_url": MINORITY_NEWS_URL,
            "category_en": "Democratic News",
            "category": "民主党新闻",
            "party": "民主党",
        },
    ]

    all_items: list[dict] = []
    existing_links = existing_links or set()

    for section in sections:
        try:
            all_items.extend(scrape_section(section, existing_links=existing_links))
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
