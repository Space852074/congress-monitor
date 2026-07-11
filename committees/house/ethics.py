# -*- coding: utf-8 -*-
from __future__ import annotations

from core.scraper_cms import run_cms_scraper

CONFIG = {
    "committee_en": "House Ethics Committee",
    "committee_zh": "美国众议院道德委员会",
    "chamber": "House",
    "base_url": "https://ethics.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://ethics.house.gov/press-releases/",
            "detail_path_prefixes": [
                "/press-releases/",
            ],
            "blocked_paths": {
                "/press-releases",
                "/press-releases/",
            },
        },
    ],
}


def run_committee(existing_links=None):
    return run_cms_scraper(CONFIG, existing_links or set())


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")

    if not data:
        print("⚠️ 没有抓到数据，请优先检查：")
        print("1. ethics 站点详情页是否都在 /press-releases/ 下")
        print("2. scraper_cms.py 的日期提取是否命中")
        print("3. 该站后续分页是否依赖 Load More 异步加载")

    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))