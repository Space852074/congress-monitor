# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


_DEFAULT_TARGET = "zh-CN"
_MAX_SEGMENT_CHARS = 400
_MIN_SUMMARY_CHARS = 80
_REQUEST_INTERVAL = float(os.getenv("TRANSLATION_REQUEST_INTERVAL", "0.45"))
_MAX_ATTEMPTS = max(1, int(os.getenv("TRANSLATION_MAX_ATTEMPTS", "3")))
_CACHE_PATH = Path(
    os.getenv(
        "CONGRESS_TRANSLATION_CACHE",
        str(Path(__file__).resolve().parent / "logs" / "translation_cache.sqlite3"),
    )
)

_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
        ),
    }
)
_REQUEST_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


class TranslationError(RuntimeError):
    pass


def _split_for_translation(text: str) -> list[str]:
    value = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not value:
        return []

    parts = re.split(r"([.!?;。！？；\n])", value)
    segments: list[str] = []
    for index in range(0, len(parts), 2):
        chunk = parts[index] or ""
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        combined = (chunk + separator).strip()
        if combined:
            segments.append(combined)

    refined: list[str] = []
    for segment in segments:
        if len(segment) <= _MAX_SEGMENT_CHARS:
            refined.append(segment)
            continue

        words = segment.split()
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > _MAX_SEGMENT_CHARS:
                refined.append(current)
                current = word
            else:
                current = candidate
        if current:
            refined.append(current)

    return refined


def _cache_key(segment: str, target: str) -> str:
    raw = f"{target}\0{segment}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_connect() -> sqlite3.Connection:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_CACHE_PATH, timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS translations ("
        "cache_key TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT NOT NULL, "
        "translated TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return connection


def _cache_get(segment: str, target: str) -> str:
    try:
        with _CACHE_LOCK, _cache_connect() as connection:
            row = connection.execute(
                "SELECT translated FROM translations WHERE cache_key = ?",
                (_cache_key(segment, target),),
            ).fetchone()
        return row[0] if row else ""
    except sqlite3.Error:
        return ""


def _cache_put(segment: str, target: str, translated: str) -> None:
    try:
        with _CACHE_LOCK, _cache_connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO translations "
                "(cache_key, source, target, translated) VALUES (?, ?, ?, ?)",
                (_cache_key(segment, target), segment, target, translated),
            )
    except sqlite3.Error as exc:
        print(f"[Translate] cache write skipped: {exc}")


def _throttle() -> None:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = _REQUEST_INTERVAL - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        _LAST_REQUEST_AT = time.monotonic()


def _translate_clients5(segment: str, target: str) -> str:
    response = _SESSION.get(
        "https://clients5.google.com/translate_a/t",
        params={"client": "dict-chrome-ex", "sl": "auto", "tl": target, "q": segment},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list):
        translated = "".join(part for part in data if isinstance(part, str)).strip()
        if translated:
            return translated
    raise TranslationError("clients5 returned an unexpected response")


def _translate_mobile(segment: str, target: str) -> str:
    response = _SESSION.get(
        "https://translate.google.com/m",
        params={"sl": "auto", "tl": target, "q": segment},
        timeout=20,
    )
    response.raise_for_status()
    result = BeautifulSoup(response.text, "html.parser").select_one(".result-container")
    translated = result.get_text(" ", strip=True) if result else ""
    if translated:
        return translated
    raise TranslationError("mobile translator returned no result")


def _translate_one_segment(segment: str, target: str) -> str:
    segment = (segment or "").strip()
    if not segment:
        return segment

    cached = _cache_get(segment, target)
    if cached:
        return cached

    errors: list[str] = []
    providers = (_translate_clients5, _translate_mobile)
    for attempt in range(_MAX_ATTEMPTS):
        for provider in providers:
            try:
                _throttle()
                translated = provider(segment, target)
                if translated and translated.strip() != segment:
                    _cache_put(segment, target, translated)
                    return translated
                errors.append(f"{provider.__name__}: unchanged response")
            except Exception as exc:
                errors.append(f"{provider.__name__}: {exc}")
        if attempt + 1 < _MAX_ATTEMPTS:
            time.sleep(min(8.0, 1.5 * (2**attempt)))

    raise TranslationError("; ".join(errors[-4:]))


def _summary_fallback(summary: str, min_len: int = _MIN_SUMMARY_CHARS) -> str:
    value = (summary or "").strip()
    if not value or len(value) >= min_len:
        return value
    segments = _split_for_translation(value)
    return "".join(segments[:3]) or value


def translate_text(text, target=_DEFAULT_TARGET):
    if not text:
        return text
    segments = _split_for_translation(str(text))
    if not segments:
        return text
    return "".join(_translate_one_segment(segment, target) for segment in segments)


def translate_summary_if_needed(summary: str, min_len: int = _MIN_SUMMARY_CHARS) -> str:
    return _summary_fallback(summary, min_len=min_len)
