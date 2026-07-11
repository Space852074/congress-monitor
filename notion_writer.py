# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import time
import hashlib
from functools import lru_cache
from pathlib import Path

import requests

from committee_translate import get_committee_cn, get_committee_en


def _load_local_env() -> None:
    """Load credentials from config.local.env beside the script or executable."""
    root = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    config_path = root / "config.local.env"
    if not config_path.is_file():
        return

    for raw_line in config_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


_load_local_env()
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "").strip()
DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "").strip()

print("🔍 NOTION_DATABASE_ID =", DATABASE_ID)
print("🔍 NOTION_TOKEN =", "已设置" if NOTION_TOKEN else "未设置")

if not DATABASE_ID:
    raise ValueError("❌ NOTION_DATABASE_ID 未设置")
if not NOTION_TOKEN:
    raise ValueError("❌ NOTION_TOKEN 未设置")


HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# 运行期缓存，避免每条数据都去重新扫描整个数据库
_EXISTING_LINKS_CACHE = None
_EXISTING_KEYS_CACHE = None


def _safe_text(value):
    return (value or "").strip()


def _normalize_name(name: str) -> str:
    return "".join(
        (name or "")
        .lower()
        .replace(" ", "")
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .split()
    )


def _norm_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _request(method: str, url: str, **kwargs):
    last_error = None
    for i in range(4):
        try:
            r = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(min(2 ** i, 8))
                continue
            return r
        except Exception as e:
            last_error = e
            time.sleep(min(2 ** i, 8))
    if last_error:
        raise last_error
    raise RuntimeError("Notion request failed")


@lru_cache(maxsize=1)
def get_database_schema():
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}"
    r = _request("GET", url)
    r.raise_for_status()
    return r.json().get("properties", {})


def _find_property_name(schema: dict, aliases: list[str]):
    if not schema:
        return None
    for alias in aliases:
        if alias in schema:
            return alias
    normalized = {_normalize_name(k): k for k in schema.keys()}
    for alias in aliases:
        hit = normalized.get(_normalize_name(alias))
        if hit:
            return hit
    return None


def _build_property_value(prop_type: str, value: str):
    value = _safe_text(value)

    if prop_type == "title":
        return {"title": [{"type": "text", "text": {"content": value[:2000]}}]}

    if prop_type == "rich_text":
        return {"rich_text": [{"type": "text", "text": {"content": value[:2000]}}]}

    if prop_type == "url":
        return {"url": value or None}

    if prop_type == "date":
        return {"date": {"start": value.replace("/", "-")} if value else None}

    if prop_type == "select":
        return {"select": {"name": value} if value else None}

    if prop_type == "multi_select":
        parts = [x.strip() for x in value.split(",") if x.strip()]
        return {"multi_select": [{"name": x} for x in parts]}

    if prop_type == "number":
        try:
            return {"number": float(value)}
        except Exception:
            return {"number": None}

    if prop_type == "checkbox":
        return {"checkbox": value.lower() in {"1", "true", "yes", "y"}}

    return None


def _get_plain_value(prop: dict) -> str:
    typ = prop.get("type")

    if typ == "title":
        arr = prop.get("title") or []
        return "".join(x.get("plain_text", "") for x in arr).strip()

    if typ == "rich_text":
        arr = prop.get("rich_text") or []
        return "".join(x.get("plain_text", "") for x in arr).strip()

    if typ == "select":
        sel = prop.get("select")
        return (sel or {}).get("name", "") if sel else ""

    if typ == "multi_select":
        arr = prop.get("multi_select") or []
        return ",".join(x.get("name", "") for x in arr if x.get("name"))

    if typ == "date":
        dt = prop.get("date")
        return (dt or {}).get("start", "") if dt else ""

    if typ == "url":
        return prop.get("url") or ""

    if typ == "number":
        num = prop.get("number")
        return "" if num is None else str(num)

    if typ == "checkbox":
        return "true" if prop.get("checkbox") else "false"

    return ""


def build_unique_key(item: dict, committee_cn: str = "", committee_en: str = "") -> str:
    """
    稳定唯一键：
    日期 + 委员会 + 分类 + 标题 + 链接
    """
    date_val = _safe_text(item.get("sort_date") or item.get("date"))
    title_val = _safe_text(item.get("title"))
    category_val = _safe_text(item.get("category"))
    link_val = _safe_text(item.get("link"))
    committee_val = (
        committee_en
        or committee_cn
        or _safe_text(item.get("committee_en"))
        or _safe_text(item.get("committee_cn"))
        or _safe_text(item.get("committee"))
    )

    raw = f"{date_val}|{committee_val}|{category_val}|{title_val}|{link_val}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _build_existing_item_key_from_props(props: dict, matched: dict) -> str:
    title_val = _norm_text(_get_plain_value(props.get(matched.get("title") or "", {})))
    date_val = _norm_text(
        _get_plain_value(props.get(matched.get("sort_date") or "", {}))
        or _get_plain_value(props.get(matched.get("date") or "", {}))
    )
    committee_val = _norm_text(
        _get_plain_value(props.get(matched.get("committee_en") or "", {}))
        or _get_plain_value(props.get(matched.get("committee_cn") or "", {}))
    )
    category_val = _norm_text(_get_plain_value(props.get(matched.get("category") or "", {})))
    link_val = _norm_text(_get_plain_value(props.get(matched.get("link") or "", {})))

    return f"{date_val}|{committee_val}|{category_val}|{title_val}|{link_val}"


def get_existing_links():
    schema = get_database_schema()
    link_name = _find_property_name(schema, ["Link", "链接", "URL", "Url"])
    if not link_name:
        return set()

    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    existing_links = set()
    next_cursor = None
    has_more = True

    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        r = _request("POST", url, json=payload)
        r.raise_for_status()
        data = r.json()

        for row in data.get("results", []):
            props = row.get("properties", {})
            prop = props.get(link_name, {})
            if prop.get("type") == "url" and prop.get("url"):
                existing_links.add(prop["url"].strip())

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return existing_links


def get_existing_item_keys():
    schema = get_database_schema()

    aliases = {
        "title": ["Title", "标题"],
        "date": ["Date", "日期"],
        "sort_date": ["SortDate", "Sort Date", "排序日期"],
        "committee_cn": ["CN/Committee", "CNCommittee", "CN(Committee)", "中文委员会名", "Committee"],
        "committee_en": ["EN/Committee", "ENCommittee", "EN(Committee)", "英文委员会名"],
        "category": ["Category", "分类"],
        "link": ["Link", "链接", "URL", "Url"],
        "unique_key": ["UniqueKey", "Unique Key", "唯一键"],
    }

    matched = {k: _find_property_name(schema, v) for k, v in aliases.items()}

    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    existing_keys = set()
    next_cursor = None
    has_more = True

    while has_more:
        payload = {}
        if next_cursor:
            payload["start_cursor"] = next_cursor

        r = _request("POST", url, json=payload)
        r.raise_for_status()
        data = r.json()

        for row in data.get("results", []):
            props = row.get("properties", {})

            unique_key_prop_name = matched.get("unique_key")
            if unique_key_prop_name and unique_key_prop_name in props:
                direct_key = _norm_text(_get_plain_value(props.get(unique_key_prop_name, {})))
                if direct_key:
                    existing_keys.add(direct_key)
                    continue

            fallback_key = _build_existing_item_key_from_props(props, matched)
            if fallback_key and fallback_key != "||||":
                existing_keys.add(_norm_text(fallback_key))

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    return existing_keys


def reset_notion_cache():
    """
    如果你在同一进程内切换数据库，或者手动改过数据库内容后想强制重新加载缓存，可调用这个函数。
    """
    global _EXISTING_LINKS_CACHE, _EXISTING_KEYS_CACHE
    _EXISTING_LINKS_CACHE = None
    _EXISTING_KEYS_CACHE = None
    get_database_schema.cache_clear()


def add_news(item):
    global _EXISTING_LINKS_CACHE, _EXISTING_KEYS_CACHE

    schema = get_database_schema()

    committee_raw = _safe_text(item.get("committee"))
    chamber = _safe_text(item.get("chamber"))
    committee_cn = _safe_text(item.get("committee_cn")) or get_committee_cn(committee_raw, chamber=chamber)
    committee_en = _safe_text(item.get("committee_en")) or get_committee_en(committee_raw, chamber=chamber)

    # 第一次写入前，先全量读一次 Notion 现有数据
    if _EXISTING_LINKS_CACHE is None:
        _EXISTING_LINKS_CACHE = get_existing_links()
        print(f"📚 已加载 Notion Link 数量: {len(_EXISTING_LINKS_CACHE)}")

    if _EXISTING_KEYS_CACHE is None:
        _EXISTING_KEYS_CACHE = get_existing_item_keys()
        print(f"🧩 已加载 Notion Key 数量: {len(_EXISTING_KEYS_CACHE)}")

    aliases = {
        "title": ["Title", "标题"],
        "date": ["Date", "日期"],
        "sort_date": ["SortDate", "Sort Date", "排序日期"],
        "committee_cn": ["CN/Committee", "CNCommittee", "CN(Committee)", "中文委员会名", "Committee"],
        "committee_en": ["EN/Committee", "ENCommittee", "EN(Committee)", "英文委员会名"],
        "category": ["Category", "分类"],
        "summary": ["Summary", "摘要"],
        "link": ["Link", "链接", "URL", "Url"],
        "chamber": ["Senate / House", "Senate/House", "Chamber", "院别"],
        "unique_key": ["UniqueKey", "Unique Key", "唯一键"],
    }

    matched = {k: _find_property_name(schema, v) for k, v in aliases.items()}

    title_value = _safe_text(item.get("title"))
    date_value = _safe_text(item.get("date"))
    sort_date_value = _safe_text(item.get("sort_date"))
    category_value = _safe_text(item.get("category"))
    summary_value = _safe_text(item.get("summary"))
    link_value = _safe_text(item.get("link"))

    unique_key_value = _safe_text(item.get("unique_key")) or build_unique_key(
        item,
        committee_cn=committee_cn,
        committee_en=committee_en,
    )

    # 兜底组合键，防止数据库中没有 UniqueKey 字段，仍能查重
    fallback_key = _norm_text(
        f"{sort_date_value or date_value}|{committee_en or committee_cn}|{category_value}|{title_value}|{link_value}"
    )

    # 第一层：Link 去重
    if link_value and link_value in _EXISTING_LINKS_CACHE:
        print(f"跳过(Notion已存在Link): {title_value}")
        return {"skipped": True, "reason": "existing_link", "link": link_value}

    # 第二层：UniqueKey 去重
    if unique_key_value and _norm_text(unique_key_value) in _EXISTING_KEYS_CACHE:
        print(f"跳过(Notion已存在UniqueKey): {title_value}")
        return {"skipped": True, "reason": "existing_unique_key", "unique_key": unique_key_value}

    # 第三层：组合字段兜底去重
    if fallback_key and fallback_key in _EXISTING_KEYS_CACHE:
        print(f"跳过(Notion已存在组合键): {title_value}")
        return {"skipped": True, "reason": "existing_fallback_key", "fallback_key": fallback_key}

    values = {
        "title": title_value,
        "date": sort_date_value or date_value,
        "sort_date": sort_date_value,
        "committee_cn": committee_cn,
        "committee_en": committee_en,
        "category": category_value,
        "summary": summary_value,
        "link": link_value,
        "chamber": chamber,
        "unique_key": unique_key_value,
    }

    properties = {}
    for key, prop_name in matched.items():
        if not prop_name:
            continue
        value = _build_property_value(schema[prop_name]["type"], values[key])
        if value is not None:
            properties[prop_name] = value

    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": properties,
    }

    url = "https://api.notion.com/v1/pages"
    r = _request("POST", url, json=payload)
    r.raise_for_status()
    resp = r.json()

    # 写入成功后，立刻加入缓存，防止本轮重复写入
    if link_value:
        _EXISTING_LINKS_CACHE.add(link_value)

    if unique_key_value:
        _EXISTING_KEYS_CACHE.add(_norm_text(unique_key_value))

    if fallback_key:
        _EXISTING_KEYS_CACHE.add(fallback_key)

    print(f"✅ 写入成功: {title_value}")
    return resp


if __name__ == "__main__":
    print("notion_writer.py 已加载，可由其他爬虫脚本 import 后调用 add_news(item)")
