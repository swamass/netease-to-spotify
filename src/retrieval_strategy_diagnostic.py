"""Compare broad second-query Spotify retrieval strategies without playlist writes.

This first-stage diagnostic only compares candidate pools. It intentionally
avoids MusicBrainz and matcher replay so strategy selection is fast and clean.
A second, narrower diagnostic can validate the chosen strategy end-to-end.
"""

from __future__ import annotations

import argparse
import json
import time
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


def _quick_signals(song: dict[str, str], items: list[dict]) -> dict:
    title_matches = []
    exact_title_matches = []
    cross_script_uncertain = []
    hard_artist_conflicts = []
    for rank, item in enumerate(items, 1):
        title_match = spotify._title_match(song["title"], item.get("name", ""))
        title_exact = spotify._normalize_text(spotify._title_core(song["title"])) in spotify._title_keys(item.get("name", ""))
        artist_score, _, artist_reliable = spotify._artist_match_score(
            [song["artist"]], item.get("artists", [])
        )
        if title_match:
            title_matches.append(rank)
        if title_exact:
            exact_title_matches.append(rank)
        if title_match and artist_score == 0.35 and not artist_reliable:
            cross_script_uncertain.append(rank)
        if title_match and artist_score == 0:
            hard_artist_conflicts.append(rank)
    return {
        "title_match_ranks": title_matches,
        "exact_title_match_ranks": exact_title_matches,
        "cross_script_uncertain_ranks": cross_script_uncertain,
        "hard_artist_conflict_ranks": hard_artist_conflicts,
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
        "stage": "candidate-pool comparison only",
        "target_count": len(targets),
        "spotify_searches": 0,
        "strategies": {
            name: {
                "tracks_with_candidates": 0,
                "tracks_with_title_match": 0,
                "tracks_with_exact_title_match": 0,
                "tracks_with_cross_script_uncertain_title_match": 0,
                "tracks_with_hard_artist_conflict_title_match": 0,
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
            signals = _quick_signals(song, items)
            stats = report["strategies"][strategy_name]
            stats["tracks_with_candidates"] += bool(items)
            stats["tracks_with_title_match"] += bool(signals["title_match_ranks"])
            stats["tracks_with_exact_title_match"] += bool(signals["exact_title_match_ranks"])
            stats["tracks_with_cross_script_uncertain_title_match"] += bool(signals["cross_script_uncertain_ranks"])
            stats["tracks_with_hard_artist_conflict_title_match"] += bool(signals["hard_artist_conflict_ranks"])
            row["strategies"][strategy_name] = {
                "query": params["q"],
                "candidate_count": len(items),
                "candidates": [_candidate(item, rank) for rank, item in enumerate(items[:15], 1)],
                **signals,
            }
        report["tracks"].append(row)
        print(
            f"[{target_index + 1}/{len(targets)}] {song['title']} - {song['artist']} | "
            + " | ".join(
                f"{name}: candidates={row['strategies'][name]['candidate_count']} "
                f"title_match={bool(row['strategies'][name]['title_match_ranks'])}"
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
        print(name + ": " + json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
