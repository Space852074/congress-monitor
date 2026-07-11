# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, NavigableString

from committee_translate import get_committee_cn


TIME_WINDOW_DAYS = 10
LOOKAHEAD_DAYS = 60

SENATE_XML_URL = "https://www.senate.gov/general/committee_schedules/hearings.xml"
SENATE_HTML_URL = "https://www.senate.gov/committees/hearings_meetings.htm"
HOUSE_WEEK_URL = "https://docs.house.gov/Committee/Calendar/ByWeek.aspx"
HOUSE_MONTH_URL = "https://docs.house.gov/Committee/Calendar/ByMonth.aspx"
HOUSE_EVENT_URL = "https://docs.house.gov/Committee/Calendar/ByEvent.aspx"
HOUSE_ACTIVITY_URL = "https://www.house.gov/legislative-activity"

HEARING_ZH = "\u542c\u8bc1\u4f1a"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
}


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower().replace("www.", "")
    path = (parsed.path or "").rstrip("/")

    return urlunparse((scheme, netloc, path, "", parsed.query, ""))


def fetch_text(url: str, timeout: int = 30) -> str:
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = "utf-8"
    return response.text


def in_window(dt: datetime) -> bool:
    today = datetime.now().date()
    return today - timedelta(days=TIME_WINDOW_DAYS) <= dt.date() <= today + timedelta(days=LOOKAHEAD_DAYS)


def parse_date(value: str) -> datetime | None:
    value = clean_text(value)
    value = value.replace("Tues,", "Tuesday,").replace("Thurs,", "Thursday,")

    patterns = [
        "%Y-%m-%d",
        "%A, %B %d, %Y",
        "%A, %b %d, %Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%m/%d/%Y",
    ]

    for fmt in patterns:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass

    regexes = [
        r"(\d{4}-\d{2}-\d{2})",
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]+ \d{1,2}, \d{4})",
        r"([A-Z][a-z]+day,\s+[A-Z][a-z]{3} \d{1,2}, \d{4})",
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]

    for pattern in regexes:
        match = re.search(pattern, value)
        if not match:
            continue
        dt = parse_date(match.group(1))
        if dt:
            return dt

    return None


def build_item(
    *,
    chamber: str,
    committee_en: str,
    title: str,
    summary: str,
    article_dt: datetime,
    link: str,
    source: str,
) -> dict:
    committee_cn = get_committee_cn(committee_en, chamber=chamber)
    return {
        "committee_en": committee_en,
        "committee_cn": committee_cn,
        "committee_zh": committee_cn,
        "committee": committee_en,
        "chamber": chamber,
        "category_en": "Hearing",
        "category": HEARING_ZH,
        "title": clean_text(title),
        "summary": clean_text(summary),
        "date": article_dt.strftime("%Y-%m-%d"),
        "sort_date": article_dt.strftime("%Y-%m-%d"),
        "link": normalize_link(link),
        "party": "",
        "source": source,
    }


def child_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return clean_text(child.text if child is not None else "")


def senate_committee_name(value: str) -> str:
    value = clean_text(value)
    if not value:
        return "Senate"
    if value.lower().startswith("senate "):
        return value
    return f"Senate {value} Committee"


def run_senate_hearing_notices(existing_links: set[str] | None = None) -> list[dict]:
    existing = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    root = ET.fromstring(fetch_text(SENATE_XML_URL))
    items: list[dict] = []

    for meeting in root.findall(".//meeting"):
        committee = child_text(meeting, "committee")
        matter = child_text(meeting, "matter")
        meeting_type = child_text(meeting, "type")
        if not committee or "no committee hearings scheduled" in matter.lower():
            continue
        if "hearing" not in meeting_type.lower() and not re.search(r"\bhearings?\b", matter, re.I):
            continue

        date_iso = child_text(meeting, "date_iso_8601")
        article_dt = parse_date(date_iso or child_text(meeting, "date"))
        if not article_dt or not in_window(article_dt):
            continue

        identifier = child_text(meeting, "identifier")
        link = f"{SENATE_HTML_URL}?meeting={identifier}" if identifier else SENATE_XML_URL
        link = normalize_link(link)
        if link in existing:
            continue

        subcommittee = child_text(meeting, "sub_cmte")
        room = child_text(meeting, "room")
        time_value = child_text(meeting, "time")
        video_url = child_text(meeting, "video_url")

        summary_parts = [
            f"Date: {article_dt.strftime('%Y-%m-%d')}",
            f"Time: {time_value}" if time_value else "",
            f"Committee: {committee}",
            f"Subcommittee: {subcommittee}" if subcommittee else "",
            f"Type: {meeting_type}" if meeting_type else "",
            f"Room: {room}" if room else "",
            f"Video: {video_url}" if video_url else "",
            f"Source: {SENATE_XML_URL}",
        ]

        items.append(
            build_item(
                chamber="Senate",
                committee_en=senate_committee_name(committee),
                title=matter or f"{meeting_type}: {committee}",
                summary=" | ".join(x for x in summary_parts if x),
                article_dt=article_dt,
                link=link,
                source="senate.gov committee hearing schedule",
            )
        )

    return items


def house_committee_name(value: str) -> str:
    value = clean_text(value)
    if not value:
        return "House"
    if value.lower().startswith("house "):
        return value

    parent = re.search(r"\(Committee on ([^)]+)\)", value, re.I)
    if parent:
        committee = re.sub(r"^the\s+", "", clean_text(parent.group(1)), flags=re.I)
        return f"House {committee} Committee"

    direct = re.search(r"^Committee on (.+)$", value, re.I)
    if direct:
        committee = re.sub(r"^the\s+", "", clean_text(direct.group(1)), flags=re.I)
        return f"House {committee} Committee"

    if value.lower().startswith("select committee"):
        return f"House {value}"

    return f"House {value}"


def house_title_from_h1(h1) -> str:
    if not h1:
        return ""

    parts: list[str] = []
    for child in h1.contents:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif getattr(child, "name", "") == "br":
            parts.append(" ")
    title = clean_text(" ".join(parts))
    if not title:
        title = clean_text(h1.get_text(" ", strip=True))

    return re.sub(r"^(?:hearing|meeting):\s*", "", title, flags=re.I).strip()


def house_committee_from_h1(h1) -> str:
    if not h1:
        return ""
    blockquote = h1.find("blockquote")
    if blockquote:
        return clean_text(blockquote.get_text(" ", strip=True))
    return ""


def house_notice_link(panel, page_url: str) -> str:
    for text_node in panel.find_all(string=lambda text: text and "Hearing Notice" in text):
        parent = text_node.parent
        link = parent.find("a", href=True) if parent else None
        if link:
            return normalize_link(urljoin(page_url, link["href"]))
    return ""


def event_id_from_url(url: str) -> str:
    match = re.search(r"[?&]EventID=(\d+)", url or "", re.I)
    return match.group(1) if match else ""


def is_house_hearing(title: str, panel) -> bool:
    body = clean_text(panel.get_text(" ", strip=True)).lower()
    if re.search(r"\bhearing\b", title or "", re.I):
        return True
    if "hearing notice" in body:
        return True
    return bool(panel.select_one("a[href*='HHRG-']"))


def parse_house_event(page_url: str) -> dict | None:
    soup = BeautifulSoup(fetch_text(page_url), "html.parser")
    panel = soup.select_one("#previewPanel") or soup
    h1 = panel.find("h1")

    title = house_title_from_h1(h1)
    committee_raw = house_committee_from_h1(h1)
    if title.lower() in {"hearing", "meeting"} and committee_raw:
        title = f"{committee_raw} Hearing"

    if not is_house_hearing(title, panel):
        return None

    time_node = panel.select_one(".meetingTime")
    time_text = clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
    article_dt = parse_date(time_text)
    if not article_dt or not in_window(article_dt):
        return None

    committee_en = house_committee_name(committee_raw)
    location_node = panel.select_one("blockquote.location")
    location = clean_text(location_node.get_text(" ", strip=True)) if location_node else ""
    notice_link = house_notice_link(panel, page_url)

    summary_parts = [
        f"Date/time: {time_text}" if time_text else "",
        f"Committee: {committee_raw}" if committee_raw else "",
        f"Location: {location}" if location else "",
        f"Hearing Notice: {notice_link}" if notice_link else "",
        f"Source: {page_url}",
    ]

    return build_item(
        chamber="House",
        committee_en=committee_en,
        title=title,
        summary=" | ".join(x for x in summary_parts if x),
        article_dt=article_dt,
        link=page_url,
        source="docs.house.gov committee calendar",
    )


def house_activity_date_urls() -> list[str]:
    soup = BeautifulSoup(fetch_text(HOUSE_ACTIVITY_URL), "html.parser")
    urls: list[str] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href") or ""
        match = re.search(r"/legislative-activity/(\d{4}-\d{2}-\d{2})$", href)
        if not match:
            continue

        article_dt = parse_date(match.group(1))
        if not article_dt or not in_window(article_dt):
            continue

        page_url = normalize_link(urljoin(HOUSE_ACTIVITY_URL, href))
        if page_url in seen:
            continue
        seen.add(page_url)
        urls.append(page_url)

    return urls


def parse_house_activity_page(page_url: str) -> list[dict]:
    soup = BeautifulSoup(fetch_text(page_url), "html.parser")
    header = soup.select_one(".legislative-events--page .view-header h2")
    article_dt = parse_date(header.get_text(" ", strip=True) if header else page_url)
    if not article_dt or not in_window(article_dt):
        return []

    items: list[dict] = []
    for session in soup.select(".legislative-events--page .session-item"):
        title_link = session.select_one(".views-field-markup a[href]")
        if not title_link:
            continue

        raw_title = clean_text(title_link.get_text(" ", strip=True))
        if not re.search(r"\bhearing\b", raw_title, re.I):
            continue

        event_url = normalize_link(urljoin(page_url, title_link.get("href", "")))
        host_link = session.select_one(".views-field-nothing a[href]")
        host = clean_text(host_link.get_text(" ", strip=True)) if host_link else ""
        host_url = normalize_link(urljoin(page_url, host_link["href"])) if host_link else ""
        time_node = session.select_one(".views-field-date .field-content")
        location_node = session.select_one(".views-field-value-2 .field-content")
        time_value = clean_text(time_node.get_text(" ", strip=True)) if time_node else ""
        location = clean_text(location_node.get_text(" ", strip=True)) if location_node else ""

        title = re.sub(r"^hearing:\s*", "", raw_title, flags=re.I).strip()
        if title.lower() in {"hearing", ""} and host:
            title = f"{host} Hearing"

        event_id = event_id_from_url(event_url)
        item_link = f"{page_url}?eventID={event_id}" if event_id else page_url
        summary_parts = [
            f"Date/time: {article_dt.strftime('%Y-%m-%d')} {time_value}".strip(),
            f"Host: {host}" if host else "",
            f"Location: {location}" if location else "",
            f"House.gov event page: {event_url}" if event_url else "",
            f"Host link: {host_url}" if host_url else "",
            f"Source: {page_url}",
        ]

        items.append(
            build_item(
                chamber="House",
                committee_en=house_committee_name(host),
                title=title,
                summary=" | ".join(x for x in summary_parts if x),
                article_dt=article_dt,
                link=item_link,
                source="house.gov legislative activity schedule",
            )
        )

    return items


def run_house_activity_hearing_notices(existing_links: set[str] | None = None) -> list[dict]:
    existing = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    items: list[dict] = []

    for page_url in house_activity_date_urls():
        try:
            page_items = parse_house_activity_page(page_url)
        except Exception as exc:
            print(f"[House legislative activity] failed {page_url}: {exc}")
            continue

        for item in page_items:
            if normalize_link(item.get("link") or "") not in existing:
                items.append(item)

    return items


def house_event_urls(existing_links: set[str] | None = None) -> list[str]:
    existing = {normalize_link(x) for x in (existing_links or set()) if (x or "").strip()}
    urls: list[str] = []
    seen: set[str] = set()

    for calendar_url in (HOUSE_WEEK_URL, HOUSE_MONTH_URL):
        soup = BeautifulSoup(fetch_text(calendar_url), "html.parser")
        for link in soup.select("a[href*='ByEvent.aspx?EventID=']"):
            event_url = normalize_link(urljoin(calendar_url, link.get("href", "")))
            if not event_url or event_url in seen or event_url in existing:
                continue
            seen.add(event_url)
            urls.append(event_url)

    return urls


def run_house_hearing_notices(existing_links: set[str] | None = None) -> list[dict]:
    items: list[dict] = run_house_activity_hearing_notices(existing_links=existing_links)
    for event_url in house_event_urls(existing_links=existing_links):
        try:
            item = parse_house_event(event_url)
        except Exception as exc:
            print(f"[House central hearings] failed {event_url}: {exc}")
            continue
        if item:
            items.append(item)
    return items
