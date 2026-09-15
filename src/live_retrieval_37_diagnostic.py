"""Read-only live diagnostic for the 37 zero artist-bound candidate tracks.

The historical benchmark already established that production's strict first
artist-bound retrieval returned no candidates for these tracks. To isolate the
new retrieval policy without needing source album metadata, this diagnostic
simulates an empty first Spotify search and sends only production query #2 to
the live Spotify API. It never writes playlists.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import time
from io import StringIO
from pathlib import Path

from . import spotify


BASELINE_ACCEPTED = 97
BENCHMARK_TOTAL = 140


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_missing(path: str) -> set[str]:
    return {
        line.strip()
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }


def _source_key(title: str, artist: str) -> str:
    return f"{title} - {artist}"


def _target_entries(retrieval: dict, replay: dict, missing: set[str]) -> list[dict]:
    old_failed_indices = {
        row.get("input_index")
        for row in replay.get("tracks", [])
        if not row.get("accepted_track_ids")
    }
    targets = []
    for entry in retrieval.get("tracks", []):
        if entry.get("input_index") not in old_failed_indices:
            continue
        if _source_key(
            entry.get("source_title", ""), entry.get("source_artist", "")
        ) in missing:
            continue
        strategies = entry.get("strategies", {})
        first_count = strategies.get("structured_page_0", {}).get(
            "candidate_count", 0
        )
        second_count = strategies.get("simplified_title", {}).get(
            "candidate_count", 0
        )
        if first_count == 0 and second_count == 0:
            targets.append(entry)
    return targets


class _EmptyResponse:
    def json(self):
        return {"tracks": {"items": []}}


def _candidate_summary(item: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "spotify_track_id": item.get("id"),
        "title": item.get("name", ""),
        "artists": [a.get("name", "") for a in item.get("artists", [])],
        "album": item.get("album", {}).get("name", ""),
        "isrc": (item.get("external_ids") or {}).get("isrc"),
        "duration_ms": item.get("duration_ms"),
    }


def _evaluate_one(access_token: str, song: dict[str, str]) -> dict:
    real_get = spotify._spotify_get
    search_calls = 0
    live_search_calls = 0
    live_query = None
    live_candidates: list[dict] = []
    diagnostics: dict = {}
    output = StringIO()

    def diagnostic_get(url: str, token: str, params: dict):
        nonlocal search_calls, live_search_calls, live_query, live_candidates
        if not url.endswith("/search"):
            return real_get(url, token, params)
        search_calls += 1
        if search_calls == 1:
            return _EmptyResponse()
        live_search_calls += 1
        live_query = str(params.get("q", ""))
        response = real_get(url, token, params)
        if response is not None:
            payload = response.json()
            live_candidates = payload.get("tracks", {}).get("items", [])
        return response

    try:
        spotify._spotify_get = diagnostic_get
        with contextlib.redirect_stdout(output):
            accepted = spotify.search_track(
                access_token,
                song["title"],
                [song["artist"]],
                "",
                diagnostics=diagnostics,
            )
    finally:
        spotify._spotify_get = real_get

    return {
        "accepted_track_id": accepted,
        "logical_search_calls": search_calls,
        "live_spotify_search_calls": live_search_calls,
        "live_query": live_query,
        "candidates": [
            _candidate_summary(item, rank)
            for rank, item in enumerate(live_candidates, 1)
        ],
        "matcher_diagnostics": diagnostics,
        "matcher_output": output.getvalue().splitlines(),
    }


def _write(path: str, report: dict) -> None:
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def diagnose(
    access_token: str,
    retrieval_path: str,
    replay_path: str,
    missing_path: str,
    output_path: str,
    delay_seconds: float = 0.8,
) -> dict:
    retrieval = _load_json(retrieval_path)
    replay = _load_json(replay_path)
    missing = _load_missing(missing_path)
    targets = _target_entries(retrieval, replay, missing)

    report = {
        "scope": "TuneMyMusic-success old replay failures with zero saved artist-bound candidates",
        "method": "historical strict query #1 forced empty; current production query #2 sent live",
        "playlist_writes": 0,
        "target_count": len(targets),
        "completed_tracks": 0,
        "live_spotify_searches": 0,
        "accepted_from_target_set": 0,
        "baseline_accepted_before_retrieval_policy": BASELINE_ACCEPTED,
        "projected_total": BASELINE_ACCEPTED,
        "projected_rate": BASELINE_ACCEPTED / BENCHMARK_TOTAL,
        "stopped_early": False,
        "stop_reason": None,
        "retry_after_seconds": None,
        "tracks": [],
    }
    _write(output_path, report)

    for position, entry in enumerate(targets, 1):
        if report["live_spotify_searches"] and delay_seconds > 0:
            time.sleep(delay_seconds)
        song = {
            "title": entry.get("source_title", ""),
            "artist": entry.get("source_artist", ""),
        }
        try:
            result = _evaluate_one(access_token, song)
        except spotify.SpotifyRateLimitError as error:
            report["stopped_early"] = True
            report["stop_reason"] = "SPOTIFY_RATE_LIMIT"
            report["retry_after_seconds"] = getattr(
                error, "retry_after_seconds", None
            )
            _write(output_path, report)
            print(
                f"Stopped before [{position}/{len(targets)}] "
                f"{song['title']} - {song['artist']} due to Spotify rate limit."
            )
            break

        report["completed_tracks"] += 1
        report["live_spotify_searches"] += result["live_spotify_search_calls"]
        if result["accepted_track_id"]:
            report["accepted_from_target_set"] += 1
        report["projected_total"] = (
            BASELINE_ACCEPTED + report["accepted_from_target_set"]
        )
        report["projected_rate"] = report["projected_total"] / BENCHMARK_TOTAL
        report["tracks"].append({
            "input_index": entry.get("input_index"),
            "source_title": song["title"],
            "source_artist": song["artist"],
            **result,
        })
        _write(output_path, report)
        print(
            f"[{position}/{len(targets)}] {song['title']} - {song['artist']} | "
            f"candidates={len(result['candidates'])} | "
            f"accepted={result['accepted_track_id'] or 'no'}"
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    parser.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args()

    token = spotify.get_access_token(
        os.environ["SPOTIFY_CLIENT_ID"],
        os.environ["SPOTIFY_CLIENT_SECRET"],
        os.environ["SPOTIFY_REFRESH_TOKEN"],
    )
    report = diagnose(
        token,
        args.retrieval_report,
        args.matcher_replay,
        args.missing,
        args.json,
        delay_seconds=args.delay,
    )
    _write(args.json, report)
    print(f"Targets: {report['target_count']}")
    print(f"Completed: {report['completed_tracks']}")
    print(f"Live Spotify searches: {report['live_spotify_searches']}")
    print(f"Accepted from target set: {report['accepted_from_target_set']}")
    print(f"Projected total: {report['projected_total']}/{BENCHMARK_TOTAL}")
    print(f"Projected rate: {report['projected_rate']:.4f}")


if __name__ == "__main__":
    main()
