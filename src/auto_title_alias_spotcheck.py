"""Read-only spot check for safe second-query title retrieval variants."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

from . import spotify
from . import retrieval_policy
from .retrieval_benchmark import parse_lines
from .retrieval_spotcheck import (
    attach_baseline_analysis,
    run_spotcheck,
    validate_search_scope,
)
from .title_alias_diagnostic import discover_title_aliases
from .production_retrieval_benchmark import print_summary


def _romanized_retrieval_title(value: str) -> str:
    """Apply a tiny diagnostic-only set of Japanese romanization variants."""
    title = unicodedata.normalize("NFKC", value).strip()
    title = re.sub(r"\bwo\b", "o", title, flags=re.IGNORECASE)
    title = re.sub(r"\bbocci\b", "botchi", title, flags=re.IGNORECASE)
    return title


def _song_key(song: dict[str, str]) -> tuple[str, str]:
    return (
        spotify._normalize_text(song["title"]),
        spotify._normalize_text(song["artist"]),
    )


def _second_query_title_overrides(
    songs: list[dict[str, str]],
    aliases: dict[tuple[str, str], str],
    discovery: list[dict],
) -> dict[str, str]:
    """Build title overrides used only by retrieval query #2 after strict zero."""
    traces = {
        (
            spotify._normalize_text(row.get("source_title", "")),
            spotify._normalize_text(row.get("source_artist", "")),
        ): row
        for row in discovery
    }
    overrides: dict[str, str] = {}

    for song in songs:
        key = _song_key(song)
        title_key = spotify._normalize_text(song["title"])
        trace = traces.get(key, {})
        alias = aliases.get(key)

        selected: str | None = None
        if alias and not trace.get("parenthetical_translation", False):
            selected = alias
        else:
            base = spotify._retrieval_query_title(song["title"])
            transformed = _romanized_retrieval_title(base)
            if transformed != base:
                selected = transformed

        if not selected:
            continue

        existing = overrides.get(title_key)
        if existing and existing != selected:
            raise ValueError(
                "Diagnostic second-query title override collision for "
                f"{song['title']}"
            )
        overrides[title_key] = selected

    return overrides


def _run_second_query_diagnostic(
    access_token: str,
    songs: list[dict[str, str]],
    *,
    max_search_requests: int,
    delay_seconds: float,
    overrides: dict[str, str],
) -> dict:
    """Run the normal matcher while changing only retrieval query #2 titles."""
    original_hook = retrieval_policy._diagnostic_title_variant_hook

    def diagnostic_title_variant(name: str) -> str | None:
        return overrides.get(spotify._normalize_text(name))

    retrieval_policy.set_diagnostic_title_variant_hook(diagnostic_title_variant)
    try:
        return run_spotcheck(
            access_token,
            songs,
            max_search_requests=max_search_requests,
            delay_seconds=delay_seconds,
            title_aliases=None,
        )
    finally:
        retrieval_policy.set_diagnostic_title_variant_hook(original_hook)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-traffic second-query title retrieval diagnostic"
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
    overrides = _second_query_title_overrides(songs, aliases, discovery)
    baseline = json.loads(Path(args.baseline_metadata).read_text(encoding="utf-8"))

    report = _run_second_query_diagnostic(
        args.access_token,
        songs,
        max_search_requests=args.max_search_requests,
        delay_seconds=args.delay_seconds,
        overrides=overrides,
    )
    report["title_alias_mode"] = "second_query_only_diagnostic"
    report["title_alias_discovery"] = discovery
    report["second_query_title_overrides"] = overrides
    report["second_query_title_override_count"] = len(overrides)
    attach_baseline_analysis(report, baseline, len(songs))

    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Second-Query Title Retrieval Spot Check ===")
    print(f"Read only: {report.get('read_only', True)}")
    print(f"Search budget: {report['search_budget']}")
    print(f"Spotify Search requests used: {report['budgeted_search_requests']}")
    print(
        "Second-query title overrides: "
        f"{report['second_query_title_override_count']}"
    )
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
        key = spotify._normalize_text(row["source_title"])
        print(
            "Title diagnostic: "
            f"{row['source_title']} - {row['source_artist']} -> "
            f"MB={row.get('selected_title') or 'NONE'}; "
            f"query2={overrides.get(key) or 'UNCHANGED'} "
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
