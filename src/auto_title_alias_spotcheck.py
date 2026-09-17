"""Read-only spot check using automatically discovered MusicBrainz title aliases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .retrieval_benchmark import parse_lines
from .retrieval_spotcheck import (
    attach_baseline_analysis,
    run_spotcheck,
    validate_search_scope,
)
from .title_alias_diagnostic import discover_title_aliases
from .production_retrieval_benchmark import print_summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-traffic automatic title-alias retrieval diagnostic"
    )
    parser.add_argument("input")
    parser.add_argument("--allowed-failures", required=True)
    parser.add_argument("--baseline-metadata", required=True)
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--max-search-requests", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--json", default="retrieval_spotcheck.json")
    args = parser.parse_args()

    songs = parse_lines(args.input)
    allowed_failures = parse_lines(args.allowed_failures)
    validate_search_scope(songs, allowed_failures)

    aliases, discovery = discover_title_aliases(songs)
    baseline = json.loads(Path(args.baseline_metadata).read_text(encoding="utf-8"))

    report = run_spotcheck(
        args.access_token,
        songs,
        max_search_requests=args.max_search_requests,
        delay_seconds=args.delay_seconds,
        title_aliases=aliases,
    )
    report["title_alias_mode"] = "musicbrainz_auto_diagnostic"
    report["title_alias_discovery"] = discovery
    attach_baseline_analysis(report, baseline, len(songs))

    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Automatic Title Alias Spot Check ===")
    print(f"Read only: {report.get('read_only', True)}")
    print(f"Search budget: {report['search_budget']}")
    print(f"Spotify Search requests used: {report['budgeted_search_requests']}")
    print(f"Automatically discovered aliases: {report['title_aliases_applied']}")
    comparison = report["analysis_comparison"]
    print(
        "Analysis baseline: "
        f"{comparison['baseline_accepted']}/{comparison['reference_total']} "
        "(0 baseline tracks searched)"
    )
    print(
        "Live search scope: "
        f"{comparison['retrieval_failure_sample_tracks']}/"
        f"{comparison['retrieval_failure_tracks_total']} retrieval failures"
    )
    for row in discovery:
        print(
            "Title alias discovery: "
            f"{row['source_title']} - {row['source_artist']} -> "
            f"{row.get('selected_title') or 'NONE'} "
            f"({row.get('reason')})"
        )

    if report.get("stop_reason") == "SEARCH_BUDGET_EXHAUSTED":
        print("STOPPED SAFELY: Spotify Search budget exhausted")
        raise SystemExit(3)
    print_summary(report)
    print(f"JSON report: {args.json}")
    if report.get("stopped_early"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
