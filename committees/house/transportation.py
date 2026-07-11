# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.scraper_asp import run_asp_scraper

CONFIG = {
    "committee_en": "House Transportation and Infrastructure Committee",
    "committee_zh": "美国众议院交通与基础设施委员会",
    "chamber": "House",
    "base_url": "https://transportation.house.gov",
    "sections": [
        {
            "key": "press_releases",
            "category_en": "Press Release",
            "category_zh": "新闻稿",
            "list_url": "https://transportation.house.gov/news/documentquery.aspx?DocumentTypeID=2545",
            "detail_patterns": [
                "documentsingle.aspx?DocumentID=",
            ],
        },
    ],
}


def run_committee(existing_links=None):
    return run_asp_scraper(CONFIG, existing_links or set())


if __name__ == "__main__":
    data = run_committee(existing_links=set())

    print("\n====================")
    print(f"抓取到 {len(data)} 条")

    for row in data:
        print(f"[{row.get('sort_date', '')}] {row.get('category', '')} | {row.get('title', '')}")
        print(row.get("link", ""))