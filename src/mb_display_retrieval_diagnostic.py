"""Read-only validation of MusicBrainz display-name retrieval.

Targets TuneMyMusic-success failures whose saved artist-bound queries returned
zero candidates. For each target we derive one conservative Latin artist name
from MusicBrainz, perform at most one Spotify Search, and save enough evidence
to judge whether query #2 recall improves. No playlist writes are performed.
"""

from __future__ import annotations

import argparse
import json
import os
import time
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


def _target_entries(retrieval: dict, replay: dict, missing: set[str]) -> list[dict]:
    failed = {
        row.get("input_index")
        for row in replay.get("tracks", [])
        if not row.get("accepted_track_ids")
    }
    targets = []
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
        if artist_bound_count == 0:
            targets.append(entry)
    return targets


def _candidate(item: dict, rank: int, source_title: str, alternate: str) -> dict:
    item_name = item.get("name", "")
    item_artists = item.get("artists", [])
    item_album = item.get("album", {}).get("name", "")
    artist_names = [artist.get("name", "") for artist in item_artists]
    exact_artist = any(
        spotify._normalize_text(name) == spotify._normalize_text(alternate)
        for name in artist_names
    )
    title_match = spotify._title_match(source_title, item_name)
    title_exact = (
        spotify._normalize_text(spotify._title_core(source_title))
        in spotify._title_keys(item_name)
    )
    version_conflicts = spotify._version_conflicts(
        source_title, "", item_name, item_album
    )
    return {
        "rank": rank,
        "spotify_track_id": item.get("id"),
        "title": item_name,
        "artists": artist_names,
        "album": item_album,
        "isrc": (item.get("external_ids") or {}).get("isrc"),
        "duration_ms": item.get("duration_ms"),
        "title_match": title_match,
        "title_exact": title_exact,
        "alternate_artist_exact": exact_artist,
        "version_conflicts": version_conflicts,
        "strong_retrieval_candidate": bool(
            item.get("id")
            and title_match
            and exact_artist
            and not version_conflicts
        ),
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
    delay_seconds: float = 1.0,
) -> dict:
    retrieval = _load(retrieval_path)
    replay = _load(replay_path)
    missing = _missing(missing_path)
    targets = _target_entries(retrieval, replay, missing)
    report = {
        "scope": "TuneMyMusic-success replay failures with zero saved artist-bound candidates",
        "target_count": len(targets),
        "completed_tracks": 0,
        "spotify_searches": 0,
        "alternate_available": 0,
        "tracks_with_candidates": 0,
        "tracks_with_strong_retrieval_candidate": 0,
        "stopped_early": False,
        "stop_reason": None,
        "tracks": [],
    }
    _write(output_path, report)

    for position, entry in enumerate(targets, 1):
        title = entry.get("source_title", "")
        artist = entry.get("source_artist", "")
        row = {
            "input_index": entry.get("input_index"),
            "source_title": title,
            "source_artist": artist,
            "alternate_artist": None,
            "query": None,
            "candidate_count": 0,
            "strong_candidate_ranks": [],
            "candidates": [],
        }
        alternate = spotify._musicbrainz_retrieval_artist_name(artist)
        row["alternate_artist"] = alternate
        if not alternate:
            report["tracks"].append(row)
            report["completed_tracks"] += 1
            _write(output_path, report)
            print(f"[{position}/{len(targets)}] {title} - {artist}: no trusted alternate")
            continue

        report["alternate_available"] += 1
        query = (
            f'track:"{spotify._spotify_query_value(title)}" '
            f'artist:"{spotify._spotify_query_value(alternate)}"'
        )
        row["query"] = query
        if report["spotify_searches"] and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            response = spotify._spotify_get(
                f"{spotify.SPOTIFY_API_URL}/search",
                access_token,
                {"q": query, "type": "track", "limit": 10},
            )
        except spotify.SpotifyRateLimitError:
            report["stopped_early"] = True
            report["stop_reason"] = "SPOTIFY_RATE_LIMIT"
            report["tracks"].append(row)
            _write(output_path, report)
            print(f"Stopped at [{position}/{len(targets)}] due to Spotify rate limit")
            break

        report["spotify_searches"] += 1
        items = [] if response is None else response.json().get("tracks", {}).get("items", [])
        candidates = [
            _candidate(item, rank, title, alternate)
            for rank, item in enumerate(items, 1)
        ]
        row["candidate_count"] = len(candidates)
        row["candidates"] = candidates
        row["strong_candidate_ranks"] = [
            item["rank"] for item in candidates if item["strong_retrieval_candidate"]
        ]
        if candidates:
            report["tracks_with_candidates"] += 1
        if row["strong_candidate_ranks"]:
            report["tracks_with_strong_retrieval_candidate"] += 1
        report["tracks"].append(row)
        report["completed_tracks"] += 1
        _write(output_path, report)
        print(
            f"[{position}/{len(targets)}] {title} - {artist}: "
            f"alternate={alternate} candidates={len(candidates)} "
            f"strong={row['strong_candidate_ranks']}"
        )

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("retrieval_report")
    parser.add_argument("matcher_replay")
    parser.add_argument("missing")
    parser.add_argument("--json", required=True)
    parser.add_argument("--delay", type=float, default=1.0)
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
    print(
        f"Completed {report['completed_tracks']}/{report['target_count']} | "
        f"alternate={report['alternate_available']} | "
        f"candidate_tracks={report['tracks_with_candidates']} | "
        f"strong={report['tracks_with_strong_retrieval_candidate']}"
    )


if __name__ == "__main__":
    main()
