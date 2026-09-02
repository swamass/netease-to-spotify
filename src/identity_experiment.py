"""Read-only MusicBrainz artist and recording identity experiment."""
import argparse
import json
from dataclasses import asdict, dataclass
from typing import Any

import requests

MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
USER_AGENT = "netease-to-spotify-identity-experiment/1.0"
SCOPE = "playlist-modify-private"


@dataclass(frozen=True)
class ExperimentCase:
    title: str
    netease_artist: str
    netease_album: str
    spotify_title: str
    spotify_artists: tuple[str, ...]
    spotify_album: str


CASES = (
    ExperimentCase("Eyes On Me", "王菲", "Separate Ways", "Eyes On Me", ("Faye Wong",), "Eyes On Me"),
    ExperimentCase("On My Own", "岩崎太整 / 二宮愛", "", "On My Own", ("Taisei Iwasaki", "Ai Ninomiya"), 'On My Own (From "Blood Blockade Battlefront" Soundtrack)'),
    ExperimentCase("あなたを・もっと・知りたくて", "薬師丸ひろ子", "", "あなたを・もっと・知りたくて", ("Hiroko Yakushimaru",), ""),
    ExperimentCase("最後の言い訳", "德永英明", "", "最後の言い訳", ("Hideaki Tokunaga",), ""),
)


def _get_json(url: str, params: dict[str, Any], request_get=requests.get) -> dict[str, Any]:
    response = request_get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def search_artist(name: str, request_get=requests.get) -> list[dict[str, Any]]:
    return _get_json(
        f"{MUSICBRAINZ_URL}/artist",
        {"query": f'artist:"{name}"', "fmt": "json", "limit": 5},
        request_get,
    ).get("artists", [])


def fetch_artist(mbid: str, request_get=requests.get) -> dict[str, Any]:
    return _get_json(
        f"{MUSICBRAINZ_URL}/artist/{mbid}",
        {"fmt": "json", "inc": "aliases"},
        request_get,
    )


def search_recordings(title: str, artist_mbid: str | None = None, request_get=requests.get) -> list[dict[str, Any]]:
    query = f'recording:"{title}"'
    if artist_mbid:
        query += f" AND arid:{artist_mbid}"
    return _get_json(
        f"{MUSICBRAINZ_URL}/recording",
        {"query": query, "fmt": "json", "limit": 10},
        request_get,
    ).get("recordings", [])


def fetch_recording(mbid: str, request_get=requests.get) -> dict[str, Any]:
    return _get_json(
        f"{MUSICBRAINZ_URL}/recording/{mbid}",
        {"fmt": "json", "inc": "artist-credits+releases+isrcs"},
        request_get,
    )


def extract_spotify_isrc(track: dict[str, Any]) -> str | None:
    return (track.get("external_ids") or {}).get("isrc")


def identity_result(title: str, artist: str, isrc: str, album: str) -> str:
    if isrc == "MATCH":
        return "SAME_RECORDING"
    if title == "EXACT" and artist == "STRONG":
        return "LIKELY_SAME"
    return "UNCERTAIN"


def analyze_case(case: ExperimentCase, spotify_track: dict[str, Any] | None = None, request_get=requests.get) -> dict[str, Any]:
    artists = search_artist(case.netease_artist, request_get)
    artist = fetch_artist(artists[0]["id"], request_get) if artists else {}
    recordings = search_recordings(case.title, artists[0]["id"], request_get) if artists else []
    recording = fetch_recording(recordings[0]["id"], request_get) if recordings else {}
    spotify_track = spotify_track or {
        "name": case.spotify_title,
        "artists": [{"name": value} for value in case.spotify_artists],
        "album": {"name": case.spotify_album},
    }
    spotify_isrc = extract_spotify_isrc(spotify_track)
    musicbrainz_isrcs = recording.get("isrcs", [])
    isrc = "MATCH" if spotify_isrc and spotify_isrc in musicbrainz_isrcs else "UNKNOWN"
    title = "EXACT" if case.title.casefold() == spotify_track.get("name", "").casefold() else "DIFFERENT"
    album = "SAME" if case.netease_album and case.netease_album == spotify_track.get("album", {}).get("name", "") else "DIFFERENT"
    return {
        "case": asdict(case),
        "musicbrainz_artist": artist,
        "recording": recording,
        "spotify_isrc": spotify_isrc,
        "musicbrainz_isrcs": musicbrainz_isrcs,
        "identity_evidence": {"artist_identity": "STRONG" if artist else "UNCERTAIN", "title": title, "isrc": isrc, "album": album},
        "final_result": identity_result(title, "STRONG" if artist else "UNCERTAIN", isrc, album),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    reports = [analyze_case(case) for case in CASES]
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
        return
    for report in reports:
        case = report["case"]
        evidence = report["identity_evidence"]
        print(f"\n=== {case['title']} ===")
        print(f"NetEase: {case['netease_artist']} / {case['netease_album']}")
        print(f"Spotify: {case['spotify_title']} / {', '.join(case['spotify_artists'])}")
        artist = report["musicbrainz_artist"]
        print(f"MusicBrainz Artist: {artist.get('name', 'NOT FOUND')} | MBID: {artist.get('id', 'UNKNOWN')}")
        print(f"Spotify ISRC: {report['spotify_isrc'] or 'UNKNOWN'}")
        print(f"MusicBrainz ISRC: {', '.join(report['musicbrainz_isrcs']) or 'UNKNOWN'}")
        print(f"Identity evidence: {json.dumps(evidence, ensure_ascii=False)}")
        print(f"Final experimental result: {report['final_result']}")


if __name__ == "__main__":
    main()
