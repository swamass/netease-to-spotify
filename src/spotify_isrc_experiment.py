"""Read-only Spotify ISRC and MusicBrainz identity experiment."""
import base64
import json
import os
import time
from typing import Any

import requests

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
USER_AGENT = "netease-to-spotify-identity-experiment/1.0"
REQUEST_DELAY = 1.1


CASES = [
    {"title": "Eyes On Me", "netease_artists": ["王菲"], "spotify_query": "Eyes On Me Faye Wong"},
    {"title": "On My Own", "netease_artists": ["岩崎太整", "二宮愛"], "spotify_query": "On My Own Taisei Iwasaki Ai Ninomiya"},
    {"title": "あなたを・もっと・知りたくて", "netease_artists": ["薬師丸ひろ子"], "spotify_query": "あなたを・もっと・知りたくて Hiroko Yakushimaru"},
    {"title": "最後の言い訳", "netease_artists": ["徳永英明", "德永英明"], "spotify_query": "最後の言い訳 Hideaki Tokunaga"},
]


def _get(url: str, headers: dict[str, str], params: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any]:
    delay = 1.0
    for attempt in range(retries):
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code in {500, 502, 503, 504} and attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError("Request failed after retries.")


def _musicbrainz_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    time.sleep(REQUEST_DELAY)
    return _get(url, {"User-Agent": USER_AGENT, "Accept": "application/json"}, params)


def _spotify_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        SPOTIFY_TOKEN_URL,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Spotify did not return an access token.")
    return token


def _spotify_get(url: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _get(url, {"Authorization": f"Bearer {token}"}, params, retries=2)


def _artist_candidates(name: str) -> list[dict[str, Any]]:
    data = _musicbrainz_get(f"{MUSICBRAINZ_URL}/artist", {"query": f'artist:"{name}"', "limit": 5, "fmt": "json"})
    return data.get("artists", [])


def _artist_report(names: list[str]) -> dict[str, Any]:
    matches = []
    seen = set()
    for name in names:
        for candidate in _artist_candidates(name):
            mbid = candidate.get("id")
            if mbid and mbid not in seen:
                seen.add(mbid)
                detail = _musicbrainz_get(f"{MUSICBRAINZ_URL}/artist/{mbid}", {"inc": "aliases", "fmt": "json"})
                matches.append(detail)
                break
    return {"queries": names, "matches": matches}


def _recording_report(title: str, artist_report: dict[str, Any]) -> dict[str, Any] | None:
    for artist in artist_report["matches"]:
        data = _musicbrainz_get(
            f"{MUSICBRAINZ_URL}/recording",
            {"query": f'recording:"{title}" AND arid:{artist["id"]}', "limit": 5, "fmt": "json"},
        )
        recordings = data.get("recordings", [])
        if recordings:
            return _musicbrainz_get(
                f"{MUSICBRAINZ_URL}/recording/{recordings[0]['id']}",
                {"inc": "artist-credits+releases+isrcs", "fmt": "json"},
            )
    return None


def _spotify_track(case: dict[str, Any], token: str) -> dict[str, Any] | None:
    data = _spotify_get(f"{SPOTIFY_API_URL}/search", token, {"q": case["spotify_query"], "type": "track", "limit": 10})
    items = data.get("tracks", {}).get("items", [])
    if not items:
        return None
    candidate = items[0]
    return _spotify_get(f"{SPOTIFY_API_URL}/tracks/{candidate['id']}", token)


def run_experiment(client_id: str, client_secret: str, refresh_token: str) -> list[dict[str, Any]]:
    token = _spotify_token(client_id, client_secret, refresh_token)
    reports = []
    for case in CASES:
        spotify = _spotify_track(case, token)
        artists = _artist_report(case["netease_artists"])
        recording = _recording_report(case["title"], artists)
        spotify_isrc = (spotify or {}).get("external_ids", {}).get("isrc")
        mb_isrcs = (recording or {}).get("isrcs", [])
        isrc_status = "ISRC_MATCH" if spotify_isrc and spotify_isrc in mb_isrcs else ("ISRC_DIFFERENT" if spotify_isrc and mb_isrcs else "ISRC_UNKNOWN")
        reports.append({
            "case": case,
            "spotify": spotify,
            "musicbrainz_artists": artists,
            "musicbrainz_recording": recording,
            "comparison": {
                "title": "EXACT" if spotify and spotify.get("name", "").casefold() == case["title"].casefold() else "UNCERTAIN",
                "artist_identity": "FOUND" if artists["matches"] else "UNKNOWN",
                "duration": "UNKNOWN",
                "spotify_isrc": spotify_isrc,
                "musicbrainz_isrc": mb_isrcs,
                "isrc_status": isrc_status,
            },
            "final": "SAME_RECORDING" if isrc_status == "ISRC_MATCH" else ("LIKELY_SAME" if spotify and artists["matches"] else "UNCERTAIN"),
        })
    return reports


def main() -> None:
    reports = run_experiment(os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"], os.environ["SPOTIFY_REFRESH_TOKEN"])
    with open("identity-experiment-report.json", "w", encoding="utf-8") as output:
        json.dump(reports, output, ensure_ascii=False, indent=2)
    print(json.dumps(reports, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
