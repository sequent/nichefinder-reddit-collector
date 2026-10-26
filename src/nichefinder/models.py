"""Domain model used by the read-only Reddit collector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Signal:
    """One external evidence point for a niche.

    Metrics are numeric when possible (post counts, shares) and can also carry
    a text summary for things like top complaint themes.
    """

    niche_key: str
    source: str
    metric: str
    value: float | None = None
    text_value: str | None = None
    unit: str | None = None
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
