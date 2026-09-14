"""Read-only diagnostic for TuneMyMusic-success tracks rejected by matcher replay.

This script never writes playlists and never calls the live Spotify API. It
reuses the saved retrieval benchmark candidates, filters out TuneMyMusic's
known missing tracks, and replays the current matcher while preserving
matcher diagnostics and output.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from io import StringIO
from pathlib import Path

from . import spotify


def _load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _source_key(title: str, artist: str) -> str:
    return f"{title} - {artist}"


def _load_missing(path: str) -> set[str]:
    return {
        line.strip()
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }


def _saved_candidate(candidate: dict) -> dict:
    return {
        "id": candidate.get("spotify_track_id"),
        "name": candidate.get("title", ""),
        "artists": [{"name": name} for name in candidate.get("artists", [])],
        "album": {"name": candidate.get("album", "")},
        "external_ids": {"isrc": candidate["isrc"]} if candidate.get("isrc") else {},
    }


def _collect_candidates(entry: dict) -> list[dict]:
    candidates: dict[str, dict] = {}
    for strategy in entry.get("strategies", {}).values():
        for candidate in strategy.get("candidates", []):
            track_id = candidate.get("spotify_track_id")
            if track_id and track_id not in candidates:
                candidates[track_id] = _saved_candidate(candidate)
    return list(candidates.values())


def _replay_one(song: dict[str, str], items: list[dict]) -> dict:
    class Response:
        def __init__(self, response_items: list[dict]):
            self.items = response_items

        def json(self):
            return {"tracks": {"items": self.items}}

    original_get = spotify._spotify_get
    calls = 0
    diagnostics: dict = {}
    output = StringIO()

    def fake_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response(items if calls == 1 else [])

    try:
        spotify._spotify_get = fake_get
        with contextlib.redirect_stdout(output):
            accepted = spotify.search_track(
                "diagnostic",
                song["title"],
                [song["artist"]],
                "",
                diagnostics=diagnostics,
            )
    finally:
        spotify._spotify_get = original_get

    return {
        "accepted_track_id": accepted,
        "matcher_diagnostics": diagnostics,
        "matcher_output": output.getvalue().splitlines(),
        "replay_spotify_search_calls": calls,
    }


def diagnose(
    retrieval_report_path: str,
    matcher_replay_path: str,
    missing_path: str,
) -> dict:
    retrieval = _load_json(retrieval_report_path)
    replay = _load_json(matcher_replay_path)
    missing = _load_missing(missing_path)

    old_failed_indices = {
        row.get("input_index")
        for row in replay.get("tracks", [])
        if not row.get("accepted_track_ids")
    }

    target_entries = [
        entry
        for entry in retrieval.get("tracks", [])
        if entry.get("input_index") in old_failed_indices
        and _source_key(entry.get("source_title", ""), entry.get("source_artist", ""))
        not in missing
    ]

    rows = []
    unique_candidate_ids: set[str] = set()

    for entry in target_entries:
        items = _collect_candidates(entry)
        unique_candidate_ids.update(
            item.get("id") for item in items if item.get("id")
        )
        song = {
            "title": entry.get("source_title", ""),
            "artist": entry.get("source_artist", ""),
        }

        if not items:
            replay_result = {
                "accepted_track_id": None,
                "matcher_diagnostics": {
                    "category": "NO_SAVED_CANDIDATES",
                    "candidates_returned": 0,
                },
                "matcher_output": [],
                "replay_spotify_search_calls": 0,
            }
        else:
            replay_result = _replay_one(song, items)

        rows.append({
            "input_index": entry.get("input_index"),
            "source_title": song["title"],
            "source_artist": song["artist"],
            "saved_candidate_count": len(items),
            "candidates": [
                {
                    "spotify_track_id": item.get("id"),
                    "title": item.get("name", ""),
                    "artists": [
                        artist.get("name", "")
                        for artist in item.get("artists", [])
                    ],
                    "album": item.get("album", {}).get("name", ""),
                    "isrc": (item.get("external_ids") or {}).get("isrc"),
                }
                for item in items
            ],
            **replay_result,
        })

    newly_accepted = [row for row in rows if row["accepted_track_id"]]
    no_candidates = [row for row in rows if not row["saved_candidate_count"]]
    still_rejected = [
        row
        for row in rows
        if row["saved_candidate_count"] and not row["accepted_track_id"]
    ]

    source_total = retrieval.get("total", len(retrieval.get("tracks", [])))
    success_count = source_total - len(missing)
    old_accepted_count = success_count - len(rows)

    return {
        "benchmark_scope": "TuneMyMusic success set only",
        "tunemymusic_source_total": source_total,
        "tunemymusic_missing_count": len(missing),
        "tunemymusic_success_count": success_count,
        "old_replay_accepted_in_success_set": old_accepted_count,
        "old_replay_failed_in_success_set": len(rows),
        "old_replay_failed_with_no_saved_candidates": len(no_candidates),
        "old_replay_failed_with_saved_candidates": len(rows) - len(no_candidates),
        "newly_accepted_by_current_matcher": len(newly_accepted),
        "current_matcher_accepted_in_success_set": old_accepted_count + len(newly_accepted),
        "current_matcher_acceptance_rate": (
            (old_accepted_count + len(newly_accepted)) / success_count
            if success_count else 0
        ),
        "still_rejected_with_saved_candidates": len(still_rejected),
        "unique_saved_candidate_ids": len(unique_candidate_ids),
        "tracks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    args = parser.parse_args()

    report = diagnose(
        args.retrieval_report,
        args.matcher_replay,
        args.missing,
    )
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"TuneMyMusic success benchmark: {report['tunemymusic_success_count']}")
    print(f"Old replay accepted: {report['old_replay_accepted_in_success_set']}")
    print(f"Newly accepted by current matcher: {report['newly_accepted_by_current_matcher']}")
    print(f"Current matcher accepted: {report['current_matcher_accepted_in_success_set']}")
    print(f"Current matcher acceptance rate: {report['current_matcher_acceptance_rate']:.4f}")
    print(f"Still rejected with candidates: {report['still_rejected_with_saved_candidates']}")


if __name__ == "__main__":
    main()
