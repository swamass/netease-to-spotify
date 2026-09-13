"""Read-only Spotify retrieval benchmark; never writes playlists."""

import argparse
import contextlib
import json
import re
import time
from io import StringIO
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


def diagnose_candidate_with_musicbrainz(
    access_token: str, song: dict[str, str], candidate: dict
) -> dict:
    """Evaluate one supplied candidate with real MusicBrainz lookups enabled."""
    class Response:
        def json(self):
            return {"tracks": {"items": [candidate]}}

    events = []
    original_spotify_get = spotify._spotify_get
    original_artist_ids = spotify._musicbrainz_artist_ids
    original_artist_names = spotify._musicbrainz_artist_names
    original_recordings = spotify._musicbrainz_recordings_for_isrc

    def artist_ids(name):
        result = original_artist_ids(name)
        events.append({"path": "artist", "name": name, "ids": sorted(result)})
        return result

    def artist_names(mbid):
        result = original_artist_names(mbid)
        events.append({"path": f"artist/{mbid}", "mbid": mbid, "names": sorted(result)})
        return result

    def recordings(isrc):
        result = original_recordings(isrc)
        events.append({
            "path": f"isrc/{isrc}",
            "isrc": isrc,
            "recordings": [
                {
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "artist_credits": [
                        {
                            "name": credit.get("artist", {}).get("name", ""),
                            "mbid": credit.get("artist", {}).get("id"),
                        }
                        for credit in item.get("artist-credit", [])
                    ],
                    "duration_ms": item.get("length"),
                    "disambiguation": item.get("disambiguation", ""),
                }
                for item in result
            ],
        })
        return result

    output = StringIO()
    try:
        spotify._spotify_get = lambda *_args, **_kwargs: Response()
        spotify._musicbrainz_artist_ids = artist_ids
        spotify._musicbrainz_artist_names = artist_names
        spotify._musicbrainz_recordings_for_isrc = recordings
        with contextlib.redirect_stdout(output):
            accepted = spotify.search_track(
                access_token, song["title"], [song["artist"]], "",
            )
    finally:
        spotify._spotify_get = original_spotify_get
        spotify._musicbrainz_artist_ids = original_artist_ids
        spotify._musicbrainz_artist_names = original_artist_names
        spotify._musicbrainz_recordings_for_isrc = original_recordings
    output_lines = output.getvalue().splitlines()
    artist_events = [event for event in events if event["path"] == "artist"]
    recording_event = next((event for event in events if event["path"].startswith("isrc/")), None)
    identity_status = _artist_identity_status(output_lines)
    artist_score, artist_reliable, _ = spotify._artist_match_score(
        [song["artist"]], candidate.get("artists", [])
    )
    return {
        "source_title": song["title"],
        "source_artist": song["artist"],
        "candidate": _candidate(candidate, 1),
        "title_match": spotify._title_match(song["title"], candidate.get("name", "")),
        "artist_score": artist_score,
        "artist_reliable": artist_reliable,
        "artist_identity": {
            "result": identity_status,
            "mbids": sorted({mbid for event in artist_events for mbid in event["ids"]}),
        },
        "isrc_recording_lookup_ran": recording_event is not None,
        "recordings": recording_event["recordings"] if recording_event else [],
        "version_conflicts": spotify._version_conflicts(
            song["title"], "", candidate.get("name", ""),
            candidate.get("album", {}).get("name", ""),
        ),
        "accepted": bool(accepted),
        "spotify_track_id": accepted,
        "diagnostics": events,
        "matcher_output": output_lines,
    }


def _artist_identity_status(output_lines: list[str]) -> str:
    for line in output_lines:
        if not line.startswith("MB artist identity:"):
            continue
        status = line.rsplit("identity=", 1)[-1].strip()
        if status in {"CONFIRMED", "NOT_CONFIRMED", "NOT_FOUND", "UNAVAILABLE"}:
            return status
    return "UNAVAILABLE"


def run_mai_yamane_diagnostic(access_token: str = "diagnostic") -> dict:
    cases = [
        ({"title": "たそがれ (Twilight)", "artist": "山根麻以"}, {"id": "mai-yamane-tasogare", "name": "Tasogare - Mai Yamane", "artists": [{"name": "Mai Yamane"}], "album": {"name": "Mai Yamane"}, "external_ids": {"isrc": "USA2P2544106"}}),
        ({"title": "Wave", "artist": "山根麻以"}, {"id": "mai-yamane-wave", "name": "Wave", "artists": [{"name": "Mai Yamane"}], "album": {"name": "Wave"}, "external_ids": {"isrc": "USA2P2552288"}}),
    ]
    return {"cases": [diagnose_candidate_with_musicbrainz(access_token, song, candidate) for song, candidate in cases]}


def _saved_candidate(candidate: dict) -> dict:
    return {
        "id": candidate.get("spotify_track_id"),
        "name": candidate.get("title", ""),
        "artists": [{"name": name} for name in candidate.get("artists", [])],
        "album": {"name": candidate.get("album", "")},
        "external_ids": {"isrc": candidate["isrc"]} if candidate.get("isrc") else {},
    }


def replay_report(report_path: str) -> dict:
    saved = json.loads(Path(report_path).read_text(encoding="utf-8"))
    results = []
    for entry in saved.get("tracks", []):
        candidates = {}
        old_accepted = set()
        for strategy in entry.get("strategies", {}).values():
            old_accepted.update(strategy.get("accepted_track_ids", []))
            for item in strategy.get("candidates", []):
                track_id = item.get("spotify_track_id")
                if track_id:
                    candidates[track_id] = _saved_candidate(item)
        song = {"title": entry.get("source_title", ""), "artist": entry.get("source_artist", "")}
        accepted, matcher_diagnostics = _replay_match(song, list(candidates.values()))
        results.append({
            "input_index": entry.get("input_index"),
            "source_title": song["title"],
            "source_artist": song["artist"],
            "saved_candidate_count": len(candidates),
            "accepted_track_ids": accepted,
            "baseline_accepted_track_ids": sorted(old_accepted),
            "newly_accepted_track_ids": sorted(set(accepted) - old_accepted),
            "catalog_exception": "山下達郎" in song["artist"],
            "matcher_diagnostics": matcher_diagnostics,
        })
    candidate_rows = [row for row in results if row["saved_candidate_count"]]
    accepted_rows = [row for row in results if row["accepted_track_ids"]]
    return {
        "total_source_tracks": len(results),
        "tracks_with_saved_candidates": len(candidate_rows),
        "tracks_accepted_by_current_matcher": len(accepted_rows),
        "acceptance_rate_all": len(accepted_rows) / len(results) if results else 0,
        "acceptance_rate_with_candidates": len(accepted_rows) / len(candidate_rows) if candidate_rows else 0,
        "newly_accepted_count": sum(bool(row["newly_accepted_track_ids"]) for row in results),
        "catalog_exception_tracks": [row["input_index"] for row in results if row["catalog_exception"]],
        "tracks": results,
    }


def _replay_match(song: dict[str, str], items: list[dict]) -> list[str]:
    class Response:
        def json(self):
            return {"tracks": {"items": self.items}}

        def __init__(self, response_items):
            self.items = response_items

    original_get = spotify._spotify_get
    try:
        spotify._spotify_get = lambda *_args, **_kwargs: Response(items)
        diagnostics = {}
        accepted = spotify.search_track(
            "replay", song["title"], [song["artist"]], "", diagnostics=diagnostics
        )
        return ([accepted] if accepted else []), diagnostics
    finally:
        spotify._spotify_get = original_get


def _print_replay_summary(report: dict) -> None:
    print(f"Total source tracks: {report['total_source_tracks']}")
    print(f"Tracks with saved candidates: {report['tracks_with_saved_candidates']}")
    print(f"Accepted by current matcher: {report['tracks_accepted_by_current_matcher']}")
    print(f"Acceptance rate: {report['acceptance_rate_all']:.4f}")


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
    display_names = [data.get("name", "")]
    display_names.extend(alias.get("name", "") for alias in data.get("aliases", []))
    alternates = [name for name in display_names if name and spotify._normalize_text(name) != key]
    latin = [name for name in alternates if not any(ord(char) > 127 for char in name)]
    result = {"mbid": mbid, "canonical_name": data.get("name", ""), "alternate": (latin or alternates or [None])[0]}
    cache[key] = result if result["alternate"] else None
    return cache[key]


def _retry_after_from_error(error: Exception) -> int | None:
    value = getattr(error, "retry_after_seconds", None)
    if value is not None:
        return int(value)
    match = re.search(r"Retry-After[= ](\d+)", str(error), re.IGNORECASE)
    return int(match.group(1)) if match else None


def benchmark(access_token: str, songs: list[dict[str, str]], delay_seconds: float = 0.25, start_index: int = 0) -> dict:
    report = {
        "total": len(songs), "logical_searches": 0,
        "real_spotify_searches": 0, "cache_hits": 0, "tracks": [],
        "alias_attempted": 0, "alias_skipped": 0,
        "alias_spotify_candidates_found": 0, "alias_zero_candidates": 0,
        "alias_matcher_accepted": 0, "unique_musicbrainz_artist_lookups": 0,
        "completed_input_rows": 0, "total_input_rows": len(songs),
        "stopped_early": False, "stop_reason": None,
        "retry_after_seconds": None, "start_index": start_index,
        "last_completed_index": None, "next_start_index": start_index,
    }
    cache = {}
    artist_cache = {}
    for input_index, song in enumerate(songs[start_index:], start=start_index):
        entry = {"input_index": input_index, "source_title": song["title"], "source_artist": song["artist"], "strategies": {}}
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
                try:
                    response = spotify._spotify_get(
                        f"{spotify.SPOTIFY_API_URL}/search", access_token, request_params
                    )
                except spotify.SpotifyRateLimitError as error:
                    report.update({
                        "stopped_early": True,
                        "stop_reason": "SPOTIFY_RATE_LIMIT",
                        "retry_after_seconds": _retry_after_from_error(error),
                        "next_start_index": input_index,
                    })
                    break
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
        if report["stopped_early"]:
            break
        if entry["strategies"]["structured_page_0"]["candidate_count"] == 0:
            alias = None if _ambiguous_artist_field(song["artist"]) else _artist_alias(song["artist"], artist_cache)
            report["unique_musicbrainz_artist_lookups"] = len(artist_cache)
            if alias is None:
                report["alias_skipped"] += 1
                entry["strategies"]["artist_alias"] = {"skipped": True, "reason": "ambiguous, unavailable, or no trusted alternate"}
            else:
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
                    try:
                        alias_response = spotify._spotify_get(f"{spotify.SPOTIFY_API_URL}/search", access_token, alias_params)
                    except spotify.SpotifyRateLimitError as error:
                        report.update({"stopped_early": True, "stop_reason": "SPOTIFY_RATE_LIMIT", "retry_after_seconds": _retry_after_from_error(error), "next_start_index": input_index})
                        break
                    cache[alias_key] = alias_response
                    report["real_spotify_searches"] += 1
                alias_items = _response_items(alias_response)
                accepted = _matcher_accepts(access_token, song, alias_items)
                report["alias_spotify_candidates_found"] += bool(alias_items)
                report["alias_zero_candidates"] += not bool(alias_items)
                report["alias_matcher_accepted"] += bool(accepted)
                entry["strategies"]["artist_alias"] = {"source_artist": song["artist"], "mbid": alias["mbid"], "canonical_artist": alias["canonical_name"], "alternate_artist": alias["alternate"], "query": alias_query, "offset": 0, "candidate_count": len(alias_items), "candidates": [_candidate(item, index) for index, item in enumerate(alias_items, 1)], "cache_hit": reused, "accepted_track_ids": accepted}
                if report["stopped_early"]:
                    break
        if report["stopped_early"]:
            break
        report["tracks"].append(entry)
        report["completed_input_rows"] += 1
        report["last_completed_index"] = input_index
        report["next_start_index"] = input_index + 1
    return report


def print_summary(report: dict) -> None:
    print(f"Total songs: {report['total']}")
    for entry in report["tracks"]:
        print(f"\n{entry['source_title']} - {entry['source_artist']}")
        for name, result in entry["strategies"].items():
            if result.get("skipped"):
                print(f"  {name}: skipped ({result.get('reason', 'no reason')})")
            else:
                print(f"  {name}: {result.get('candidate_count', 0)} candidates")


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Spotify retrieval benchmark")
    parser.add_argument("input", nargs="?", help="UTF-8 file containing TITLE - ARTIST lines")
    parser.add_argument("--access-token")
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--json", default="retrieval_benchmark.json")
    parser.add_argument("--mai-yamane-diagnostic", action="store_true")
    parser.add_argument("--replay")
    args = parser.parse_args()
    if args.mai_yamane_diagnostic:
        if not args.access_token:
            args.access_token = "diagnostic"
        report = run_mai_yamane_diagnostic(args.access_token)
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for case in report["cases"]:
            print(f"{case['source_title']} -> {case['candidate']['title']}: {'MATCH' if case['accepted'] else 'REJECT'}")
        print(f"JSON report: {args.json}")
        return
    if args.replay:
        report = replay_report(args.replay)
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_replay_summary(report)
        print(f"JSON report: {args.json}")
        return
    if not args.access_token:
        parser.error("the following arguments are required: --access-token")
    if not args.input:
        parser.error("the following arguments are required: input")
    report = benchmark(args.access_token, parse_lines(args.input), args.delay_seconds, args.start_index)
    Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"JSON report: {args.json}")
    if report["stopped_early"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
