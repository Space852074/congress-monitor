# -*- coding: utf-8 -*-
from __future__ import annotations

from core.scraper_cms import run_cms_scraper

CONFIG = {
    "committee_en": "House Budget Committee",
    "committee_zh": "美国众议院预算委员会",
    "chamber": "House",
    "base_url": "https://budget.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://budget.house.gov/news/press-releases",
            "detail_path_prefixes": [
                "/press-release/",
                "/news/press-releases/",
            ],
            "blocked_paths": {
                "/news",
                "/news/press-releases",
                "/news/press-releases/",
            },
        },
        {
            "key": "icymi",
            "category_en": "ICYMI",
            "category_zh": "媒体转载",
            "list_url": "https://budget.house.gov/news/icymi",
            "detail_path_prefixes": [
                "/press-release/",
                "/news/press-releases/",
            ],
            "blocked_paths": {
                "/news",
                "/news/icymi",
                "/news/icymi/",
            },
        },
        {
            "key": "op_eds_speeches",
            "category_en": "Op-Ed / Speech",
            "category_zh": "评论文章/讲话",
            "list_url": "https://budget.house.gov/news/op-eds-and-speeches",
            "detail_path_prefixes": [
                "/press-release/",
                "/news/press-releases/",
                "/speech/",
            ],
            "blocked_paths": {
                "/news",
                "/news/op-eds-and-speeches",
                "/news/op-eds-and-speeches/",
            },
        },
        {
            "key": "hearings",
            "category_en": "Hearing",
            "category_zh": "听证会",
            "list_url": "https://budget.house.gov/hearings",
            "detail_path_prefixes": [
                "/hearing/",
            ],
            "blocked_paths": {
                "/hearings",
                "/hearings/",
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
        print("3. hearings 栏目详情页是否都统一落在 /hearing/ 下")

    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))