# -*- coding: utf-8 -*-
from __future__ import annotations

from core.scraper_cms import run_cms_scraper

CONFIG = {
    "committee_en": "House Judiciary Committee",
    "committee_zh": "美国众议院司法委员会",
    "chamber": "House",
    "base_url": "https://judiciary.house.gov",
    "sections": [
        {
            "key": "hearings",
            "category_en": "Hearing",
            "category_zh": "听证会",
            "list_url": "https://judiciary.house.gov/committee-activity/hearings",
            "detail_path_prefixes": [
                "/committee-activity/hearings/",
            ],
            "blocked_paths": {
                "/committee-activity/hearings",
                "/committee-activity/hearings/",
            },
        },
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://judiciary.house.gov/media/press-releases",
            "detail_path_prefixes": [
                "/media/press-releases/",
            ],
            "blocked_paths": {
                "/media/press-releases",
                "/media/press-releases/",
            },
        },
        {
            "key": "in_the_news",
            "category_en": "In the News",
            "category_zh": "媒体转载",
            "list_url": "https://judiciary.house.gov/media/in-the-news",
            "detail_path_prefixes": [
                "/media/in-the-news/",
            ],
            "blocked_paths": {
                "/media/in-the-news",
                "/media/in-the-news/",
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
        print("1. detail_path_prefixes 是否匹配真实详情页路径")
        print("2. scraper_cms.py 的 TIME_WINDOW_DAYS 是否过小")
        print("3. hearings / press / in-the-news 是否存在特殊分页参数")

    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))