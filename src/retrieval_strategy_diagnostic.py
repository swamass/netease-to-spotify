"""Compare broad second-query retrieval strategies without writing playlists.

Targets TuneMyMusic-success tracks whose saved artist-bound retrieval returned
no candidates. Each strategy performs one live Spotify Search, then replays the
returned candidates through the current matcher with the first query empty.
This approximates replacing only production query #2 while preserving matcher
safety and the two-search production budget.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import time
from io import StringIO
from pathlib import Path

from . import spotify


STRATEGY_NAMES = ("loose_artist_text", "plain_text", "track_only_50")


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


def _query_specs(title: str, artist: str) -> dict[str, dict]:
    title_q = spotify._spotify_query_value(title)
    artist_q = spotify._spotify_query_value(artist)
    return {
        "loose_artist_text": {
            "q": f'track:"{title_q}" {artist_q}',
            "type": "track",
            "limit": 20,
        },
        "plain_text": {
            "q": f'"{title_q}" {artist_q}',
            "type": "track",
            "limit": 20,
        },
        "track_only_50": {
            "q": f'track:"{title_q}"',
            "type": "track",
            "limit": 50,
        },
    }


def _candidate(item: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "spotify_track_id": item.get("id"),
        "title": item.get("name", ""),
        "artists": [artist.get("name", "") for artist in item.get("artists", [])],
        "album": item.get("album", {}).get("name", ""),
        "isrc": (item.get("external_ids") or {}).get("isrc"),
        "duration_ms": item.get("duration_ms"),
    }


def _replay_as_second_query(song: dict[str, str], items: list[dict]) -> dict:
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
        if calls == 1:
            return Response([])
        if calls == 2:
            return Response(items)
        return Response([])

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

    accepted_rank = None
    if accepted:
        for rank, item in enumerate(items, 1):
            if item.get("id") == accepted:
                accepted_rank = rank
                break
    return {
        "accepted_track_id": accepted,
        "accepted_rank": accepted_rank,
        "matcher_diagnostics": diagnostics,
        "matcher_output": output.getvalue().splitlines(),
    }


def _target_entries(retrieval: dict, replay: dict, missing: set[str]) -> list[dict]:
    failed_indices = {
        row.get("input_index")
        for row in replay.get("tracks", [])
        if not row.get("accepted_track_ids")
    }
    targets = []
    for entry in retrieval.get("tracks", []):
        if entry.get("input_index") not in failed_indices:
            continue
        if _source_key(entry.get("source_title", ""), entry.get("source_artist", "")) in missing:
            continue
        strategies = entry.get("strategies", {})
        artist_bound_count = sum(
            strategies.get(name, {}).get("candidate_count", 0)
            for name in ("structured_page_0", "simplified_title")
        )
        if artist_bound_count == 0:
            targets.append(entry)
    return targets


def diagnose(
    access_token: str,
    retrieval_path: str,
    replay_path: str,
    missing_path: str,
    delay_seconds: float = 0.25,
) -> dict:
    retrieval = _load_json(retrieval_path)
    replay = _load_json(replay_path)
    missing = _load_missing(missing_path)
    targets = _target_entries(retrieval, replay, missing)

    report = {
        "scope": "TuneMyMusic-success old replay failures with zero saved artist-bound candidates",
        "target_count": len(targets),
        "spotify_searches": 0,
        "strategies": {
            name: {
                "tracks_with_candidates": 0,
                "matcher_accepted": 0,
                "accepted_track_ids": [],
            }
            for name in STRATEGY_NAMES
        },
        "tracks": [],
    }

    for target_index, entry in enumerate(targets):
        song = {
            "title": entry.get("source_title", ""),
            "artist": entry.get("source_artist", ""),
        }
        row = {
            "input_index": entry.get("input_index"),
            "source_title": song["title"],
            "source_artist": song["artist"],
            "strategies": {},
        }
        for strategy_name, params in _query_specs(song["title"], song["artist"]).items():
            if report["spotify_searches"] and delay_seconds > 0:
                time.sleep(delay_seconds)
            response = spotify._spotify_get(
                f"{spotify.SPOTIFY_API_URL}/search",
                access_token,
                params,
            )
            report["spotify_searches"] += 1
            items = [] if response is None else response.json().get("tracks", {}).get("items", [])
            if items:
                report["strategies"][strategy_name]["tracks_with_candidates"] += 1
            replay_result = _replay_as_second_query(song, items)
            if replay_result["accepted_track_id"]:
                report["strategies"][strategy_name]["matcher_accepted"] += 1
                report["strategies"][strategy_name]["accepted_track_ids"].append(
                    replay_result["accepted_track_id"]
                )
            row["strategies"][strategy_name] = {
                "query": params["q"],
                "candidate_count": len(items),
                "candidates": [_candidate(item, rank) for rank, item in enumerate(items[:10], 1)],
                **replay_result,
            }
        report["tracks"].append(row)
        print(
            f"[{target_index + 1}/{len(targets)}] {song['title']} - {song['artist']} | "
            + " | ".join(
                f"{name}: candidates={row['strategies'][name]['candidate_count']} "
                f"accepted={'yes' if row['strategies'][name]['accepted_track_id'] else 'no'}"
                for name in STRATEGY_NAMES
            )
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()

    import os
    access_token = spotify.get_access_token(
        os.environ["SPOTIFY_CLIENT_ID"],
        os.environ["SPOTIFY_CLIENT_SECRET"],
        os.environ["SPOTIFY_REFRESH_TOKEN"],
    )
    report = diagnose(
        access_token,
        args.retrieval_report,
        args.matcher_replay,
        args.missing,
        delay_seconds=args.delay,
    )
    Path(args.json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Targets: {report['target_count']}")
    print(f"Spotify searches: {report['spotify_searches']}")
    for name, stats in report["strategies"].items():
        print(
            f"{name}: tracks_with_candidates={stats['tracks_with_candidates']} "
            f"matcher_accepted={stats['matcher_accepted']}"
        )


if __name__ == "__main__":
    main()
