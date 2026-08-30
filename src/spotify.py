import base64
import difflib
import re
import time
import unicodedata

import requests


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]
MAX_RETRY_AFTER_SECONDS = 15


class SpotifyRateLimitError(RuntimeError):
    """Raised when Spotify asks the whole sync to stop waiting."""


def get_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    """Use the refresh token to get a new Spotify access token."""
    credentials = f"{client_id}:{client_secret}".encode()
    encoded_credentials = base64.b64encode(credentials).decode()

    response = requests.post(
        SPOTIFY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    print("Spotify token scopes:", data.get("scope"))

    if "access_token" not in data:
        raise RuntimeError("Spotify did not return an access token.")

    return data["access_token"]


def _spotify_get(
    url: str,
    access_token: str,
    params: dict,
) -> requests.Response | None:
    """Make a Spotify GET request with retries for temporary errors."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
                params=params,
                timeout=30,
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "5")

                try:
                    wait_seconds = int(retry_after)
                except ValueError:
                    wait_seconds = 5

                print(
                    f"Spotify rate limit reached. Retry-After={wait_seconds}s."
                )
                if wait_seconds > MAX_RETRY_AFTER_SECONDS:
                    print(
                        f"Retry-After exceeds {MAX_RETRY_AFTER_SECONDS}s; "
                        "aborting all Spotify searches."
                    )
                    raise SpotifyRateLimitError(
                        "Spotify rate limit detected; aborting sync to protect "
                        "existing playlist."
                    )

                time.sleep(wait_seconds)
                continue

            if response.status_code in (502, 503, 504):
                if attempt < MAX_RETRIES - 1:
                    wait_seconds = RETRY_DELAYS[attempt]
                    print(
                        f"Spotify returned {response.status_code}. "
                        f"Retrying in {wait_seconds} seconds..."
                    )
                    time.sleep(wait_seconds)
                    continue

                print(
                    f"Spotify returned {response.status_code} "
                    f"after {MAX_RETRIES} attempts."
                )
                return None

            response.raise_for_status()
            return response

        except requests.RequestException as error:
            if attempt < MAX_RETRIES - 1:
                wait_seconds = RETRY_DELAYS[attempt]
                print(
                    f"Spotify request failed: {error}. "
                    f"Retrying in {wait_seconds} seconds..."
                )
                time.sleep(wait_seconds)
                continue

            print(
                f"Spotify request failed after "
                f"{MAX_RETRIES} attempts: {error}"
            )
            return None

    return None


def _normalize_text(value: str) -> str:
    """Normalize text while ignoring punctuation and presentation differences."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


ARTIST_ALIASES = {
    "久石譲": ["Joe Hisaishi"],
    "山下達郎": ["Tatsuro Yamashita"],
    "竹内まりや": ["Mariya Takeuchi"],
    "清塚信也": ["Shinya Kiyozuka"],
    "NAOTO": ["Naoto"],
    "CAGNET": ["Cagnet"],
    "藤井風": ["Fujii Kaze"],
    "吉田美奈子": ["Minako Yoshida"],
    "ブレッド&バター": ["Bread And Butter"],
    "林ゆうき": ["Yuki Hayashi"],
    "宇多田ヒカル": ["Hikaru Utada"],
    "ラ・ムー": ["RA MU"],
}

TITLE_ALIASES = {
    "マイ・ベイビー・クイーン": ["My Baby Queen"],
    "トゥルー・トゥ・ユア・ハート(キャグネット)": [
        "True to Your Heart",
        "True to Your Heart (From Mulan)",
    ],
    "Just My Imagination": ["Just My Imagination (Running Away with Me)"],
}

VERSION_TERMS = {
    "remix", "remixed", "live", "acoustic", "edit", "radioedit",
    "version", "remaster", "remastered", "demo", "instrumental",
    "extendedmix", "djversion", "tribute", "cover", "karaoke",
}
HARD_VERSION_TERMS = {
    "live", "remix", "acoustic", "instrumental", "demo", "radioedit",
    "extendedmix", "djversion",
}
INVALID_RELEASE_TERMS = {"tribute", "cover", "karaoke"}


def _title_core(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(
        r"\s*\((?:with|feat\.?|featuring)\b[^)]*\)",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*-\s*from\s+[\"“”][^\"“”]+[\"“”]\s*$",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*-\s*(?:\\d{4}\\s+)?remaster(?:ed)?\\s*$",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*\\((?:\\d{4}\\s+)?remaster(?:ed)?|version)\\s*\\)\s*$",
        "",
        normalized,
    )
    return normalized.strip()


def _title_match(source: str, candidate: str) -> bool:
    source_key = _normalize_text(_title_core(source))
    candidate_key = _normalize_text(_title_core(candidate))
    if source_key == candidate_key:
        return True
    ratio = difflib.SequenceMatcher(None, source_key, candidate_key).ratio()
    return ratio >= 0.92 and abs(len(source_key) - len(candidate_key)) <= 3


def _title_variants(name: str) -> list[str]:
    variants = [name, *TITLE_ALIASES.get(name, [])]
    return list(dict.fromkeys(variants))


def _version_terms(value: str) -> set[str]:
    normalized = _normalize_text(value)
    return {term for term in VERSION_TERMS if term in normalized}


def _artist_matches(
    source_artists: list[str],
    spotify_artists: list[dict],
) -> tuple[bool, int]:
    source_names = {
        _normalize_text(value)
        for artist in source_artists
        for value in [artist, *ARTIST_ALIASES.get(artist, [])]
        if value
    }
    spotify_names = {
        _normalize_text(artist.get("name", ""))
        for artist in spotify_artists
        if artist.get("name")
    }
    matches = source_names & spotify_names
    return bool(matches), len(matches)


def _album_score(source_album: str, spotify_album: str) -> int:
    if not source_album or not spotify_album:
        return 0
    source = _normalize_text(source_album)
    candidate = _normalize_text(spotify_album)
    if source == candidate:
        return 60
    if source in candidate or candidate in source:
        return 45
    return 15


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
    album: str = "",
) -> str | None:
    """Find the most reliable candidate using two bounded searches."""
    if not name or not artists:
        print(f"Not found: {name} - missing artist metadata")
        return None

    artist = artists[0]
    queries = [
        f'track:"{name}" artist:"{artist}"'
        + (f' album:"{album}"' if album else ""),
        f"{name} {artist}".strip(),
    ]
    source_versions = _version_terms(name) | _version_terms(album)
    candidates = {}
    requests_sent = 0

    for query_index, query in enumerate(queries, start=1):
        print(f"Spotify search query {query_index}/2: {query}")
        requests_sent += 1
        response = _spotify_get(
            f"{SPOTIFY_API_URL}/search",
            access_token,
            {"q": query, "type": "track", "limit": 10},
        )
        if response is None:
            print(f"Search request {requests_sent} skipped or failed.")
            continue

        items = response.json().get("tracks", {}).get("items", [])
        print(f"Search result: {len(items)} candidates")
        for item in items:
            item_name = item.get("name", "")
            item_artists = item.get("artists", [])
            item_album_name = item.get("album", {}).get("name", "")
            item_versions = _version_terms(item_name) | _version_terms(item_album_name)
            reasons = []

            if not _title_match(name, item_name):
                reasons.append("title mismatch")
            artist_ok, artist_count = _artist_matches(artists, item_artists)
            if not artist_ok:
                reasons.append("artist mismatch")
            invalid_terms = item_versions & INVALID_RELEASE_TERMS
            if invalid_terms:
                reasons.append("invalid release: " + ", ".join(sorted(invalid_terms)))
            source_hard_versions = source_versions & HARD_VERSION_TERMS
            candidate_hard_versions = item_versions & HARD_VERSION_TERMS
            if source_hard_versions != candidate_hard_versions:
                reasons.append("version mismatch")

            album_points = _album_score(album, item_album_name)
            if reasons:
                print(
                    f"Rejected candidate: {item_name} - "
                    f"{', '.join(value.get('name', '') for value in item_artists)} - "
                    f"{item_album_name} ({', '.join(reasons)})"
                )
                continue

            score = 300 * artist_count + 100 + album_points
            item_id = item.get("id")
            if item_id:
                candidates[item_id] = max(
                    candidates.get(item_id, (0, item)),
                    (score, item),
                    key=lambda value: value[0],
                )

        if candidates:
            break

    print(f"Spotify search requests sent: {requests_sent}")
    if not candidates:
        print(f"Not found: {name} - no sufficiently reliable candidate")
        return None

    score, item = max(candidates.values(), key=lambda value: value[0])
    item_artists = ", ".join(
        value.get("name", "") for value in item.get("artists", [])
    )
    album_points = _album_score(album, item.get("album", {}).get("name", ""))
    print(
        f"Matched candidate: {item.get('name', '')} - {item_artists} - "
        f"{item.get('album', {}).get('name', '')}; "
        f"Match reason: title + artist"
        + (" + album" if album_points >= 45 else "")
        + f"; score={score}"
    )
    return item.get("id")

def replace_playlist_tracks(
    access_token: str,
    playlist_id: str,
) -> None:
    """Remove all existing tracks using Spotify's playlist replace endpoint."""
    response = requests.put(
        f"{SPOTIFY_API_URL}/playlists/{playlist_id}/items",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"uris": []},
        timeout=30,
    )

    print("Spotify playlist clear status:", response.status_code)
    response.raise_for_status()

    print("Cleared existing Spotify playlist tracks.")

def add_tracks_to_playlist(
    access_token: str,
    playlist_id: str,
    track_ids: list[str],
) -> None:
    """Add all tracks to a Spotify playlist in batches of 100."""

    if not track_ids:
        print("No tracks to add.")
        return

    uris = [
        f"spotify:track:{track_id}"
        for track_id in track_ids
    ]

    for start in range(0, len(uris), 100):
        batch = uris[start : start + 100]

        print(
            f"Trying to add {len(batch)} tracks "
            f"to Spotify playlist..."
        )

        response = requests.post(
            f"{SPOTIFY_API_URL}/playlists/{playlist_id}/items",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "uris": batch,
            },
            timeout=30,
        )

        print("Spotify response status:", response.status_code)
        print("Spotify response body:", response.text)

        if response.status_code != 201:
            print("Spotify response headers:", dict(response.headers))

        response.raise_for_status()

        print(
            f"Successfully added {len(batch)} tracks."
        )
