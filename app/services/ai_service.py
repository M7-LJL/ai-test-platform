from __future__ import annotations

import re


def _normalize_point(sentence: str) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip(" .。;；,，")
    sentence = re.sub(r"^(用户|系统|页面|应用|平台)", "", sentence).strip()

    replacements = (
        (r"^(需要|应当|应该|可以|能够)", ""),
        (r"^支持", ""),
        (r"^实现", ""),
        (r"^提供", ""),
        (r"^具备", ""),
    )
    for pattern, replacement in replacements:
        sentence = re.sub(pattern, replacement, sentence).strip()

    if not sentence:
        return ""
    if sentence.startswith("验证"):
        return sentence
    return f"验证{sentence}"


def analyze_requirement(content: str) -> list[str]:
    """Generate simple mocked test points from requirement text."""
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return []

    raw_parts = re.split(r"[\r\n]+|(?<=[。！？!?；;])", content)
    candidates: list[str] = []

    for part in raw_parts:
        cleaned = re.sub(r"^\s*[-*0-9.)、]+\s*", "", part).strip()
        cleaned = cleaned.strip("。！？!?；;")
        if len(cleaned) >= 4:
            point = _normalize_point(cleaned)
            if point and point not in candidates:
                candidates.append(point)

    if not candidates:
        fallback = _normalize_point(normalized[:80])
        return [fallback] if fallback else []

    return candidates[:8]
