"""Fast read-only probe of alternative Spotify query forms.

This tool measures retrieval only. It never writes playlists and does not call
MusicBrainz or the matcher. Candidate metadata is saved for a second-stage
safety analysis.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from . import spotify
from .retrieval_strategy_diagnostic import _load_json, _load_missing, _query_specs, _target_entries, _candidate


def probe(access_token: str, retrieval_path: str, replay_path: str, missing_path: str, delay: float = 0.2) -> dict:
    retrieval = _load_json(retrieval_path)
    replay = _load_json(replay_path)
    missing = _load_missing(missing_path)
    targets = _target_entries(retrieval, replay, missing)
    report = {
        "target_count": len(targets),
        "spotify_searches": 0,
        "strategies": {},
        "tracks": [],
    }
    strategy_names = ("loose_artist_text", "plain_text", "track_only_50")
    for name in strategy_names:
        report["strategies"][name] = {
            "tracks_with_candidates": 0,
            "rank1_title_match": 0,
            "any_title_match": 0,
        }

    for index, entry in enumerate(targets, 1):
        song = {"title": entry.get("source_title", ""), "artist": entry.get("source_artist", "")}
        row = {"input_index": entry.get("input_index"), **song, "strategies": {}}
        for strategy_name, params in _query_specs(song["title"], song["artist"]).items():
            if report["spotify_searches"] and delay > 0:
                time.sleep(delay)
            response = spotify._spotify_get(f"{spotify.SPOTIFY_API_URL}/search", access_token, params)
            report["spotify_searches"] += 1
            items = [] if response is None else response.json().get("tracks", {}).get("items", [])
            title_matches = [spotify._title_match(song["title"], item.get("name", "")) for item in items]
            if items:
                report["strategies"][strategy_name]["tracks_with_candidates"] += 1
            if title_matches and title_matches[0]:
                report["strategies"][strategy_name]["rank1_title_match"] += 1
            if any(title_matches):
                report["strategies"][strategy_name]["any_title_match"] += 1
            row["strategies"][strategy_name] = {
                "query": params["q"],
                "candidate_count": len(items),
                "rank1_title_match": bool(title_matches and title_matches[0]),
                "title_match_ranks": [rank for rank, matched in enumerate(title_matches, 1) if matched],
                "candidates": [_candidate(item, rank) for rank, item in enumerate(items[:20], 1)],
            }
        report["tracks"].append(row)
        print(f"[{index}/{len(targets)}] {song['title']} - {song['artist']}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    parser.add_argument("--delay", type=float, default=0.2)
    args = parser.parse_args()
    token = spotify.get_access_token(
        os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"], os.environ["SPOTIFY_REFRESH_TOKEN"]
    )
    report = probe(token, args.retrieval_report, args.matcher_replay, args.missing, args.delay)
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["strategies"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
