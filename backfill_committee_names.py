# -*- coding: utf-8 -*-
"""Backfill English committee names already stored in Notion."""
from __future__ import annotations

import argparse
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import notion_writer
from committee_translate import get_committee_cn


def has_ascii(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 Notion 中的中文委员会名称")
    parser.add_argument("--apply", action="store_true", help="实际写入 Notion；默认仅预览")
    parser.add_argument("--start-cursor", default="", help="从指定 Notion 分页游标继续")
    parser.add_argument("--max-pages", type=int, default=0, help="本批最多读取页数；0 表示不限制")
    parser.add_argument("--max-updates", type=int, default=0, help="本批最多写入条数；0 表示不限制")
    args = parser.parse_args()

    schema = notion_writer.get_database_schema()
    cn_name = notion_writer._find_property_name(schema, ["CN/Committee", "CNCommittee", "CN(Committee)", "中文委员会名", "Committee"])
    en_name = notion_writer._find_property_name(schema, ["EN/Committee", "ENCommittee", "EN(Committee)", "英文委员会名"])
    chamber_name = notion_writer._find_property_name(schema, ["Senate / House", "Senate/House", "Chamber", "院别"])
    if not cn_name or not en_name:
        raise RuntimeError("Notion 数据库缺少中英文委员会字段")

    url = f"https://api.notion.com/v1/databases/{notion_writer.DATABASE_ID}/query"
    cursor = args.start_cursor or None
    candidates: list[tuple[str, str]] = []
    page_count = 0
    has_more = False
    print("开始读取 Notion 记录...")
    while True:
        payload = {"sorts": [{"timestamp": "created_time", "direction": "descending"}]}
        if cursor:
            payload["start_cursor"] = cursor
        response = notion_writer._request("POST", url, json=payload)
        response.raise_for_status()
        data = response.json()
        page_count += 1
        if page_count % 10 == 0:
            print(f"已读取 {page_count} 页...")
        for row in data.get("results", []):
            props = row.get("properties", {})
            current = notion_writer._get_plain_value(props.get(cn_name, {}))
            english = notion_writer._get_plain_value(props.get(en_name, {}))
            chamber = notion_writer._get_plain_value(props.get(chamber_name, {})) if chamber_name else ""
            translated = get_committee_cn(english, chamber=chamber)
            if has_ascii(current) and translated and not has_ascii(translated) and translated != current:
                candidates.append((row["id"], translated))
        has_more = bool(data.get("has_more"))
        cursor = data.get("next_cursor")
        if not has_more or (args.max_pages and page_count >= args.max_pages):
            break

    print(f"已读取 {page_count} 页；待回填中文委员会名称: {len(candidates)}")
    if has_more and cursor:
        print(f"下一批游标: {cursor}")
    if not args.apply:
        print("预览完成。使用 --apply 才会写入 Notion。")
        return 0

    if args.max_updates:
        candidates = candidates[:args.max_updates]

    prop_type = schema[cn_name]["type"]
    for page_id, translated in candidates:
        response = notion_writer._request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            json={"properties": {cn_name: notion_writer._build_property_value(prop_type, translated)}},
        )
        response.raise_for_status()
    print(f"已回填: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
