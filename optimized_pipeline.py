# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import inspect
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable
from urllib.parse import urlparse, urlunparse


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import notion_writer
import run_house
import run_senate
from core.central_hearings import run_house_hearing_notices, run_senate_hearing_notices
from committees.house.science import run_committee as house_science_committee
from logger_utils import log_failure, log_start, log_success
from notion_writer import add_news, get_existing_item_keys, get_existing_links
from translator import translate_summary_if_needed, translate_text


DEFAULT_WORKERS = 6
TRANSLATION_RETRY_DELAY = 1.0
ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")
CJK_RE = re.compile(r"[\u3400-\u9fff]")


@dataclass(frozen=True)
class CommitteeTask:
    chamber: str
    name: str
    func: Callable[..., list[dict]]


HOUSE_TASKS: list[CommitteeTask] = [
    CommitteeTask("House", "China Committee", run_house.china_committee),
    CommitteeTask("House", "Appropriations Committee", run_house.appropriations_committee),
    CommitteeTask("House", "Foreign Affairs Committee", run_house.foreignaffairs_committee),
    CommitteeTask("House", "Armed Services Committee", run_house.armedservices_committee),
    CommitteeTask("House", "Agriculture Committee", run_house.agriculture_committee),
    CommitteeTask("House", "Energy and Commerce Committee", run_house.energycommerce_committee),
    CommitteeTask("House", "Financial Services Committee", run_house.financialservices_committee),
    CommitteeTask("House", "Homeland Security Committee", run_house.homeland_committee),
    CommitteeTask("House", "Budget Committee", run_house.budget_committee),
    CommitteeTask("House", "Education and Workforce Committee", run_house.edworkforce_committee),
    CommitteeTask("House", "Ethics Committee", run_house.ethics_committee),
    CommitteeTask("House", "House Administration Committee", run_house.cha_committee),
    CommitteeTask("House", "Judiciary Committee", run_house.judiciary_committee),
    CommitteeTask("House", "Natural Resources Committee", run_house.naturalresources_committee),
    CommitteeTask("House", "Oversight Committee", run_house.oversight_committee),
    CommitteeTask("House", "Rules Committee", run_house.rules_committee),
    CommitteeTask("House", "Science Committee", house_science_committee),
    CommitteeTask("House", "Small Business Committee", run_house.smallbusiness_committee),
    CommitteeTask("House", "Transportation Committee", run_house.transportation_committee),
    CommitteeTask("House", "Veterans Affairs Committee", run_house.veterans_committee),
    CommitteeTask("House", "Ways and Means Committee", run_house.waysandmeans_committee),
    CommitteeTask("House", "Intelligence Committee", run_house.intelligence_committee),
    CommitteeTask("House", "House Central Hearing Notices", run_house_hearing_notices),
]


SENATE_TASKS: list[CommitteeTask] = [
    CommitteeTask("Senate", "Agriculture Committee", run_senate.agriculture_committee),
    CommitteeTask("Senate", "Appropriations Committee", run_senate.appropriations_committee),
    CommitteeTask("Senate", "Armed Services Committee", run_senate.armedservices_committee),
    CommitteeTask("Senate", "Banking Committee", run_senate.banking_committee),
    CommitteeTask("Senate", "Budget Committee", run_senate.budget_committee),
    CommitteeTask("Senate", "Commerce Committee", run_senate.commerce_committee),
    CommitteeTask("Senate", "Energy Committee", run_senate.energy_committee),
    CommitteeTask("Senate", "EPW Committee", run_senate.epw_committee),
    CommitteeTask("Senate", "Finance Committee", run_senate.finance_committee),
    CommitteeTask("Senate", "Foreign Committee", run_senate.foreign_committee),
    CommitteeTask("Senate", "HELP Committee", run_senate.help_committee),
    CommitteeTask("Senate", "HSGAC Committee", run_senate.hsgac_committee),
    CommitteeTask("Senate", "Intelligence Committee", run_senate.intelligence_committee),
    CommitteeTask("Senate", "Judiciary Committee", run_senate.judiciary_committee),
    CommitteeTask("Senate", "Rules Committee", run_senate.rules_committee),
    CommitteeTask("Senate", "Small Business Committee", run_senate.sbc_committee),
    CommitteeTask("Senate", "Aging Committee", run_senate.aging_committee),
    CommitteeTask("Senate", "Veterans Committee", run_senate.veterans_committee),
    CommitteeTask("Senate", "Senate Central Hearing Notices", run_senate_hearing_notices),
]


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def norm_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def looks_untranslated(source: str, translated: str) -> bool:
    source = (source or "").strip()
    translated = (translated or "").strip()
    if not source or not translated:
        return False
    if CJK_RE.search(source) or CJK_RE.search(translated):
        return False
    if len(ASCII_WORD_RE.findall(source)) < 3:
        return False
    return norm_text(source) == norm_text(translated)


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


def is_hearing_item(item: dict) -> bool:
    category = norm_text(item.get("category_en") or item.get("category") or "")
    return "hearing" in category or "听证" in category


def normalize_hearing_committee(item: dict) -> str:
    committee = norm_text(
        item.get("committee_en")
        or item.get("committee_cn")
        or item.get("committee_zh")
        or item.get("committee")
        or ""
    )
    committee = committee.replace("&", " and ")
    committee = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", committee)
    for phrase in (
        "united states",
        "u s",
        "house of representatives",
        "house",
        "senate",
        "committee on",
        "committee",
        "subcommittee on",
        "subcommittee",
        "select",
        "the",
    ):
        committee = re.sub(rf"\b{re.escape(phrase)}\b", " ", committee)
    return norm_text(committee)


def normalize_hearing_title(title: str) -> str:
    title = norm_text(title)
    title = re.sub(r"^(?:hearing|hearings|meeting)\s*[:;-]\s*", "", title)
    title = title.replace("&", " and ")
    title = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", title)
    return norm_text(title)


def hearing_merge_parts(item: dict) -> tuple[str, str, str] | None:
    if not is_hearing_item(item):
        return None

    date = norm_text(item.get("sort_date") or item.get("date") or "")
    committee = normalize_hearing_committee(item)
    title = normalize_hearing_title(item.get("title") or "")
    if not date or not committee or not title:
        return None
    return date, committee, title


def hearing_merge_key(item: dict) -> str:
    parts = hearing_merge_parts(item)
    return "|".join(parts) if parts else ""


def title_similarity(left: str, right: str) -> float:
    left_tokens = {x for x in left.split() if len(x) > 2}
    right_tokens = {x for x in right.split() if len(x) > 2}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def find_matching_hearing_index(item: dict, deduped: list[dict]) -> int | None:
    parts = hearing_merge_parts(item)
    if not parts:
        return None

    date, committee, title = parts
    for index, existing in enumerate(deduped):
        existing_parts = hearing_merge_parts(existing)
        if not existing_parts:
            continue
        existing_date, existing_committee, existing_title = existing_parts
        if date != existing_date or committee != existing_committee:
            continue
        if title == existing_title:
            return index
        if len(title) >= 18 and (title in existing_title or existing_title in title):
            return index
        if title_similarity(title, existing_title) >= 0.72:
            return index
    return None


def merge_hearing_source(base: dict, extra: dict) -> None:
    base_source = (base.get("source") or "").strip()
    extra_source = (extra.get("source") or "").strip()
    if extra_source and extra_source not in base_source:
        base["source"] = "; ".join(x for x in (base_source, extra_source) if x)

    additions: list[str] = []
    extra_summary = (extra.get("summary") or "").strip()
    base_summary = (base.get("summary") or "").strip()
    if extra_summary and norm_text(extra_summary) not in norm_text(base_summary):
        additions.append(extra_summary)

    extra_link = (extra.get("link") or "").strip()
    if extra_link and normalize_link(extra_link) != normalize_link(base.get("link") or ""):
        if norm_text(extra_link) not in norm_text(base_summary):
            additions.append(f"Additional source link: {extra_link}")

    if additions:
        merged_summary = " | ".join(x for x in [base_summary, *additions] if x)
        base["summary"] = merged_summary[:1200].rstrip()


def task_list(chamber: str) -> list[CommitteeTask]:
    if chamber == "house":
        return HOUSE_TASKS
    if chamber == "senate":
        return SENATE_TASKS
    return HOUSE_TASKS + SENATE_TASKS


def _accepts_existing_links(func: Callable[..., list[dict]]) -> bool:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return True

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == "existing_links":
            return True
    return False


def run_committee_task(task: CommitteeTask, existing_links: set[str]) -> tuple[list[dict], float]:
    started = time.perf_counter()
    if _accepts_existing_links(task.func):
        items = task.func(existing_links=existing_links)
    else:
        items = task.func()

    if items is None:
        items = []
    if not isinstance(items, list):
        items = list(items)

    return items, time.perf_counter() - started


def load_existing_state() -> tuple[set[str], set[str]]:
    started = time.perf_counter()
    raw_links = get_existing_links()
    existing_links = {normalize_link(x) for x in raw_links if (x or "").strip()}
    existing_keys = {norm_text(x) for x in get_existing_item_keys() if (x or "").strip()}

    # add_news() has its own cache; priming it here prevents a second full database scan.
    notion_writer._EXISTING_LINKS_CACHE = set(existing_links)
    notion_writer._EXISTING_KEYS_CACHE = set(existing_keys)

    print(
        f"[Notion] loaded {len(existing_links)} links and "
        f"{len(existing_keys)} keys in {time.perf_counter() - started:.1f}s"
    )
    return existing_links, existing_keys


def scrape_all(
    tasks: list[CommitteeTask],
    existing_links: set[str],
    workers: int,
) -> tuple[list[dict], list[str], list[CommitteeTask]]:
    workers = max(1, min(workers, len(tasks) or 1))
    print(f"[Scrape] running {len(tasks)} committees with {workers} workers")

    results: dict[int, list[dict]] = {}
    failures: list[str] = []
    failed_tasks: list[CommitteeTask] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_committee_task, task, existing_links): (index, task)
            for index, task in enumerate(tasks)
        }

        for future in as_completed(futures):
            index, task = futures[future]
            label = f"{task.chamber} / {task.name}"
            try:
                items, elapsed = future.result()
                results[index] = items
                print(f"[Scrape] OK {label}: {len(items)} items in {elapsed:.1f}s")
            except Exception as exc:
                failures.append(f"{label}: {exc}")
                failed_tasks.append(task)
                results[index] = []
                print(f"[Scrape] FAIL {label}: {exc}")

    all_items: list[dict] = []
    for index in range(len(tasks)):
        all_items.extend(results.get(index, []))

    return all_items, failures, failed_tasks


def dedupe_new_items(
    items: Iterable[dict],
    existing_links: set[str],
    existing_keys: set[str],
) -> list[dict]:
    deduped: list[dict] = []
    seen_links: set[str] = set()
    seen_keys: set[str] = set()
    seen_hearings: dict[str, int] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        raw_link = (item.get("link") or "").strip()
        norm_link = normalize_link(raw_link)
        item_key = build_item_key(item)
        item["unique_key"] = item_key

        if not norm_link:
            print(f"[Skip] missing link: {item.get('title', '')}")
            continue

        if norm_link in existing_links:
            print(f"[Skip] existing Notion link: {raw_link}")
            continue

        if norm_text(item_key) in existing_keys:
            print(f"[Skip] existing Notion key: {item.get('title', '')}")
            continue

        merge_key = hearing_merge_key(item)
        merge_index = seen_hearings.get(merge_key) if merge_key else None
        if merge_index is None:
            merge_index = find_matching_hearing_index(item, deduped)

        if merge_index is not None:
            merge_hearing_source(deduped[merge_index], item)
            seen_links.add(norm_link)
            seen_keys.add(norm_text(item_key))
            if merge_key:
                seen_hearings[merge_key] = merge_index
            print(f"[Merge] same hearing source: {item.get('title', '')}")
            continue

        if norm_link in seen_links:
            print(f"[Skip] duplicate link in this run: {raw_link}")
            continue

        if norm_text(item_key) in seen_keys:
            print(f"[Skip] duplicate key in this run: {item.get('title', '')}")
            continue

        item["link"] = norm_link
        seen_links.add(norm_link)
        seen_keys.add(norm_text(item_key))
        deduped.append(item)
        if merge_key:
            seen_hearings[merge_key] = len(deduped) - 1

    return deduped


def translate_value_checked(value: str, *, field: str, item_title: str) -> tuple[str, bool]:
    value = (value or "").strip()
    if not value:
        return value, False

    try:
        translated = translate_text(value)
    except Exception as exc:
        print(f"[Translate] FAIL {field}: {item_title or value[:80]} | {exc}")
        return value, True

    if looks_untranslated(value, translated):
        print(f"[Translate] suspicious unchanged {field}: {item_title or value[:80]}")
        return translated, True

    return translated, False


def translate_and_format(item: dict, skip_translate: bool) -> tuple[dict, list[str]]:
    item = dict(item)
    failed_fields: list[str] = []

    if not skip_translate:
        original_title = (item.get("title") or "").strip()
        summary = (item.get("summary") or "").strip()

        if original_title:
            translated_title, failed = translate_value_checked(
                original_title,
                field="title",
                item_title=original_title,
            )
            item["title"] = translated_title
            if failed:
                failed_fields.append("title")

        if summary:
            try:
                summary_candidate = translate_summary_if_needed(summary)
            except Exception:
                summary_candidate = summary

            if summary_candidate:
                translated_summary, failed = translate_value_checked(
                    summary_candidate,
                    field="summary",
                    item_title=original_title,
                )
                item["summary"] = translated_summary
                if failed:
                    failed_fields.append("summary")

    chamber = (item.get("chamber") or "").strip().lower()
    if chamber == "senate":
        return run_senate.format_output_fields(item), failed_fields
    return run_house.format_output_fields(item), failed_fields


def write_prepared_item(
    item: dict,
    existing_links: set[str],
    existing_keys: set[str],
    *,
    dry_run: bool,
) -> str:
    raw_link = (item.get("link") or "").strip()
    norm_link = normalize_link(raw_link)
    item_key = item.get("unique_key") or build_item_key(item)
    title = (item.get("title") or "").strip()

    if dry_run:
        print(f"[DryRun] would write: {title}")
    else:
        response = add_news(item)
        if isinstance(response, dict) and response.get("skipped"):
            print(f"[Skip] Notion skipped: {title}")
            return "skipped"

    existing_links.add(norm_link)
    existing_keys.add(norm_text(item_key))
    print(f"[Write] OK: {title}")
    return "success"


def write_items(
    items: list[dict],
    existing_links: set[str],
    existing_keys: set[str],
    *,
    dry_run: bool,
    skip_translate: bool,
) -> tuple[int, int, int, int, int]:
    success = 0
    skipped = 0
    failed = 0
    translation_retry_items: list[dict] = []
    translation_failed_after_retry = 0

    for item in items:
        raw_link = (item.get("link") or "").strip()
        norm_link = normalize_link(raw_link)
        item_key = item.get("unique_key") or build_item_key(item)
        title = (item.get("title") or "").strip()

        if not norm_link:
            print(f"[Skip] missing link before write: {title}")
            skipped += 1
            continue

        if norm_link in existing_links:
            print(f"[Skip] existing link before write: {title}")
            skipped += 1
            continue

        if norm_text(item_key) in existing_keys:
            print(f"[Skip] existing key before write: {title}")
            skipped += 1
            continue

        try:
            prepared, translation_failures = translate_and_format(
                item,
                skip_translate=skip_translate,
            )
            prepared["unique_key"] = item_key

            if translation_failures and not skip_translate:
                print(
                    f"[Translate] queued for retry after first pass: "
                    f"{title} ({', '.join(translation_failures)})"
                )
                translation_retry_items.append(dict(item))
                continue

            outcome = write_prepared_item(
                prepared,
                existing_links,
                existing_keys,
                dry_run=dry_run,
            )
            if outcome == "skipped":
                skipped += 1
            else:
                success += 1

        except Exception as exc:
            failed += 1
            print(f"[Write] FAIL: {title} | {exc}")

    if translation_retry_items:
        print(f"\n[Translate] retrying {len(translation_retry_items)} failed translation items once")

    for item in translation_retry_items:
        raw_link = (item.get("link") or "").strip()
        norm_link = normalize_link(raw_link)
        item_key = item.get("unique_key") or build_item_key(item)
        title = (item.get("title") or "").strip()

        if norm_link in existing_links or norm_text(item_key) in existing_keys:
            skipped += 1
            print(f"[Skip] already written before translation retry: {title}")
            continue

        try:
            time.sleep(TRANSLATION_RETRY_DELAY)
            prepared, translation_failures = translate_and_format(
                item,
                skip_translate=skip_translate,
            )
            prepared["unique_key"] = item_key

            if translation_failures:
                translation_failed_after_retry += 1
                print(
                    f"[Translate] still failed after retry, writing original/partial text: "
                    f"{title} ({', '.join(translation_failures)})"
                )

            outcome = write_prepared_item(
                prepared,
                existing_links,
                existing_keys,
                dry_run=dry_run,
            )
            if outcome == "skipped":
                skipped += 1
            else:
                success += 1

        except Exception as exc:
            failed += 1
            print(f"[Write] FAIL after translation retry: {title} | {exc}")

    return success, skipped, failed, len(translation_retry_items), translation_failed_after_retry


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimized Congress Monitor runner")
    parser.add_argument(
        "--chamber",
        choices=["all", "house", "senate"],
        default=os.getenv("CONGRESS_CHAMBER", "all").lower(),
        help="Committee group to run",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("CONGRESS_WORKERS", str(DEFAULT_WORKERS))),
        help="Committee scrape concurrency",
    )
    parser.add_argument(
        "--no-notion",
        action="store_true",
        help="Scrape and dedupe only; do not read or write Notion",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read Notion and scrape, but do not write new pages",
    )
    parser.add_argument(
        "--skip-translate",
        action="store_true",
        default=os.getenv("CONGRESS_SKIP_TRANSLATION", "").lower() in {"1", "true", "yes"},
        help="Write original English title/summary without Google Translate calls",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    tasks = task_list(args.chamber)

    log_start("Start optimized Congress Monitor")
    started = time.perf_counter()

    try:
        print("\n====================")
        print("Congress Monitor optimized run")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Chamber: {args.chamber}")
        print(f"Workers: {args.workers}")
        print("====================\n")

        if args.no_notion:
            existing_links: set[str] = set()
            existing_keys: set[str] = set()
            print("[Notion] skipped because --no-notion was passed")
        else:
            existing_links, existing_keys = load_existing_state()

        all_items, scrape_failures, failed_tasks = scrape_all(
            tasks,
            existing_links,
            workers=args.workers,
        )
        initial_scrape_failures = len(scrape_failures)

        if failed_tasks:
            retry_workers = max(1, min(args.workers, len(failed_tasks)))
            print(f"\n[Scrape] retrying {len(failed_tasks)} failed committees once")
            retry_items, scrape_failures, failed_tasks = scrape_all(
                failed_tasks,
                existing_links,
                workers=retry_workers,
            )
            all_items.extend(retry_items)
            print(
                f"[Scrape] retry recovered "
                f"{initial_scrape_failures - len(scrape_failures)} committees"
            )

        print(f"\n[Scrape] total raw items: {len(all_items)}")

        deduped_items = dedupe_new_items(all_items, existing_links, existing_keys)
        print(f"[Dedupe] new items after global dedupe: {len(deduped_items)}")

        success, skipped, failed, translation_retries, translation_failed_after_retry = write_items(
            deduped_items,
            existing_links,
            existing_keys,
            dry_run=args.no_notion or args.dry_run,
            skip_translate=args.skip_translate,
        )

        elapsed = time.perf_counter() - started
        print("\n====================")
        print(f"Initial scrape failures: {initial_scrape_failures}")
        print(f"Scrape failures: {len(scrape_failures)}")
        for failure in scrape_failures:
            print(f"- {failure}")
        print(f"Translation retries: {translation_retries}")
        print(f"Translation still failed after retry: {translation_failed_after_retry}")
        print(f"Written: {success}")
        print(f"Skipped: {skipped}")
        print(f"Write failed: {failed}")
        print(f"Elapsed: {elapsed:.1f}s")
        print("====================\n")

        log_success("Optimized Congress Monitor finished")
        return 0

    except Exception as exc:
        log_failure(exc, "Optimized Congress Monitor failed")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
