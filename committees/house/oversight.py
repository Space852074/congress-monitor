# -*- coding: utf-8 -*-
from __future__ import annotations

from core.scraper_cms import run_cms_scraper

CONFIG = {
    "committee_en": "House Oversight Committee",
    "committee_zh": "美国众议院监督与问责委员会",
    "chamber": "House",
    "base_url": "https://oversight.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://oversight.house.gov/release/",
            "detail_path_prefixes": [
                "/release/",
            ],
            "blocked_paths": {
                "/release",
                "/release/",
            },
        },
    ],
}


def run_committee(existing_links=None):
    return run_cms_scraper(CONFIG, existing_links or set())


if __name__ == "__main__":
    data = run_committee()
    print("\n====================")
    print(f"抓取到 {len(data)} 条")
    for row in data:
        print(f"[{row['sort_date']}] {row['category']} | {row['title']}")
        print(row["link"])