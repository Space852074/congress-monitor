# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

TIME_WINDOW_DAYS = 10
SKIP_LIMIT = 5
MAX_PAGES = 60
NO_NEW_PAGE_LIMIT = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}

COMMITTEE_EN = "Senate Banking Committee"
COMMITTEE_ZH = "美国参议院银行、住房与城市事务委员会"
CHAMBER = "Senate"
BASE_URL = "https://www.sbc.senate.gov"

BAD_TITLES = {
    "hearings",
    "hearing",
    "press releases",
    "press release",
    "republican press releases",
    "democratic press releases",
    "news",
    "home",
    "next >",
    "< prev",
    "last",
    "first",
    "jump to page",
    "read more",
}

HEARINGS_URL = "https://www.sbc.senate.gov/public/index.cfm/hearings"
REPUBLICAN_URL = "https://www.sbc.senate.gov/public/index.cfm/republicanpressreleases"
DEMOCRATIC_URL = "https://www.sbc.senate.gov/public/index.cfm/democraticpressreleases"


# =========================
# 基础工具
# =========================
def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() != "utm_source"
    ]
    query = urlencode(query_pairs)

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

    patterns = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass

    matchers = [
        (r"([A-Z][a-z]+ \d{1,2}, \d{4})", ["%B %d, %Y", "%b %d, %Y"]),
        (r"(\d{1,2}/\d{1,2}/\d{2,4})", ["%m/%d/%Y", "%m/%d/%y"]),
    ]

    for pattern, fmts in matchers:
        m = re.search(pattern, text)
        if not m:
            continue
        for fmt in fmts:
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
        ".contenttitle",
        ".news-title",
        ".article-title",
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
    """
    详情页日期提取：
    - 优先取标题附近 / 顶部区域日期
    - 不轻易用正文中出现的历史日期覆盖发布日期
    - 兜底时返回页面里解析到的“最新日期”
    """
    candidate_nodes = []

    priority_selectors = [
        "time",
        "main time",
        "article time",
        "h1 + *",
        "h1 + div",
        "h1 + p",
        "h1 + span",
        ".date",
        ".published",
        ".post-date",
        ".article-date",
        ".news-date",
        ".contenttitle + *",
    ]

    for selector in priority_selectors:
        for node in soup.select(selector):
            candidate_nodes.append(node)

    for tag in soup.find_all(["time", "span", "div", "p", "strong", "li", "td", "h4"]):
        candidate_nodes.append(tag)

    seen_text = set()
    parsed_dates = []

    for node in candidate_nodes:
        txt = clean_text(node.get_text(" ", strip=True))
        if not txt or txt in seen_text:
            continue
        seen_text.add(txt)

        if re.search(r"[A-Z][a-z]+ \d{1,2}, \d{4}", txt) or re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", txt):
            dt = parse_date(txt)
            if dt:
                parsed_dates.append(dt)

    if not parsed_dates:
        return None

    return max(parsed_dates)


def extract_summary(soup: BeautifulSoup, limit: int = 200) -> str:
    candidates: list[str] = []

    selectors = [
        "main p",
        "article p",
        ".main-content p",
        ".content p",
        ".entry-content p",
        ".news-body p",
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


# =========================
# 块解析
# =========================
def _is_valid_internal_link(full_url: str) -> bool:
    host = urlparse(full_url).netloc.lower().replace("www.", "")
    return host == "sbc.senate.gov"


def _looks_like_hearing_detail(full_url: str) -> bool:
    parsed = urlparse(full_url)
    path = (parsed.path or "").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if path != "/public/index.cfm/hearings":
        return False
    if not query.get("ID"):
        return False
    return True


def _looks_like_press_detail(full_url: str) -> bool:
    parsed = urlparse(full_url)
    path = (parsed.path or "").lower()
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    if path != "/public/index.cfm/pressreleases":
        return False
    if not query.get("ID"):
        return False
    return True


def collect_hearing_blocks(soup: BeautifulSoup) -> list[dict]:
    blocks: list[dict] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        full_url = urljoin(BASE_URL, href)
        if not _is_valid_internal_link(full_url):
            continue
        if not _looks_like_hearing_detail(full_url):
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        parent = a.find_parent(["tr", "li", "div", "section", "article"]) or a.parent
        block_text = clean_text(parent.get_text(" ", strip=True)) if parent else title
        article_dt = parse_date(block_text)

        norm_link = normalize_link(full_url)
        key = (norm_link, title.lower())
        if key in seen:
            continue
        seen.add(key)

        blocks.append({
            "title": title,
            "link": norm_link,
            "date": article_dt,
            "block_text": block_text,
        })

    return blocks


def collect_press_blocks(soup: BeautifulSoup) -> list[dict]:
    blocks: list[dict] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue

        full_url = urljoin(BASE_URL, href)
        if not _is_valid_internal_link(full_url):
            continue
        if not _looks_like_press_detail(full_url):
            continue

        title = clean_text(a.get_text(" ", strip=True))
        if not title or title.lower() in BAD_TITLES:
            continue

        parent = a.find_parent(["tr", "li", "div", "section", "article"]) or a.parent
        block_text = clean_text(parent.get_text(" ", strip=True)) if parent else title
        article_dt = parse_date(block_text)

        norm_link = normalize_link(full_url)
        key = (norm_link, title.lower())
        if key in seen:
            continue
        seen.add(key)

        blocks.append({
            "title": title,
            "link": norm_link,
            "date": article_dt,
            "block_text": block_text,
        })

    return blocks


# =========================
# 业务逻辑
# =========================
def build_item(
    *,
    category_en: str,
    category_zh: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
    party: str = "",
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
        "party": party,
    }


def dedupe_items(items: list[dict]) -> list[dict]:
    seen = set()
    result = []

    for item in items:
        key = (
            normalize_link(item.get("link", "")),
            clean_text(item.get("title", "")).lower(),
            clean_text(item.get("sort_date", item.get("date", ""))),
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


def scrape_section(
    *,
    key: str,
    list_url: str,
    category_en: str,
    category_zh: str,
    party: str,
    block_collector,
    existing_links: set[str],
) -> list[dict]:
    print(f"\n====== {category_en} ======")

    cutoff_date = (datetime.now() - timedelta(days=TIME_WINDOW_DAYS)).date()
    page = 1
    consecutive_old_count = 0
    no_new_page_count = 0
    seen_detail_urls: set[str] = set()
    items: list[dict] = []

    while page <= MAX_PAGES:
        paged_url = make_paged_url(list_url, page)

        try:
            soup = fetch(paged_url)
            blocks = block_collector(soup)
        except Exception as e:
            print(f"[{key}] 第 {page} 页抓取失败: {paged_url} | {e}")
            break

        if not blocks:
            print(f"[{key}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{key}] 第 {page} 页候选链接: {len(blocks)} | {paged_url}")

        found_new_on_page = False

        for block in blocks:
            norm_link = normalize_link(block.get("link", ""))
            list_title = clean_text(block.get("title", ""))
            list_dt = block.get("date")

            if not norm_link or norm_link in seen_detail_urls:
                continue
            seen_detail_urls.add(norm_link)

            if norm_link in existing_links:
                print(f"跳过(已存在): {norm_link}")
                continue

            # 先用列表页日期判断；这是该站最可靠的发布日期来源。
            if list_dt:
                if list_dt.date() < cutoff_date:
                    print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {list_title}")
                    consecutive_old_count += 1
                    if consecutive_old_count >= SKIP_LIMIT:
                        print("连续跳过达到5条，停止当前分类")
                        return items
                    continue
                consecutive_old_count = 0

            try:
                detail_soup = fetch(norm_link)
            except Exception as e:
                print(f"跳过(详情页抓取失败): {norm_link} | {e}")
                continue

            detail_title = extract_title(detail_soup) or list_title

            # 关键修复：
            # 列表页已有日期时，绝不允许详情页日期覆盖它，
            # 否则正文中的历史日期会误伤发布日期判断。
            detail_dt = list_dt or extract_date_from_soup(detail_soup)

            if not detail_title or not detail_dt:
                print(f"跳过(无标题/日期): {norm_link}")
                continue

            # 只有“列表页无日期”时，才会走到这里的详情页日期判断。
            if not list_dt and detail_dt.date() < cutoff_date:
                print(f"跳过(超出最近{TIME_WINDOW_DAYS}天): {detail_title}")
                consecutive_old_count += 1
                if consecutive_old_count >= SKIP_LIMIT:
                    print("连续跳过达到5条，停止当前分类")
                    return items
                continue

            consecutive_old_count = 0
            found_new_on_page = True

            summary = extract_summary(detail_soup, limit=200)
            items.append(
                build_item(
                    category_en=category_en,
                    category_zh=category_zh,
                    title=detail_title,
                    summary=summary,
                    article_dt=detail_dt,
                    link=norm_link,
                    party=party,
                )
            )
            print(f"+ {detail_title}")
            time.sleep(0.2)

        if not found_new_on_page:
            no_new_page_count += 1
            print(f"[{key}] 第 {page} 页没有新增有效数据")
            if no_new_page_count >= NO_NEW_PAGE_LIMIT:
                print("连续5页没有新增有效数据，停止当前分类")
                break
        else:
            no_new_page_count = 0

        page += 1

    return items


def run_committee(existing_links=None) -> list[dict]:
    existing_links = {
        normalize_link(x) for x in (existing_links or set()) if (x or "").strip()
    }

    hearing_items = scrape_section(
        key="hearings",
        list_url=HEARINGS_URL,
        category_en="Hearing",
        category_zh="听证会",
        party="",
        block_collector=collect_hearing_blocks,
        existing_links=existing_links,
    )

    republican_items = scrape_section(
        key="republican",
        list_url=REPUBLICAN_URL,
        category_en="Republican News",
        category_zh="共和党新闻",
        party="共和党",
        block_collector=collect_press_blocks,
        existing_links=existing_links,
    )

    democratic_items = scrape_section(
        key="democratic",
        list_url=DEMOCRATIC_URL,
        category_en="Democratic News",
        category_zh="民主党新闻",
        party="民主党",
        block_collector=collect_press_blocks,
        existing_links=existing_links,
    )

    all_items = hearing_items + republican_items + democratic_items
    return dedupe_items(all_items)


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条\n")

    for i, row in enumerate(data, 1):
        print(f"{i}. [{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(f"LINK: {row.get('link', '')}")
        print("-" * 120)
