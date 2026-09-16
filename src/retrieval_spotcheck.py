"""Low-traffic, read-only production retrieval spot check.

Only known retrieval failures are allowed to reach Spotify Search. The 97/140
accepted baseline is analysis-only, and failures with already-saved candidates
stay in the offline matcher-analysis bucket.
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


def _song_key(song: dict[str, str]) -> tuple[str, str]:
    return (
        spotify._normalize_text(song["title"]),
        spotify._normalize_text(song["artist"]),
    )


def validate_search_scope(
    songs: list[dict[str, str]],
    allowed_failures: list[dict[str, str]],
) -> None:
    """Reject any live-search input outside the known retrieval-failure set."""
    allowed = {_song_key(song) for song in allowed_failures}
    disallowed = [song for song in songs if _song_key(song) not in allowed]
    if disallowed:
        preview = "; ".join(
            f"{song['title']} - {song['artist']}" for song in disallowed[:3]
        )
        raise ValueError(
            "Live retrieval diagnostics may search only the known retrieval "
            f"failure set. Disallowed input: {preview}"
        )


def attach_baseline_analysis(
    report: dict,
    baseline: dict,
    sample_size: int,
) -> dict:
    """Add comparison metadata without searching any baseline-accepted tracks."""
    accepted = int(baseline.get("baseline_accepted", 0))
    total = int(baseline.get("reference_total", 0))
    retrieval_total = int(
        baseline.get("retrieval_failures_without_saved_candidates", 0)
    )
    saved_failure_total = int(
        baseline.get("matcher_failures_with_saved_candidates", 0)
    )
    report["analysis_comparison"] = {
        "reference_total": total,
        "baseline_accepted": accepted,
        "baseline_acceptance_rate": accepted / total if total else 0,
        "baseline_accepted_tracks_searched": 0,
        "saved_candidate_failure_tracks_searched": 0,
        "retrieval_failure_tracks_total": retrieval_total,
        "retrieval_failure_sample_tracks": sample_size,
        "sample_newly_accepted": int(report.get("accepted_all", 0)),
        "matcher_failures_kept_offline": saved_failure_total,
        "note": (
            "97/140 is analysis-only. Live Spotify Search is restricted to "
            "the retrieval-failure set; saved-candidate failures stay offline."
        ),
    }
    return report


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
                "accepted_all": 0,
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
    baseline = json.loads(Path(args.baseline_metadata).read_text(encoding="utf-8"))

    report = run_spotcheck(
        args.access_token,
        songs,
        max_search_requests=args.max_search_requests,
        delay_seconds=args.delay_seconds,
    )
    attach_baseline_analysis(report, baseline, len(songs))
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Production Retrieval Spot Check ===")
    print(f"Read only: {report.get('read_only', True)}")
    print(f"Search budget: {report['search_budget']}")
    print(f"Spotify Search requests used: {report['budgeted_search_requests']}")
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
    if report.get("stop_reason") == "SEARCH_BUDGET_EXHAUSTED":
        print("STOPPED SAFELY: Spotify Search budget exhausted")
        raise SystemExit(3)
    print_summary(report)
    print(f"JSON report: {args.json}")
    if report.get("stopped_early"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
