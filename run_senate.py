# -*- coding: utf-8 -*-
from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from notion_writer import (
    add_news,
    get_existing_item_keys,
    get_existing_links,
)
from logger_utils import log_start, log_success, log_failure
from translator import translate_text, translate_summary_if_needed

# ===== 已接入的 Senate 委员会 =====
from committees.senate.agriculture import run_committee as agriculture_committee
from committees.senate.appropriations import run_committee as appropriations_committee
from committees.senate.armedservices import run_committee as armedservices_committee
from committees.senate.banking import run_committee as banking_committee
from committees.senate.budget import run_committee as budget_committee
from committees.senate.commerce import run_committee as commerce_committee
from committees.senate.energy import run_committee as energy_committee
from committees.senate.epw import run_committee as epw_committee
from committees.senate.finance import run_committee as finance_committee
from committees.senate.foreign import run_committee as foreign_committee
from committees.senate.help import run_committee as help_committee
from committees.senate.hsgac import run_committee as hsgac_committee
from committees.senate.intelligence import run_committee as intelligence_committee
from committees.senate.judiciary import run_committee as judiciary_committee
from committees.senate.rules import run_committee as rules_committee
from committees.senate.sbc import run_committee as sbc_committee
from committees.senate.aging import run_committee as aging_committee
from committees.senate.veterans import run_committee as veterans_committee


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def norm_text(v: str) -> str:
    return " ".join((v or "").strip().lower().split())


def build_item_key(item: dict) -> str:
    date = norm_text(item.get("sort_date") or item.get("date") or "")
    title = norm_text(item.get("title") or "")
    committee = norm_text(
        item.get("committee_en")
        or item.get("committee_cn")
        or item.get("committee_zh")
        or item.get("committee")
        or ""
    )
    category = norm_text(item.get("category_en") or item.get("category") or "")
    return f"{date}|{committee}|{category}|{title}"


def format_output_fields(item: dict) -> dict:
    def strip_committee_prefix(value: str) -> str:
        value = (value or "").strip()
        prefixes = ["美国", "参议院", "众议院"]
        changed = True
        while changed and value:
            changed = False
            for prefix in prefixes:
                if value.startswith(prefix):
                    value = value[len(prefix):].strip()
                    changed = True
        return value

    chamber = (item.get("chamber") or "").strip()
    if chamber == "House":
        item["chamber"] = "🟡众议院"
    elif chamber == "Senate":
        item["chamber"] = "🟢参议院"

    committee_cn = (
        item.get("committee_cn")
        or item.get("committee_zh")
        or item.get("committee")
        or ""
    )
    item["committee_cn"] = strip_committee_prefix(committee_cn)

    party = (item.get("party") or "").strip()
    if party in ("共和党", "Republican"):
        item["party"] = "🛑共和党"
    elif party in ("民主党", "Democratic"):
        item["party"] = "⭕️民主党"

    category = (item.get("category") or "").strip()
    if category:
        for sep in ("（", "("):
            if sep in category:
                category = category.split(sep, 1)[0].strip()
                break

    category_map = {
        "新闻稿": "🟦新闻稿",
        "听证会": "🟪听证会",
        "会议": "🟧会议",
        "商务会议": "🟫会议",
        "业务会议": "🟫会议",
        "审议会议": "🟧审议会议",
        "讲话": "🟩讲话",
        "报告": "🟥报告",
        "委员会报告": "🟥报告",
        "开场陈述": "🟥开场陈述",
        "视频": "🎥视频",
        "媒体转载": "📰媒体转载",
        "法案": "📜法案",
        "立法": "📜法案",
        "信函": "✉️信函",
        "少数党新闻稿": "⭕️新闻稿",
        "多数党新闻稿": "🛑新闻稿",
        "民主党新闻": "⭕️新闻稿",
        "共和党新闻": "🛑新闻稿",
        "民主党新闻稿": "⭕️新闻稿",
        "共和党新闻稿": "🛑新闻稿",
        "提名": "👤提名",
        "条约": "📘条约",
    }

    if category:
        item["category"] = category_map.get(category, category)

    return item


def translate_item(item: dict) -> dict:
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()

    if title:
        try:
            item["title"] = translate_text(title)
        except Exception as e:
            print(f"标题翻译失败: {title} | {e}")

    if summary:
        try:
            summary_candidate = translate_summary_if_needed(summary)
            if summary_candidate:
                item["summary"] = translate_text(summary_candidate)
        except Exception as e:
            print(f"摘要翻译失败: {title} | {e}")

    return item


def safe_run_committee(func, existing_links: set[str]) -> list[dict]:
    """
    兼容两种 run_committee 写法：
    1. run_committee(existing_links=...)
    2. run_committee()
    """
    try:
        return func(existing_links=existing_links)
    except TypeError as e:
        if "unexpected keyword argument 'existing_links'" in str(e):
            return func()
        raise


def main():
    log_start("开始执行 Senate Committees → Notion")

    try:
        notion_existing_links_raw = get_existing_links()
        notion_existing_links = {
            normalize_link(x) for x in notion_existing_links_raw if (x or "").strip()
        }

        notion_existing_keys = set(get_existing_item_keys())

        print(f"Notion 已有链接数量: {len(notion_existing_links)}")
        print(f"Notion 已有 UniqueKey 数量: {len(notion_existing_keys)}")

        all_items: list[dict] = []

        committees = [
            ("Agriculture Committee", agriculture_committee),
            ("Appropriations Committee", appropriations_committee),
            ("Armed Services Committee", armedservices_committee),
            ("Banking Committee", banking_committee),
            ("Budget Committee", budget_committee),
            ("Commerce Committee", commerce_committee),
            ("Energy Committee", energy_committee),
            ("EPW Committee", epw_committee),
            ("Finance Committee", finance_committee),
            ("Foreign Committee", foreign_committee),
            ("Help Committee", help_committee),
            ("HSGAC Committee", hsgac_committee),
            ("Intelligence Committee", intelligence_committee),
            ("Judiciary Committee", judiciary_committee),
            ("Rules Committee", rules_committee),
            ("SBC Committee", sbc_committee),
            ("Aging Committee", aging_committee),
            ("Veterans Committee", veterans_committee),
        ]

        for name, func in committees:
            print(f"\n========== {name} ==========")
            try:
                items = safe_run_committee(func, existing_links=notion_existing_links)
                print(f"{name} 抓取到 {len(items)} 条")
                all_items.extend(items)
            except Exception as e:
                print(f"❌ {name} 抓取失败: {e}")

        print(f"\n总抓取数量: {len(all_items)}")

        deduped_items: list[dict] = []
        seen_links_in_run: set[str] = set()
        seen_keys_in_run: set[str] = set()

        for item in all_items:
            if not isinstance(item, dict):
                continue

            raw_link = (item.get("link") or "").strip()
            norm_link = normalize_link(raw_link)
            item_key = build_item_key(item)
            item["unique_key"] = item_key

            if not norm_link:
                print(f"跳过(无链接): {item.get('title', '')}")
                continue

            if norm_link in notion_existing_links:
                print(f"跳过(Notion已存在Link): {raw_link}")
                continue

            if item_key in notion_existing_keys:
                print(f"跳过(Notion已存在UniqueKey): {item.get('title', '')}")
                continue

            if norm_link in seen_links_in_run:
                print(f"跳过(本轮link重复): {raw_link}")
                continue

            if item_key in seen_keys_in_run:
                print(f"跳过(本轮UniqueKey重复): {item.get('title', '')}")
                continue

            item["link"] = norm_link
            seen_links_in_run.add(norm_link)
            seen_keys_in_run.add(item_key)
            deduped_items.append(item)

        print(f"写入前去重后数量: {len(deduped_items)}")

        success = 0
        skipped = 0
        failed = 0

        for item in deduped_items:
            raw_link = (item.get("link") or "").strip()
            norm_link = normalize_link(raw_link)
            item_key = item.get("unique_key") or build_item_key(item)
            title = (item.get("title") or "").strip()

            if not norm_link:
                print(f"跳过(无链接): {title}")
                skipped += 1
                continue

            if norm_link in notion_existing_links:
                print(f"跳过(写入前再次命中Notion Link): {raw_link}")
                skipped += 1
                continue

            if item_key in notion_existing_keys:
                print(f"跳过(写入前再次命中Notion UniqueKey): {title}")
                skipped += 1
                continue

            try:
                item = translate_item(item)
                item = format_output_fields(item)
                item["unique_key"] = item_key

                add_news(item)

                notion_existing_links.add(norm_link)
                notion_existing_keys.add(item_key)

                success += 1
                print(f"✅ 写入成功: {title}")

            except Exception as e:
                failed += 1
                print(f"❌ 写入失败: {title} | {e}")

        print("\n====================")
        print(f"成功: {success}")
        print(f"跳过: {skipped}")
        print(f"失败: {failed}")

        log_success("Senate Committees 执行结束")

    except Exception as e:
        log_failure(e, "Senate Committees 执行失败")
        raise


if __name__ == "__main__":
    main()