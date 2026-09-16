"""Read-only benchmark of the actual production Spotify retrieval + matcher stack."""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from . import spotify
from .retrieval_benchmark import parse_lines


def _song_key(song: dict[str, str]) -> tuple[str, str]:
    return (
        spotify._normalize_text(song["title"]),
        spotify._normalize_text(song["artist"]),
    )


def _candidate(item: dict) -> dict:
    return {
        "spotify_track_id": item.get("id"),
        "title": item.get("name", ""),
        "artists": [artist.get("name", "") for artist in item.get("artists", [])],
        "album": (item.get("album") or {}).get("name", ""),
        "isrc": (item.get("external_ids") or {}).get("isrc"),
    }


def _retry_after(error: Exception) -> int | None:
    value = getattr(error, "retry_after_seconds", None)
    return int(value) if value is not None else None


def benchmark_production(
    access_token: str,
    songs: list[dict[str, str]],
    missing_reference: list[dict[str, str]] | None = None,
    delay_seconds: float = 0.25,
    baseline_accepted: int | None = None,
) -> dict:
    missing_keys = {_song_key(song) for song in (missing_reference or [])}
    reference_total = sum(_song_key(song) not in missing_keys for song in songs)
    report = {
        "mode": "production_retrieval_policy",
        "read_only": True,
        "total_source_tracks": len(songs),
        "reference_success_tracks": reference_total,
        "reference_missing_tracks": len(songs) - reference_total,
        "baseline_reference_accepted": baseline_accepted,
        "completed_tracks": 0,
        "spotify_search_requests": 0,
        "tracks_using_second_search": 0,
        "first_search_zero_candidates": 0,
        "accepted_all": 0,
        "accepted_reference": 0,
        "stopped_early": False,
        "stop_reason": None,
        "retry_after_seconds": None,
        "retrieval_signal_counts": {},
        "tracks": [],
    }

    original_get = spotify._spotify_get
    last_request_at = [None]

    for index, song in enumerate(songs):
        requests = []

        def logged_get(url, token, params, *args, **kwargs):
            if "/search" in url:
                now = time.monotonic()
                if last_request_at[0] is not None and delay_seconds > 0:
                    wait = delay_seconds - (now - last_request_at[0])
                    if wait > 0:
                        time.sleep(wait)
                response = original_get(url, token, params, *args, **kwargs)
                last_request_at[0] = time.monotonic()
                items = [] if response is None else response.json().get("tracks", {}).get("items", [])
                requests.append({
                    "query": params.get("q"),
                    "limit": params.get("limit"),
                    "candidate_count": len(items),
                    "candidates": [_candidate(item) for item in items],
                })
                report["spotify_search_requests"] += 1
                return response
            return original_get(url, token, params, *args, **kwargs)

        diagnostics: dict = {}
        try:
            spotify._spotify_get = logged_get
            accepted = spotify.search_track(
                access_token,
                song["title"],
                [song["artist"]],
                "",
                diagnostics=diagnostics,
            )
        except spotify.SpotifyRateLimitError as error:
            report["stopped_early"] = True
            report["stop_reason"] = "SPOTIFY_RATE_LIMIT"
            report["retry_after_seconds"] = _retry_after(error)
            break
        finally:
            spotify._spotify_get = original_get

        is_reference = _song_key(song) not in missing_keys
        signals = list(diagnostics.get("signals", []))
        for signal in signals:
            report.setdefault("retrieval_signal_counts", {})[signal] = (
                report.setdefault("retrieval_signal_counts", {}).get(signal, 0) + 1
            )

        if requests and requests[0]["candidate_count"] == 0:
            report["first_search_zero_candidates"] += 1
        if len(requests) > 1:
            report["tracks_using_second_search"] += 1
        if accepted:
            report["accepted_all"] += 1
            if is_reference:
                report["accepted_reference"] += 1

        report["tracks"].append({
            "input_index": index,
            "source_title": song["title"],
            "source_artist": song["artist"],
            "tmm_reference_success": is_reference,
            "spotify_track_id": accepted,
            "accepted": bool(accepted),
            "search_request_count": len(requests),
            "searches": requests,
            "diagnostics": diagnostics,
        })
        report["completed_tracks"] += 1

    completed_reference = sum(
        row["tmm_reference_success"] for row in report["tracks"]
    )
    report["completed_reference_tracks"] = completed_reference
    report["acceptance_rate_reference"] = (
        report["accepted_reference"] / completed_reference if completed_reference else 0
    )
    report["acceptance_rate_all"] = (
        report["accepted_all"] / report["completed_tracks"] if report["completed_tracks"] else 0
    )

    full_reference_run = (
        not report["stopped_early"] and completed_reference == reference_total
    )
    report["full_reference_run"] = full_reference_run
    report["delta_from_baseline"] = (
        report["accepted_reference"] - baseline_accepted
        if full_reference_run and baseline_accepted is not None
        else None
    )
    return report


def print_summary(report: dict) -> None:
    print("\n=== Production Retrieval Benchmark ===")
    print(f"Read only: {report['read_only']}")
    print(f"Completed: {report['completed_tracks']}/{report['total_source_tracks']}")
    print(f"Spotify Search requests: {report['spotify_search_requests']}")
    print(f"First-search zero candidates: {report['first_search_zero_candidates']}")
    print(f"Tracks using search #2: {report['tracks_using_second_search']}")
    print(f"Accepted, all source rows: {report['accepted_all']}/{report['completed_tracks']}")
    print(
        "Accepted, TuneMyMusic reference-success set: "
        f"{report['accepted_reference']}/{report['completed_reference_tracks']} "
        f"({report['acceptance_rate_reference']:.1%})"
    )
    baseline = report.get("baseline_reference_accepted")
    delta = report.get("delta_from_baseline")
    if baseline is not None:
        if delta is None:
            print(f"Baseline: {baseline}/{report['reference_success_tracks']} (comparison pending full run)")
        else:
            sign = "+" if delta >= 0 else ""
            print(
                f"Baseline: {baseline}/{report['reference_success_tracks']} | "
                f"change: {sign}{delta} tracks"
            )
    if report.get("retrieval_signal_counts"):
        print("Retrieval signals:")
        for name, count in sorted(report["retrieval_signal_counts"].items()):
            print(f"  {name}: {count}")
    if report["stopped_early"]:
        print(
            f"STOPPED: {report['stop_reason']} "
            f"retry_after={report['retry_after_seconds']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only benchmark of the production retrieval policy"
    )
    parser.add_argument("input")
    parser.add_argument("--missing-reference")
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--baseline-accepted", type=int)
    parser.add_argument("--json", default="production_retrieval_benchmark.json")
    args = parser.parse_args()

    songs = parse_lines(args.input)
    missing = parse_lines(args.missing_reference) if args.missing_reference else []
    report = benchmark_production(
        args.access_token,
        songs,
        missing_reference=missing,
        delay_seconds=args.delay_seconds,
        baseline_accepted=args.baseline_accepted,
    )
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print_summary(report)
    print(f"JSON report: {args.json}")
    if report["stopped_early"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
