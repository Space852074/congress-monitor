# -*- coding: utf-8 -*-
"""Preview or archive exact cross-source hearing duplicates in Notion."""
from __future__ import annotations

import argparse
from urllib.parse import urlparse

import notion_writer
from optimized_pipeline import build_item_key


def plain(properties: dict, name: str) -> str:
    return notion_writer._get_plain_value(properties.get(name, {}))


def source_priority(link: str) -> int:
    parsed = urlparse(link or "")
    host = parsed.netloc.lower().replace("www.", "")
    path = parsed.path.lower()
    if host == "docs.house.gov":
        return 1
    if host == "house.gov" and path.startswith("/legislative-activity"):
        return 2
    if host == "senate.gov" and path.startswith("/committees/"):
        return 2
    return 0


def original_title(properties: dict) -> str:
    unique_key = plain(properties, "UniqueKey")
    if unique_key.startswith("hearing|"):
        parts = unique_key.split("|", 3)
        return parts[3] if len(parts) == 4 else ""
    parts = unique_key.split("|", 3)
    if len(parts) == 4:
        return parts[3]
    return plain(properties, "Title")


def merge_source_links(survivor: dict, duplicates: list[dict]) -> None:
    """Keep the original summary and append only previously missing source links."""
    summary = survivor.get("summary", "").strip()
    known_links = {survivor.get("link", "").strip()}
    additions: list[str] = []
    for duplicate in duplicates:
        link = duplicate.get("link", "").strip()
        if not link or link in known_links or link in summary:
            continue
        known_links.add(link)
        additions.append(f"Additional source link: {link}")
    if additions:
        summary = "\n".join(part for part in [summary, *additions] if part)
    survivor["summary"] = summary[:2000]


def load_hearings() -> list[dict]:
    url = f"https://api.notion.com/v1/databases/{notion_writer.DATABASE_ID}/query"
    cursor = None
    rows: list[dict] = []
    page_count = 0
    while True:
        payload: dict = {
            "filter": {
                "or": [
                    {"property": "Category", "rich_text": {"contains": "听证"}},
                    {"property": "Category", "rich_text": {"contains": "Hearing"}},
                ]
            }
        }
        if cursor:
            payload["start_cursor"] = cursor
        response = notion_writer._request("POST", url, json=payload)
        response.raise_for_status()
        data = response.json()
        rows.extend(data.get("results", []))
        page_count += 1
        if page_count % 5 == 0:
            print(f"已读取 {page_count} 页听证会记录...")
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def canonical_record(row: dict) -> dict | None:
    properties = row.get("properties", {})
    item = {
        "sort_date": plain(properties, "SortDate") or plain(properties, "Date"),
        "committee_en": plain(properties, "EN/Committee"),
        "committee_cn": plain(properties, "CN/Committee"),
        "category_en": "Hearing",
        "category": plain(properties, "Category") or "听证会",
        "title": original_title(properties),
        "summary": plain(properties, "Summary"),
        "link": plain(properties, "Link"),
    }
    key = build_item_key(item)
    if not key.startswith("hearing|"):
        return None
    item.update(
        {
            "page_id": row["id"],
            "page_title": plain(properties, "Title"),
            "old_key": plain(properties, "UniqueKey"),
            "new_key": key,
        }
    )
    return item


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 Notion 中跨来源重复听证会")
    parser.add_argument("--apply", action="store_true", help="更新事件键并归档重复页")
    args = parser.parse_args()

    records = [record for row in load_hearings() if (record := canonical_record(row))]
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record["new_key"], []).append(record)

    duplicate_groups = [group for group in groups.values() if len(group) > 1]
    key_updates = sum(record["old_key"] != record["new_key"] for record in records)
    duplicates = sum(len(group) - 1 for group in duplicate_groups)
    print(f"听证会记录: {len(records)}")
    print(f"需更新稳定事件键: {key_updates}")
    print(f"完全匹配的重复组: {len(duplicate_groups)}；重复页: {duplicates}")

    for group in duplicate_groups:
        group.sort(key=lambda record: source_priority(record["link"]))
        print(f"\n保留: {group[0]['page_title']} | {group[0]['link']}")
        for duplicate in group[1:]:
            print(f"归档: {duplicate['page_title']} | {duplicate['link']}")

    if not args.apply:
        print("\n预览完成；未修改 Notion。")
        return 0

    for group in groups.values():
        group.sort(key=lambda record: source_priority(record["link"]))
        survivor = group[0]
        merge_source_links(survivor, group[1:])

        properties = {
            "UniqueKey": notion_writer._build_property_value("rich_text", survivor["new_key"]),
        }
        if survivor["summary"]:
            properties["Summary"] = notion_writer._build_property_value("rich_text", survivor["summary"])
        response = notion_writer._request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{survivor['page_id']}",
            json={"properties": properties},
        )
        response.raise_for_status()

        for duplicate in group[1:]:
            response = notion_writer._request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{duplicate['page_id']}",
                json={"archived": True},
            )
            response.raise_for_status()

    print(f"已归档重复页: {duplicates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
