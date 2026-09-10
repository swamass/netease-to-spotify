"""Read-only Spotify retrieval benchmark; never writes playlists."""

import argparse
import json
import re
import time
from pathlib import Path

from . import spotify


def parse_lines(path: str) -> list[dict[str, str]]:
    songs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or " - " not in line:
            continue
        title, artist = line.rsplit(" - ", 1)
        if title.strip() and artist.strip():
            songs.append({"title": title.strip(), "artist": artist.strip()})
    return songs


def simplified_title(title: str) -> str:
    return re.sub(r"\s*[-(（]\s*(?:album|single)\s+version\s*[)）]?\s*$", "", title, flags=re.IGNORECASE).strip()


def build_queries(song: dict[str, str]) -> dict[str, dict]:
    title = spotify._spotify_query_value(song["title"])
    artist = spotify._spotify_query_value(song["artist"])
    simple = spotify._spotify_query_value(simplified_title(song["title"]))
    return {
        "structured_page_0": {"q": f'track:"{title}" artist:"{artist}"', "limit": 10, "offset": 0},
        "structured_page_10": {"q": f'track:"{title}" artist:"{artist}"', "limit": 10, "offset": 10},
        "simplified_title": {"q": f'track:"{simple}" artist:"{artist}"', "limit": 10, "offset": 0},
        "track_only": {"q": f'track:"{title}"', "limit": 10, "offset": 0},
    }


def _candidate(item: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "spotify_track_id": item.get("id"),
        "title": item.get("name", ""),
        "artists": [artist.get("name", "") for artist in item.get("artists", [])],
        "album": item.get("album", {}).get("name", ""),
        "isrc": (item.get("external_ids") or {}).get("isrc"),
    }


def _response_items(response) -> list[dict]:
    if response is None:
        return []
    return response.json().get("tracks", {}).get("items", [])


def _matcher_accepts(access_token: str, song: dict[str, str], items: list[dict]) -> list[str]:
    class Response:
        def json(self):
            return {"tracks": {"items": self.items}}

        def __init__(self, response_items):
            self.items = response_items

    original_get = spotify._spotify_get
    original_mb_get = spotify._musicbrainz_get
    try:
        spotify._spotify_get = lambda *_args, **_kwargs: Response(items)
        spotify._musicbrainz_get = lambda *_args, **_kwargs: None
        accepted = spotify.search_track(
            access_token, song["title"], [song["artist"]], ""
        )
        return [accepted] if accepted else []
    finally:
        spotify._spotify_get = original_get
        spotify._musicbrainz_get = original_mb_get


def _request_key(params: dict) -> tuple:
    return tuple(sorted((key, params.get(key)) for key in ("q", "type", "limit", "offset", "market")))


def _ambiguous_artist_field(artist: str) -> bool:
    return bool(re.search(r"[,/]|\s(?:and|&|with|feat\.?|featuring)\s", artist, re.IGNORECASE))


def _artist_alias(source_artist: str, cache: dict) -> dict | None:
    key = spotify._normalize_text(source_artist)
    if key in cache:
        return cache[key]
    ids = spotify._musicbrainz_artist_ids(source_artist)
    if len(ids) != 1:
        cache[key] = None
        return None
    mbid = next(iter(ids))
    data = spotify._musicbrainz_get("artist/" + mbid, {"fmt": "json", "inc": "aliases"})
    names = spotify._musicbrainz_artist_names(mbid) if data else set()
    if spotify._normalize_text(source_artist) not in names:
        cache[key] = None
        return None
    display_names = [data.get("name", ""), data.get("sort-name", "")]
    display_names.extend(alias.get("name", "") for alias in data.get("aliases", []))
    alternates = [name for name in display_names if name and spotify._normalize_text(name) != key]
    latin = [name for name in alternates if not any(ord(char) > 127 for char in name)]
    result = {"mbid": mbid, "canonical_name": data.get("name", ""), "alternate": (latin or alternates or [None])[0]}
    cache[key] = result if result["alternate"] else None
    return cache[key]


def benchmark(access_token: str, songs: list[dict[str, str]], delay_seconds: float = 0.25) -> dict:
    report = {
        "total": len(songs), "logical_searches": 0,
        "real_spotify_searches": 0, "cache_hits": 0, "tracks": [],
        "alias_attempted": 0, "alias_skipped": 0,
        "alias_spotify_candidates_found": 0, "alias_zero_candidates": 0,
        "alias_matcher_accepted": 0, "unique_musicbrainz_artist_lookups": 0,
    }
    cache = {}
    artist_cache = {}
    for song in songs:
        entry = {"source_title": song["title"], "source_artist": song["artist"], "strategies": {}}
        for strategy, params in build_queries(song).items():
            report["logical_searches"] += 1
            request_params = {"q": params["q"], "type": "track", "limit": params["limit"], "offset": params["offset"]}
            key = _request_key(request_params)
            reused = key in cache
            if reused:
                response = cache[key]
                report["cache_hits"] += 1
            else:
                if report["real_spotify_searches"] and delay_seconds > 0:
                    time.sleep(delay_seconds)
                response = spotify._spotify_get(
                    f"{spotify.SPOTIFY_API_URL}/search", access_token, request_params
                )
                cache[key] = response
                report["real_spotify_searches"] += 1
            items = _response_items(response)
            candidates = [_candidate(item, index) for index, item in enumerate(items, 1)]
            entry["strategies"][strategy] = {
                "query": params["q"], "offset": params["offset"],
                "candidate_count": len(candidates), "candidates": candidates,
                "cache_hit": reused,
                "accepted_track_ids": _matcher_accepts(access_token, song, items),
            }
        if entry["strategies"]["structured_page_0"]["candidate_count"] == 0:
            if _ambiguous_artist_field(song["artist"]):
                report["alias_skipped"] += 1
                entry["strategies"]["artist_alias"] = {"skipped": True, "reason": "ambiguous multi-artist input"}
                report["tracks"].append(entry)
                continue
            alias = _artist_alias(song["artist"], artist_cache)
            report["unique_musicbrainz_artist_lookups"] = len(artist_cache)
            if not alias:
                report["alias_skipped"] += 1
                entry["strategies"]["artist_alias"] = {"skipped": True, "reason": "MusicBrainz unavailable, ambiguous, or no alternate"}
                report["tracks"].append(entry)
                continue
            report["alias_attempted"] += 1
            alias_query = f'track:"{spotify._spotify_query_value(song["title"])}" artist:"{spotify._spotify_query_value(alias["alternate"])}"'
            alias_params = {"q": alias_query, "type": "track", "limit": 10, "offset": 0}
            alias_key = _request_key(alias_params)
            reused = alias_key in cache
            if reused:
                alias_response = cache[alias_key]
                report["cache_hits"] += 1
            else:
                if report["real_spotify_searches"] and delay_seconds > 0:
                    time.sleep(delay_seconds)
                alias_response = spotify._spotify_get(f"{spotify.SPOTIFY_API_URL}/search", access_token, alias_params)
                cache[alias_key] = alias_response
                report["real_spotify_searches"] += 1
            alias_items = _response_items(alias_response)
            accepted = _matcher_accepts(access_token, song, alias_items)
            report["alias_spotify_candidates_found"] += bool(alias_items)
            report["alias_zero_candidates"] += not bool(alias_items)
            report["alias_matcher_accepted"] += bool(accepted)
            entry["strategies"]["artist_alias"] = {
                "source_artist": song["artist"], "mbid": alias["mbid"],
                "canonical_artist": alias["canonical_name"], "alternate_artist": alias["alternate"],
                "query": alias_query, "offset": 0, "candidate_count": len(alias_items),
                "candidates": [_candidate(item, index) for index, item in enumerate(alias_items, 1)],
                "cache_hit": reused, "accepted_track_ids": accepted,
            }
        report["tracks"].append(entry)
    return report


def print_summary(report: dict) -> None:
    print(f"Total songs: {report['total']}")
    for entry in report["tracks"]:
        print(f"\n{entry['source_title']} - {entry['source_artist']}")
        for name, result in entry["strategies"].items():
            print(f"  {name}: {result['candidate_count']} candidates")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Spotify retrieval benchmark")
    parser.add_argument("input", help="UTF-8 file containing TITLE - ARTIST lines")
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--json", default="retrieval_benchmark.json")
    args = parser.parse_args()
    report = benchmark(args.access_token, parse_lines(args.input), args.delay_seconds)
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"JSON report: {args.json}")


if __name__ == "__main__":
    main()
