# -*- coding: utf-8 -*-
"""
veterans.py
Senate Veterans’ Affairs Committee scraper

目标：
- Majority News
- Minority News
- Hearings

规则：
1. 只抓最近10天
2. 连续跳过5条旧数据 -> 停止当前分类
3. 连续5页没有新增有效数据 -> 停止当前分类
4. 列表页无候选链接 -> 停止当前分类
5. summary 最长 200 字
6. 去重规则：link + title + date
7. requests + BeautifulSoup
8. 定义 BAD_TITLES
9. 不使用 Selenium
10. 完整可运行

兼容说明：
- 该站分页真实规则为 ?page=N
- 详情页真实规则为 /YYYY/M/slug
- 三个栏目结构分开处理，但共用统一基础函数
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag

BASE = "https://www.veterans.senate.gov"

COMMITTEE_EN = "Senate Veterans’ Affairs Committee"
COMMITTEE_ZH = "美国参议院退伍军人事务委员会"
CHAMBER = "Senate"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Connection": "keep-alive",
}

BAD_TITLES = {
    "",
    "home",
    "hearings",
    "majority news",
    "minority news",
    "chairman",
    "ranking member",
    "committee transcripts",
    "legislation",
    "nominations",
    "recent updates",
    "about",
    "committee members",
    "committee rules",
    "for veterans",
    "informational resources",
    "contact chairman",
    "contact ranking member",
    "sign up for email updates",
    "image",
    "facebook",
    "twitter",
    "menu",
    "skip to content",
    "skip navigation",
    "search",
    "whistleblower",
    "‹",
    "›",
    "«",
    "»",
}

SECTION_CONFIG = {
    "majority_news": {
        "label": "majority_news",
        "base_url": f"{BASE}/majority-news",
        "category_en": "Majority News",
        "category": "多数党新闻",
        "party": "共和党",
    },
    "minority_news": {
        "label": "minority_news",
        "base_url": f"{BASE}/minority-news",
        "category_en": "Minority News",
        "category": "少数党新闻",
        "party": "民主党",
    },
    "hearings": {
        "label": "hearings",
        "base_url": f"{BASE}/hearings",
        "category_en": "Hearing",
        "category": "听证会",
        "party": "",
    },
}


def normalize_link(link: str) -> str:
    """标准化链接，去掉 fragment，保留 query（因为分页要用 query）。"""
    if not link:
        return ""
    link = link.strip()
    if link.startswith("//"):
        link = "https:" + link
    link = urljoin(BASE, link)
    parsed = urlparse(link)
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)


def fetch(url: str, session: Optional[requests.Session] = None, timeout: int = 20) -> Optional[BeautifulSoup]:
    """拉取页面并返回 BeautifulSoup。"""
    sess = session or requests.Session()
    try:
        resp = sess.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        print(f"[fetch] 请求失败: {url} | {exc}")
        return None


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_bad_title(title: str) -> bool:
    t = clean_text(title).strip(" -–—|").lower()
    if not t:
        return True
    if t in BAD_TITLES:
        return True
    if len(t) <= 2:
        return True
    if t.startswith("page ") or t.startswith("type ") or t.startswith("month ") or t.startswith("year "):
        return True
    if re.fullmatch(r"\d+", t):
        return True
    return False


def parse_date(text: str) -> Optional[datetime]:
    """
    解析页面中的日期文本。
    支持：
    - Wednesday, March 18, 2026
    - March 18, 2026
    - March 18, 2026 04:00 PM 418 Russell...
    - Mar 18 4:00 pm （无年份时不直接认定）
    """
    if not text:
        return None

    raw = clean_text(text)

    # 先截取完整年月日
    m = re.search(
        r"(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+)?"
        r"([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})",
        raw,
    )
    if m:
        date_str = f"{m.group(2)} {m.group(3)}, {m.group(4)}"
        try:
            return datetime.strptime(date_str, "%B %d, %Y")
        except ValueError:
            pass

    # 缩写月 + 年（通常详情页不用这个；列表页若只有简写，一般回退到详情页）
    m2 = re.search(r"\b([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\b", raw)
    if m2:
        date_str = f"{m2.group(1)} {m2.group(2)}, {m2.group(3)}"
        try:
            return datetime.strptime(date_str, "%b %d, %Y")
        except ValueError:
            pass

    return None


def extract_title(soup: BeautifulSoup) -> str:
    """
    详情页标题提取：
    优先正文 h1，再回退 title/meta。
    """
    if not soup:
        return ""

    # 优先 main 区域中的 h1，取最后一个有效 h1
    candidates: List[str] = []

    for sel in [
        "main h1",
        "#main h1",
        ".main-content h1",
        ".content h1",
        "article h1",
        "h1",
    ]:
        for tag in soup.select(sel):
            text = clean_text(tag.get_text(" ", strip=True))
            if not is_bad_title(text) and text.lower() not in {"majority news", "minority news", "hearings"}:
                candidates.append(text)

    if candidates:
        # 详情页通常第二个 h1 才是真标题，取最长/最后一个都比较稳
        candidates = sorted(set(candidates), key=lambda x: (len(x), x))
        return candidates[-1]

    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        og_title = clean_text(og["content"]).split(" - U.S. Senate Committee on Veterans' Affairs")[0].strip()
        if not is_bad_title(og_title):
            return og_title

    if soup.title and soup.title.string:
        title = clean_text(soup.title.string)
        title = re.split(r"\s*-\s*U\.S\. Senate Committee on Veterans' Affairs", title)[0].strip()
        if not is_bad_title(title):
            return title

    return ""


def extract_date_from_soup(soup: BeautifulSoup) -> Optional[datetime]:
    """
    详情页日期提取：
    优先 main/article 区域，再全页兜底。
    """
    if not soup:
        return None

    roots: List[Tag] = []
    for sel in ["main", "#main", "#main-content", ".main-content", ".content", "article", "body"]:
        node = soup.select_one(sel)
        if node and isinstance(node, Tag):
            roots.append(node)

    seen_texts: Set[str] = set()
    for root in roots:
        # 优先 time 标签
        for t in root.find_all("time"):
            txt = clean_text(t.get_text(" ", strip=True))
            if txt and txt not in seen_texts:
                seen_texts.add(txt)
                dt = parse_date(txt)
                if dt:
                    return dt

        # 优先标题附近的短文本
        texts = list(root.stripped_strings)
        for txt in texts[:120]:
            txt = clean_text(txt)
            if txt and txt not in seen_texts:
                seen_texts.add(txt)
                dt = parse_date(txt)
                if dt:
                    return dt

    return None


def extract_summary(soup: BeautifulSoup, max_len: int = 200) -> str:
    """
    摘要提取：
    - 优先副标题 h2/h3
    - 再取正文首段
    - hearing 若没有正文段落，取 Agenda 附近首条有效文本
    """
    if not soup:
        return ""

    title = extract_title(soup)

    # 1) 副标题
    for sel in ["main h2", "article h2", ".main-content h2", ".content h2", "main h3", "article h3"]:
        for tag in soup.select(sel):
            txt = clean_text(tag.get_text(" ", strip=True))
            if not txt:
                continue
            if txt == title:
                continue
            if txt.lower() in {"agenda", "contact us"}:
                continue
            if "if you are having trouble viewing this hearing" in txt.lower():
                continue
            return txt[:max_len]

    # 2) 正文首段
    roots = []
    for sel in ["main", "#main", "#main-content", ".main-content", ".content", "article", "body"]:
        node = soup.select_one(sel)
        if node and isinstance(node, Tag):
            roots.append(node)

    bad_prefixes = (
        "home",
        "contact us",
        "sign up for email updates",
        "if you are having trouble viewing this hearing",
        "guide to clearing browser cache",
    )

    for root in roots:
        for p in root.find_all(["p", "div", "li"]):
            txt = clean_text(p.get_text(" ", strip=True))
            if not txt:
                continue
            low = txt.lower()
            if txt == title:
                continue
            if len(txt) < 30:
                continue
            if any(low.startswith(prefix) for prefix in bad_prefixes):
                continue
            if re.fullmatch(r"[#\s]+", txt):
                continue
            return txt[:max_len]

    # 3) 文本流兜底
    for root in roots:
        for txt in root.stripped_strings:
            txt = clean_text(txt)
            low = txt.lower()
            if not txt or txt == title:
                continue
            if len(txt) < 30:
                continue
            if any(low.startswith(prefix) for prefix in bad_prefixes):
                continue
            if low in {"agenda", "contact us"}:
                continue
            return txt[:max_len]

    return ""


def _build_page_url(base_url: str, page: int) -> str:
    return base_url if page == 1 else f"{base_url}?page={page}"


def _is_detail_url(link: str, section_key: str) -> bool:
    """
    真实详情页规则：
    /YYYY/M/slug
    """
    if not link:
        return False

    norm = normalize_link(link)
    parsed = urlparse(norm)

    if parsed.netloc and "veterans.senate.gov" not in parsed.netloc:
        return False

    path = parsed.path.rstrip("/")
    if not re.search(r"/\d{4}/\d{1,2}/[^/]+$", path):
        return False

    # 排除明显非详情
    if path in {"/majority-news", "/minority-news", "/hearings"}:
        return False

    return True


def _find_content_root(soup: BeautifulSoup, section_key: str) -> Tag:
    """
    找主要内容区，尽量不要全页乱扫。
    """
    section_titles = {
        "majority_news": "Majority News",
        "minority_news": "Minority News",
        "hearings": "Hearings",
    }

    for sel in [
        "main",
        "#main",
        "#main-content",
        ".main-content",
        ".content",
        ".page-content",
        ".site-main",
    ]:
        node = soup.select_one(sel)
        if node and isinstance(node, Tag):
            return node

    # 用包含栏目标题的标题节点反推容器
    target = section_titles.get(section_key, "")
    for h in soup.find_all(["h1", "h2"]):
        txt = clean_text(h.get_text(" ", strip=True))
        if txt == target:
            # 尝试返回最近的大容器
            parent = h
            for _ in range(5):
                if parent and isinstance(parent, Tag):
                    if parent.name in {"main", "section", "article", "div"}:
                        return parent
                    parent = parent.parent  # type: ignore[assignment]
            break

    return soup.body if soup.body else soup


def _extract_candidate_from_block(block: Tag, section_key: str) -> Optional[Dict[str, str]]:
    """
    从“块”中提取一条候选记录。
    必须以块为单位，不做全页 a 标签粗暴扫描。
    """
    anchors = block.find_all("a", href=True)
    if not anchors:
        return None

    valid_anchors = []
    for a in anchors:
        href = normalize_link(a.get("href", ""))
        if not _is_detail_url(href, section_key):
            continue
        title = clean_text(a.get_text(" ", strip=True))
        if is_bad_title(title):
            continue
        valid_anchors.append((a, href, title))

    if not valid_anchors:
        return None

    # 取文本最长的那个 anchor，避开空图片链接
    valid_anchors.sort(key=lambda x: len(x[2]), reverse=True)
    a, href, title = valid_anchors[0]

    block_text = clean_text(block.get_text(" ", strip=True))
    dt = parse_date(block_text)

    return {
        "title": title,
        "link": href,
        "date_text": block_text if dt else "",
    }


def _collect_blocks_majority_or_minority(root: Tag, section_key: str) -> List[Dict[str, str]]:
    """
    Majority/Minority News：
    优先 article/li/div/section 等条目块。
    """
    candidates: List[Dict[str, str]] = []
    seen_links: Set[str] = set()

    block_tags = root.find_all(["article", "li", "div", "section"], recursive=True)
    for block in block_tags:
        item = _extract_candidate_from_block(block, section_key)
        if not item:
            continue

        link = item["link"]
        title = item["title"]

        if link in seen_links:
            continue
        if is_bad_title(title):
            continue

        # 块文本中至少出现 News 或日期特征，减少误抓
        block_text = clean_text(block.get_text(" ", strip=True)).lower()
        has_date_hint = bool(re.search(r"[a-z]+ \d{1,2}, \d{4}", block_text))
        has_news_hint = "news" in block_text
        if not (has_date_hint or has_news_hint):
            continue

        seen_links.add(link)
        candidates.append(item)

    return candidates


def _collect_blocks_hearings(root: Tag, section_key: str) -> List[Dict[str, str]]:
    """
    Hearings：
    条目通常是 hearing 卡片/列表块。
    允许列表页拿不到完整日期，后续回退详情页。
    """
    candidates: List[Dict[str, str]] = []
    seen_links: Set[str] = set()

    block_tags = root.find_all(["article", "li", "div", "section"], recursive=True)
    for block in block_tags:
        item = _extract_candidate_from_block(block, section_key)
        if not item:
            continue

        link = item["link"]
        title = item["title"]

        if link in seen_links:
            continue
        if is_bad_title(title):
            continue

        text = clean_text(block.get_text(" ", strip=True)).lower()

        # hearing 块常出现月份缩写 + 时间 / hearing/business meeting 等
        looks_like_hearing = any(
            kw in text
            for kw in [
                "hearing",
                "business meeting",
                "legislative presentation",
                "markup",
                "oversight",
                "nomination",
                "roundtable",
                "press conference",
            ]
        ) or bool(re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b", text))

        if not looks_like_hearing:
            continue

        seen_links.add(link)
        candidates.append(item)

    return candidates


def collect_detail_links(soup: BeautifulSoup, section_key: str) -> List[Dict[str, str]]:
    """
    收集列表页候选条目，返回：
    [
        {
            "title": "...",
            "link": "...",
            "date_text": "...",   # 若列表页能读到日期，则这里包含块文本；否则空
        }
    ]
    """
    root = _find_content_root(soup, section_key)

    if section_key in {"majority_news", "minority_news"}:
        candidates = _collect_blocks_majority_or_minority(root, section_key)
    else:
        candidates = _collect_blocks_hearings(root, section_key)

    # 去重并保持顺序
    deduped: List[Dict[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for item in candidates:
        key = (item["link"], item["title"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def _within_last_10_days(dt: datetime) -> bool:
    today = datetime.now().date()
    cutoff = today - timedelta(days=10)
    return dt.date() >= cutoff


def _format_date_fields(dt: datetime) -> Tuple[str, str]:
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y/%m/%d")


def scrape_section(section_key: str, session: Optional[requests.Session] = None) -> List[Dict]:
    """
    抓取单个栏目。
    """
    conf = SECTION_CONFIG[section_key]
    label = conf["label"]
    base_url = conf["base_url"]

    sess = session or requests.Session()
    results: List[Dict] = []
    dedup_keys: Set[Tuple[str, str, str]] = set()

    consecutive_old = 0
    no_new_pages = 0
    max_pages = 200  # 保险上限，实际会被规则提前停止

    for page in range(1, max_pages + 1):
        page_url = _build_page_url(base_url, page)
        soup = fetch(page_url, session=sess)
        if not soup:
            print(f"[{label}] 第 {page} 页抓取失败，停止当前分类")
            break

        candidates = collect_detail_links(soup, section_key)
        candidate_count = len(candidates)

        if candidate_count == 0:
            print(f"[{label}] 第 {page} 页无候选链接，停止当前分类")
            break

        print(f"[{label}] 第 {page} 页候选链接: {candidate_count} | {page_url}")

        page_new_count = 0

        for item in candidates:
            list_title = clean_text(item.get("title", ""))
            link = normalize_link(item.get("link", ""))

            if not list_title or not link:
                continue

            # 先尝试列表页日期
            dt = parse_date(item.get("date_text", ""))

            detail_soup: Optional[BeautifulSoup] = None

            # 若列表页无日期，再进详情页取
            if dt is None:
                detail_soup = fetch(link, session=sess)
                if not detail_soup:
                    print(f"跳过(详情页抓取失败): {list_title}")
                    continue
                dt = extract_date_from_soup(detail_soup)
                if dt is None:
                    print(f"跳过(列表页无日期): {list_title}")
                    continue

            if not _within_last_10_days(dt):
                print(f"跳过(超出最近10天): {list_title}")
                consecutive_old += 1
                if consecutive_old >= 5:
                    print("连续跳过达到5条，停止当前分类")
                    return results
                continue

            # 只要出现一条有效近10天数据，就重置旧数据计数
            consecutive_old = 0

            date_str, sort_date = _format_date_fields(dt)
            dedup_key = (link, list_title, date_str)
            if dedup_key in dedup_keys:
                continue

            if detail_soup is None:
                detail_soup = fetch(link, session=sess)

            detail_title = extract_title(detail_soup) if detail_soup else ""
            title = list_title or detail_title
            if not title:
                print(f"跳过(无标题): {link}")
                continue

            summary = extract_summary(detail_soup, max_len=200) if detail_soup else ""
            summary = summary[:200]

            record = {
                "committee_en": COMMITTEE_EN,
                "committee_zh": COMMITTEE_ZH,
                "chamber": CHAMBER,
                "category_en": conf["category_en"],
                "category": conf["category"],
                "title": title,
                "summary": summary,
                "date": date_str,
                "sort_date": sort_date,
                "link": link,
                "party": conf["party"],
            }

            results.append(record)
            dedup_keys.add(dedup_key)
            page_new_count += 1

            time.sleep(0.2)

        if page_new_count == 0:
            print(f"[{label}] 第 {page} 页没有新增有效数据")
            no_new_pages += 1
            if no_new_pages >= 5:
                print(f"[{label}] 连续5页没有新增有效数据，停止当前分类")
                break
        else:
            no_new_pages = 0

    return results


def run_committee() -> List[Dict]:
    """
    运行整个委员会抓取。
    """
    all_results: List[Dict] = []
    session = requests.Session()

    print("====== Majority News ======")
    all_results.extend(scrape_section("majority_news", session=session))

    print("\n====== Minority News ======")
    all_results.extend(scrape_section("minority_news", session=session))

    print("\n====== Hearing ======")
    all_results.extend(scrape_section("hearings", session=session))

    # 最终去重：link + title + date
    final_results: List[Dict] = []
    seen: Set[Tuple[str, str, str]] = set()

    for item in all_results:
        key = (item["link"], item["title"], item["date"])
        if key in seen:
            continue
        seen.add(key)
        final_results.append(item)

    print(f"\ntotal: {len(final_results)}")
    return final_results


if __name__ == "__main__":
    data = run_committee()
    for row in data:
        print(row)