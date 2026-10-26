"""Lightweight complaint theming for app-store reviews.

This is a transparent keyword baseline, not an LLM classifier. It is good
enough to show *which* pain themes appear in a niche and can be replaced by a
semantic classifier later without changing the storage schema.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

THEMES: dict[str, tuple[str, tuple[str, ...]]] = {
    "pricing": (
        "цена",
        (
            r"\bexpensive\b",
            r"\boverpriced\b",
            r"\bprice\b",
            r"\bpricing\b",
            r"\bcost\b",
            r"\brefund\b",
        ),
    ),
    "bugs": (
        "баги",
        (
            r"\bbug\b",
            r"\bcrash",
            r"\bglitch",
            r"\bbroken\b",
            r"\berror\b",
            r"\bfreez",
            r"\bdoesn't work\b",
            r"\bdoes not work\b",
        ),
    ),
    "support": (
        "поддержка",
        (
            r"\bsupport\b",
            r"\bcustomer service\b",
            r"\bno response\b",
            r"\bignored\b",
        ),
    ),
    "usability": (
        "сложность UX",
        (
            r"\bconfusing\b",
            r"\bcomplicated\b",
            r"\bdifficult\b",
            r"\bhard to use\b",
            r"\bclunky\b",
        ),
    ),
    "missing_features": (
        "не хватает функций",
        (
            r"\bmissing\b",
            r"\bwish\b",
            r"\bwould be nice\b",
            r"\bno option\b",
            r"\black of\b",
        ),
    ),
    "sync": (
        "синхронизация",
        (
            r"\bsync",
            r"\bdoesn't update\b",
            r"\bnot updating\b",
            r"\bdisconnect",
            r"\bintegration\b",
        ),
    ),
    "performance": (
        "скорость",
        (
            r"\bslow\b",
            r"\blag",
            r"\bbattery\b",
            r"\bperformance\b",
            r"\btakes forever\b",
        ),
    ),
    "accuracy": (
        "точность",
        (
            r"\binaccurate\b",
            r"\bwrong\b",
            r"\bmistake\b",
            r"\bincorrect\b",
            r"\bnot accurate\b",
        ),
    ),
    "ads": (
        "реклама",
        (
            r"\bads?\b",
            r"\bads everywhere\b",
            r"\bpaywall\b",
        ),
    ),
    "privacy": (
        "приватность",
        (
            r"\bprivacy\b",
            r"\bpermissions?\b",
            r"\baccount deletion\b",
            r"\bsells? (my|your) data\b",
        ),
    ),
}

_COMPILED = {
    key: (label, tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns))
    for key, (label, patterns) in THEMES.items()
}


def summarize_complaints(reviews: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    examples: dict[str, str] = {}
    matched = 0

    for review in reviews:
        text = f"{review.get('title') or ''} {review.get('content') or ''}".strip()
        if not text:
            continue
        matched_this = False
        for key, (_label, patterns) in _COMPILED.items():
            if any(pattern.search(text) for pattern in patterns):
                counts[key] = counts.get(key, 0) + 1
                examples.setdefault(key, text[:180])
                matched_this = True
        if matched_this:
            matched += 1

    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return {
        "matched": matched,
        "themes": [
            {"key": key, "label": _COMPILED[key][0], "count": count}
            for key, count in ordered
        ],
        "examples": {key: examples[key] for key, _count in ordered},
    }


def format_themes(summary: dict[str, Any], limit: int = 3) -> str:
    themes = summary.get("themes") or []
    if not themes:
        return "—"
    return ", ".join(
        f"{theme['label']} ({theme['count']})" for theme in themes[:limit]
    )
