#!/usr/bin/env python3
"""Collect Reddit signals for one niche."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from nichefinder.signals.reddit import RedditCollector, load_rules


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only Reddit collector for one niche."
    )
    parser.add_argument(
        "niche",
        nargs="?",
        default="ai_agents",
        choices=sorted(load_rules()),
        help="Niche key from reddit_queries.yaml (default: ai_agents)",
    )
    args = parser.parse_args()

    collector = RedditCollector(now=datetime.now(UTC))
    if not collector.available():
        print(collector.unavailable_reason)
        return 1

    try:
        signals = collector.collect(args.niche, args.niche.replace("_", " "))
    finally:
        collector.close()

    for signal in signals:
        value = "" if signal.value is None else f" {signal.value:g}"
        unit = f" {signal.unit}" if signal.unit else ""
        text = f" — {signal.text_value}" if signal.text_value else ""
        print(f"{signal.metric}{value}{unit}{text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
