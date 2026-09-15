"""Offline replay of saved track-only candidates as production query #2.

Uses the existing retrieval benchmark artifact and current matcher. No Spotify
API calls are made. MusicBrainz may be used by the matcher as normal.
"""

from __future__ import annotations

import argparse
import contextlib
import json
from io import StringIO
from pathlib import Path

from . import spotify


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _missing(path: str) -> set[str]:
    return {
        line.strip()
        for line in Path(path).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    }


def _key(title: str, artist: str) -> str:
    return f"{title} - {artist}"


def _saved(candidate: dict) -> dict:
    return {
        "id": candidate.get("spotify_track_id"),
        "name": candidate.get("title", ""),
        "artists": [{"name": name} for name in candidate.get("artists", [])],
        "album": {"name": candidate.get("album", "")},
        "external_ids": {"isrc": candidate["isrc"]} if candidate.get("isrc") else {},
        "duration_ms": candidate.get("duration_ms"),
    }


def _replay(song: dict[str, str], second_items: list[dict]) -> dict:
    class Response:
        def __init__(self, items):
            self.items = items
        def json(self):
            return {"tracks": {"items": self.items}}

    original_get = spotify._spotify_get
    calls = 0
    diagnostics = {}
    output = StringIO()

    def fake_get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return Response([])
        if calls == 2:
            return Response(second_items)
        return Response([])

    try:
        spotify._spotify_get = fake_get
        with contextlib.redirect_stdout(output):
            accepted = spotify.search_track(
                "offline-replay",
                song["title"],
                [song["artist"]],
                "",
                diagnostics=diagnostics,
            )
    finally:
        spotify._spotify_get = original_get

    rank = None
    if accepted:
        for i, item in enumerate(second_items, 1):
            if item.get("id") == accepted:
                rank = i
                break
    return {
        "accepted_track_id": accepted,
        "accepted_rank": rank,
        "matcher_diagnostics": diagnostics,
        "matcher_output": output.getvalue().splitlines(),
    }


def diagnose(retrieval_path: str, replay_path: str, missing_path: str) -> dict:
    retrieval = _load(retrieval_path)
    replay = _load(replay_path)
    missing = _missing(missing_path)
    failed = {
        row.get("input_index")
        for row in replay.get("tracks", [])
        if not row.get("accepted_track_ids")
    }

    rows = []
    for entry in retrieval.get("tracks", []):
        if entry.get("input_index") not in failed:
            continue
        if _key(entry.get("source_title", ""), entry.get("source_artist", "")) in missing:
            continue
        strategies = entry.get("strategies", {})
        artist_bound_count = sum(
            strategies.get(name, {}).get("candidate_count", 0)
            for name in ("structured_page_0", "simplified_title")
        )
        if artist_bound_count:
            continue
        raw = strategies.get("track_only", {}).get("candidates", [])
        items = [_saved(candidate) for candidate in raw]
        song = {
            "title": entry.get("source_title", ""),
            "artist": entry.get("source_artist", ""),
        }
        result = _replay(song, items) if items else {
            "accepted_track_id": None,
            "accepted_rank": None,
            "matcher_diagnostics": {"category": "NO_SAVED_TRACK_ONLY_CANDIDATES"},
            "matcher_output": [],
        }
        rows.append({
            "input_index": entry.get("input_index"),
            "source_title": song["title"],
            "source_artist": song["artist"],
            "track_only_candidate_count": len(items),
            "candidates": raw,
            **result,
        })
        print(
            f"{song['title']} - {song['artist']}: "
            f"candidates={len(items)} accepted={result['accepted_track_id'] or 'no'}"
        )

    accepted = [row for row in rows if row["accepted_track_id"]]
    return {
        "scope": "TuneMyMusic-success old replay failures with zero artist-bound candidates",
        "spotify_api_calls": 0,
        "target_count": len(rows),
        "tracks_with_saved_track_only_candidates": sum(bool(row["track_only_candidate_count"]) for row in rows),
        "accepted_by_current_matcher": len(accepted),
        "projected_total_if_added_to_current_97": 97 + len(accepted),
        "projected_rate_if_added_to_current_97": (97 + len(accepted)) / 140,
        "tracks": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    report = diagnose(args.retrieval_report, args.matcher_replay, args.missing)
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Targets: {report['target_count']}")
    print(f"Accepted: {report['accepted_by_current_matcher']}")
    print(f"Projected total: {report['projected_total_if_added_to_current_97']}/140")


if __name__ == "__main__":
    main()
