"""Read-only diagnostic for TuneMyMusic-success tracks rejected by matcher replay.

This script never writes playlists. It reuses the saved retrieval benchmark,
filters out TuneMyMusic's known missing tracks, hydrates saved Spotify candidates
with current track metadata (including duration_ms), and replays the current
matcher while preserving diagnostics and matcher output.
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


def _chunks(values: list[str], size: int = 50):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _hydrate_candidates(access_token: str, candidate_ids: list[str]) -> dict[str, dict]:
    hydrated: dict[str, dict] = {}
    for batch in _chunks(candidate_ids, 50):
        response = spotify._spotify_get(
            f"{spotify.SPOTIFY_API_URL}/tracks",
            access_token,
            {"ids": ",".join(batch)},
        )
        if response is None:
            continue
        for item in response.json().get("tracks", []):
            if item and item.get("id"):
                hydrated[item["id"]] = item
    return hydrated


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
    access_token: str,
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

    saved_candidates_by_index: dict[int, list[dict]] = {}
    candidate_ids: list[str] = []
    seen_ids: set[str] = set()
    for entry in target_entries:
        index = entry.get("input_index")
        candidates = _collect_candidates(entry)
        saved_candidates_by_index[index] = candidates
        for candidate in candidates:
            track_id = candidate.get("id")
            if track_id and track_id not in seen_ids:
                seen_ids.add(track_id)
                candidate_ids.append(track_id)

    hydrated = _hydrate_candidates(access_token, candidate_ids)

    rows = []
    for entry in target_entries:
        index = entry.get("input_index")
        saved_candidates = saved_candidates_by_index.get(index, [])
        items = [hydrated.get(item.get("id"), item) for item in saved_candidates]
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
            "input_index": index,
            "source_title": song["title"],
            "source_artist": song["artist"],
            "saved_candidate_count": len(items),
            "hydrated_candidate_count": sum(
                bool(item.get("id") in hydrated) for item in saved_candidates
            ),
            "candidates": [
                {
                    "spotify_track_id": item.get("id"),
                    "title": item.get("name", ""),
                    "artists": [artist.get("name", "") for artist in item.get("artists", [])],
                    "album": item.get("album", {}).get("name", ""),
                    "duration_ms": item.get("duration_ms"),
                    "isrc": (item.get("external_ids") or {}).get("isrc"),
                }
                for item in items
            ],
            **replay_result,
        })

    accepted_after_hydration = [row for row in rows if row["accepted_track_id"]]
    no_candidates = [row for row in rows if not row["saved_candidate_count"]]
    still_rejected = [
        row for row in rows
        if row["saved_candidate_count"] and not row["accepted_track_id"]
    ]

    return {
        "benchmark_scope": "TuneMyMusic success set only",
        "tunemymusic_source_total": retrieval.get("total", len(retrieval.get("tracks", []))),
        "tunemymusic_missing_count": len(missing),
        "tunemymusic_success_count": (
            retrieval.get("total", len(retrieval.get("tracks", []))) - len(missing)
        ),
        "old_replay_failed_in_success_set": len(rows),
        "old_replay_failed_with_no_saved_candidates": len(no_candidates),
        "old_replay_failed_with_saved_candidates": len(rows) - len(no_candidates),
        "accepted_after_candidate_hydration": len(accepted_after_hydration),
        "still_rejected_after_candidate_hydration": len(still_rejected),
        "unique_saved_candidate_ids": len(candidate_ids),
        "hydrated_candidate_ids": len(hydrated),
        "tracks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--json", required=True)
    args = parser.parse_args()

    report = diagnose(
        args.access_token,
        args.retrieval_report,
        args.matcher_replay,
        args.missing,
    )
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"TuneMyMusic success benchmark: {report['tunemymusic_success_count']}")
    print(f"Old replay failures in success set: {report['old_replay_failed_in_success_set']}")
    print(f"Accepted after candidate hydration: {report['accepted_after_candidate_hydration']}")
    print(f"Still rejected after hydration: {report['still_rejected_after_candidate_hydration']}")


if __name__ == "__main__":
    main()
