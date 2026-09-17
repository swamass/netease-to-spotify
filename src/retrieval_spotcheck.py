"""Low-traffic, read-only production retrieval spot check.

Only known retrieval failures are allowed to reach Spotify Search. The 97/140
accepted baseline is analysis-only, and failures with already-saved candidates
stay in the offline matcher-analysis bucket.

An optional oracle title-alias mode is diagnostic only: it substitutes a small
set of already-verified Spotify display titles so we can measure whether title
identity is the remaining bottleneck without changing production matching.
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


def load_title_aliases(path: str) -> dict[tuple[str, str], str]:
    """Load diagnostic-only source-title -> verified Spotify-title mappings."""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Title alias fixture must be a JSON list")

    aliases: dict[tuple[str, str], str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each title alias fixture row must be an object")
        source_title = str(row.get("source_title", "")).strip()
        artist = str(row.get("artist", "")).strip()
        spotify_title = str(row.get("spotify_title", "")).strip()
        if not source_title or not artist or not spotify_title:
            raise ValueError("Title alias fixture rows require source_title, artist, spotify_title")
        key = (
            spotify._normalize_text(source_title),
            spotify._normalize_text(artist),
        )
        aliases[key] = spotify_title
    return aliases


def apply_title_aliases(
    songs: list[dict[str, str]],
    title_aliases: dict[tuple[str, str], str] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return aliased diagnostic inputs while preserving the original source set."""
    aliases = title_aliases or {}
    search_songs: list[dict[str, str]] = []
    applied: list[dict[str, str]] = []

    for song in songs:
        alias = aliases.get(_song_key(song))
        search_song = dict(song)
        if alias:
            search_song["title"] = alias
            applied.append(
                {
                    "source_title": song["title"],
                    "source_artist": song["artist"],
                    "diagnostic_search_title": alias,
                }
            )
        search_songs.append(search_song)

    return search_songs, applied


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


def validate_title_alias_scope(
    songs: list[dict[str, str]],
    title_aliases: dict[tuple[str, str], str],
) -> None:
    """Prevent alias fixtures from silently targeting songs outside this sample."""
    sample_keys = {_song_key(song) for song in songs}
    unknown = set(title_aliases) - sample_keys
    if unknown:
        raise ValueError("Title alias fixture contains tracks outside the spot-check sample")


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
    title_aliases: dict[tuple[str, str], str] | None = None,
) -> dict:
    original_get = spotify._spotify_get
    state = {"search_requests": 0}
    search_songs, alias_applications = apply_title_aliases(songs, title_aliases)

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
                search_songs,
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

    # Restore original source labels in the report. The substituted title is
    # diagnostic input only and must never masquerade as the NetEase source.
    for index, row in enumerate(report.get("tracks", [])):
        if index >= len(songs):
            break
        original_song = songs[index]
        alias = (title_aliases or {}).get(_song_key(original_song))
        row["source_title"] = original_song["title"]
        row["source_artist"] = original_song["artist"]
        row["diagnostic_search_title"] = alias or original_song["title"]
        row["title_alias_applied"] = bool(alias)

    report["mode"] = "production_retrieval_spotcheck"
    report["spotcheck"] = True
    report["search_budget"] = max_search_requests
    report["budgeted_search_requests"] = state["search_requests"]
    report["title_alias_mode"] = "oracle_diagnostic" if title_aliases else "none"
    report["title_aliases_applied"] = len(alias_applications)
    report["title_alias_applications"] = alias_applications
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Low-traffic read-only spot check of production retrieval"
    )
    parser.add_argument("input")
    parser.add_argument("--allowed-failures", required=True)
    parser.add_argument("--baseline-metadata", required=True)
    parser.add_argument("--title-aliases")
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--max-search-requests", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--json", default="retrieval_spotcheck.json")
    args = parser.parse_args()

    songs = parse_lines(args.input)
    allowed_failures = parse_lines(args.allowed_failures)
    validate_search_scope(songs, allowed_failures)
    title_aliases = load_title_aliases(args.title_aliases) if args.title_aliases else {}
    validate_title_alias_scope(songs, title_aliases)
    baseline = json.loads(Path(args.baseline_metadata).read_text(encoding="utf-8"))

    report = run_spotcheck(
        args.access_token,
        songs,
        max_search_requests=args.max_search_requests,
        delay_seconds=args.delay_seconds,
        title_aliases=title_aliases,
    )
    attach_baseline_analysis(report, baseline, len(songs))
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== Production Retrieval Spot Check ===")
    print(f"Read only: {report.get('read_only', True)}")
    print(f"Search budget: {report['search_budget']}")
    print(f"Spotify Search requests used: {report['budgeted_search_requests']}")
    print(f"Title alias mode: {report['title_alias_mode']}")
    print(f"Title aliases applied: {report['title_aliases_applied']}")
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
