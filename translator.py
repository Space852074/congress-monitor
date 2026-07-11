# -*- coding: utf-8 -*-
from __future__ import annotations

import re

import requests


_DEFAULT_TARGET = "zh-CN"
_MAX_SEGMENT_CHARS = 400
_MIN_SUMMARY_CHARS = 80


def _split_for_translation(text: str) -> list[str]:
    """
    按句号/分号/换行等切分，尽量保持标点归属到对应片段。
    """
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return []

    # 先按“句子/分隔符”切分，同时保留分隔符
    parts = re.split(r"([。！？!?;；\.\n])", s)
    segments: list[str] = []
    buf = ""
    for i in range(0, len(parts), 2):
        chunk = parts[i] or ""
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        buf = (chunk + sep).strip()
        if buf:
            segments.append(buf)

    # 再处理过长片段：按逗号/空格近似二次切分
    refined: list[str] = []
    for seg in segments:
        if len(seg) <= _MAX_SEGMENT_CHARS:
            refined.append(seg)
            continue
        # 优先按中文/英文逗号切，再按空格切
        subparts = re.split(r"([,，])", seg)
        cur = ""
        for i in range(0, len(subparts), 2):
            a = subparts[i] or ""
            comma = subparts[i + 1] if i + 1 < len(subparts) else ""
            candidate = (a + comma).strip()
            if not candidate:
                continue
            if len(cur) + len(candidate) <= _MAX_SEGMENT_CHARS:
                cur = (cur + candidate).strip()
            else:
                if cur:
                    refined.append(cur)
                cur = candidate
        if cur:
            refined.append(cur)

    return refined


def _translate_one_segment(segment: str, target: str) -> str:
    """
    翻译单段；单段失败时返回原文。
    """
    segment = (segment or "").strip()
    if not segment:
        return segment

    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": target,
            "dt": "t",
            "q": segment,
        }
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        translated = "".join(item[0] for item in data[0] if item and item[0])
        return translated or segment
    except Exception as e:
        # 单段失败：保留该段原文
        print("翻译段失败:", e)
        return segment


def _summary_fallback(summary: str, min_len: int = _MIN_SUMMARY_CHARS) -> str:
    """
    summary 为空或过短时，从其“前段内容”取 2-3 段作为可翻译摘要。
    （由于当前 monitor 返回字段只有 summary，不含正文全文，这里基于 summary 自身前段切分兜底。）
    """
    s = (summary or "").strip()
    if not s:
        return s
    if len(s) >= min_len:
        return s

    segments = _split_for_translation(s)
    lead = [x for x in segments[:3] if x.strip()]
    if not lead:
        return s
    return "".join(lead)


def translate_text(text, target=_DEFAULT_TARGET):
    """
    对长文本做分段翻译，再拼接；单段翻译失败时只保留该段原文。
    """
    if not text:
        return text

    # 过短：也走同一套逻辑，减少行为差异
    segments = _split_for_translation(str(text))
    if not segments:
        return text

    translated_parts: list[str] = []
    for seg in segments:
        translated_parts.append(_translate_one_segment(seg, target=target))
    return "".join(translated_parts) or text


def translate_summary_if_needed(summary: str, min_len: int = _MIN_SUMMARY_CHARS) -> str:
    """
    给 main_monitor 作为摘要兜底使用：summary 为空或太短时返回兜底摘要候选。
    """
    return _summary_fallback(summary, min_len=min_len)
