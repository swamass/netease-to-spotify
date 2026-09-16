"""Low-traffic, read-only production retrieval spot check.

This wrapper exists to protect the daily sync from diagnostic traffic. It runs
only the supplied small sample and enforces a hard Spotify Search request budget.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import spotify
from .production_retrieval_benchmark import benchmark_production, print_summary
from .retrieval_benchmark import parse_lines


class SearchBudgetExceeded(RuntimeError):
    """Raised before a Spotify Search would exceed the diagnostic budget."""


def run_spotcheck(
    access_token: str,
    songs: list[dict[str, str]],
    *,
    max_search_requests: int = 10,
    delay_seconds: float = 1.0,
) -> dict:
    original_get = spotify._spotify_get
    state = {"search_requests": 0}

    def budgeted_get(url, token, params, *args, **kwargs):
        if "/search" in url:
            if state["search_requests"] >= max_search_requests:
                raise SearchBudgetExceeded(
                    f"Spotify Search budget exhausted at {max_search_requests} requests"
                )
            state["search_requests"] += 1
        return original_get(url, token, params, *args, **kwargs)

    spotify._spotify_get = budgeted_get
    try:
        try:
            report = benchmark_production(
                access_token,
                songs,
                missing_reference=None,
                delay_seconds=delay_seconds,
                baseline_accepted=None,
            )
        except SearchBudgetExceeded:
            report = {
                "mode": "production_retrieval_spotcheck",
                "read_only": True,
                "spotcheck": True,
                "total_source_tracks": len(songs),
                "completed_tracks": 0,
                "spotify_search_requests": state["search_requests"],
                "stopped_early": True,
                "stop_reason": "SEARCH_BUDGET_EXHAUSTED",
                "tracks": [],
            }
    finally:
        spotify._spotify_get = original_get

    report["mode"] = "production_retrieval_spotcheck"
    report["spotcheck"] = True
    report["search_budget"] = max_search_requests
    report["budgeted_search_requests"] = state["search_requests"]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-traffic read-only spot check of production retrieval"
    )
    parser.add_argument("input")
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--max-search-requests", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--json", default="retrieval_spotcheck.json")
    args = parser.parse_args()

    songs = parse_lines(args.input)
    report = run_spotcheck(
        args.access_token,
        songs,
        max_search_requests=args.max_search_requests,
        delay_seconds=args.delay_seconds,
    )
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Production Retrieval Spot Check ===")
    print(f"Read only: {report.get('read_only', True)}")
    print(f"Search budget: {report['search_budget']}")
    print(f"Spotify Search requests used: {report['budgeted_search_requests']}")
    if report.get("stop_reason") == "SEARCH_BUDGET_EXHAUSTED":
        print("STOPPED SAFELY: Spotify Search budget exhausted")
        raise SystemExit(3)
    print_summary(report)
    print(f"JSON report: {args.json}")
    if report.get("stopped_early"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
