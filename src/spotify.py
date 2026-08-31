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
    "村田和人": ["Kazuhito Murata"],
}

TITLE_ALIASES = {
    "マイ・ベイビー・クイーン": ["My Baby Queen"],
    "トゥルー・トゥ・ユア・ハート(キャグネット)": [
        "True to Your Heart",
        "True to Your Heart (From Mulan)",
    ],
    "Just My Imagination": ["Just My Imagination (Running Away with Me)"],
}

SAFE_VERSION_TERMS = {
    "remaster", "remastered", "reissue", "rerelease", "deluxeedition",
    "expandededition", "anniversaryedition", "specialedition",
}
HARD_VERSION_TERMS = {
    "live", "remix", "remixed", "acoustic", "instrumental", "demo",
    "radioedit", "extendedmix", "djversion",
}
INVALID_RELEASE_TERMS = {"tribute", "cover", "karaoke"}


def _version_terms(value: str) -> set[str]:
    normalized = _normalize_text(value)
    terms = set()
    for term in SAFE_VERSION_TERMS | HARD_VERSION_TERMS | INVALID_RELEASE_TERMS:
        if term in normalized:
            terms.add(term)
    return terms


def _title_core(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(
        r"\s*\((?:with|feat\.?|featuring)\b[^)]*\)",
        "",
        normalized,
    )
    normalized = re.sub(
        r'\s*-\s*from\s+["“”][^"“”]+["“”]\s*$',
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*-\s*(?:\d{4}\s+)?remaster(?:ed)?\s*$",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*\((?:\d{4}\s+)?remaster(?:ed)?\)\s*$",
        "",
        normalized,
    )
    return normalized.strip()


def _title_keys(value: str) -> set[str]:
    core = _title_core(value)
    keys = {_normalize_text(core)}
    subtitle_removed = re.sub(r"\s*\([^)]*\)\s*$", "", core).strip()
    if subtitle_removed != core:
        keys.add(_normalize_text(subtitle_removed))
    return {key for key in keys if key}


def _title_match(source: str, candidate: str) -> bool:
    source_keys = set()
    for variant in _title_variants(source):
        source_keys.update(_title_keys(variant))
    candidate_keys = _title_keys(candidate)
    for source_key in source_keys:
        for candidate_key in candidate_keys:
            if source_key == candidate_key:
                return True
            distance = abs(len(source_key) - len(candidate_key))
            ratio = difflib.SequenceMatcher(None, source_key, candidate_key).ratio()
            if distance <= 3 and ratio >= 0.92:
                return True
    return False


def _title_variants(name: str) -> list[str]:
    return list(dict.fromkeys([name, *TITLE_ALIASES.get(name, [])]))


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)


def _contains_kana(value: str) -> bool:
    return any(
        "\u3040" <= character <= "\u30ff"
        for character in value
    )


def _artist_match_score(
    source_artists: list[str],
    spotify_artists: list[dict],
) -> tuple[float, int, bool]:
    source_names = set()
    for source_artist in source_artists:
        source_names.add(_normalize_text(source_artist))
        source_names.update(
            _normalize_text(alias)
            for alias in ARTIST_ALIASES.get(source_artist, [])
        )

    spotify_values = [
        artist.get("name", "")
        for artist in spotify_artists
        if artist.get("name")
    ]
    spotify_names = {_normalize_text(value) for value in spotify_values}
    exact_matches = source_names & spotify_names
    if exact_matches:
        return 1.0, len(exact_matches), True

    for source_artist in source_artists:
        source_key = _normalize_text(source_artist)
        for spotify_name in spotify_names:
            if source_key and (
                source_key in spotify_name or spotify_name in source_key
            ):
                return 0.8, 1, True

    source_has_asian = any(
        _contains_cjk(value) or _contains_kana(value)
        for value in source_artists
    )
    spotify_has_asian = any(
        _contains_cjk(value) or _contains_kana(value)
        for value in spotify_values
    )
    if source_has_asian != spotify_has_asian or (
        source_has_asian and spotify_has_asian
    ):
        return 0.35, 0, False

    return 0.0, 0, False


def _artist_matches(
    source_artists: list[str],
    spotify_artists: list[dict],
) -> tuple[bool, int]:
    score, count, reliable = _artist_match_score(
        source_artists, spotify_artists
    )
    return score > 0, count


def _duration_score(source_duration_ms: int | None, spotify_duration_ms: int | None) -> int:
    if not source_duration_ms or not spotify_duration_ms:
        return 0
    difference = abs(source_duration_ms - spotify_duration_ms)
    if difference <= 3000:
        return 50
    if difference <= 8000:
        return 40
    if difference <= 15000:
        return 25
    if difference <= 30000:
        return 10
    return 0


def _album_score(source_album: str, spotify_album: str) -> int:
    if not source_album or not spotify_album:
        return 0
    source = _normalize_text(source_album)
    candidate = _normalize_text(spotify_album)
    if source == candidate:
        return 60
    if source in candidate or candidate in source:
        return 45
    source_words = set(re.findall(r"[a-z0-9]+", source))
    candidate_words = set(re.findall(r"[a-z0-9]+", candidate))
    overlap = len(source_words & candidate_words)
    if overlap:
        return 30
    return 10


def _release_has_invalid_terms(name: str, album: str) -> bool:
    return bool(_version_terms(name) | _version_terms(album) & INVALID_RELEASE_TERMS)


def _version_conflicts(source_name: str, source_album: str,
                       candidate_name: str, candidate_album: str) -> list[str]:
    source_terms = _version_terms(source_name) | _version_terms(source_album)
    candidate_terms = _version_terms(candidate_name) | _version_terms(candidate_album)
    reasons = []
    if candidate_terms & INVALID_RELEASE_TERMS:
        reasons.append("tribute/cover/karaoke release")
    for term in HARD_VERSION_TERMS:
        if (term in source_terms) != (term in candidate_terms):
            reasons.append(f"{term} version mismatch")
    return reasons


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
    album: str = "",
    duration_ms: int | None = None,
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
            item_id = item.get("id")
            item_name = item.get("name", "")
            item_artists = item.get("artists", [])
            item_album_name = item.get("album", {}).get("name", "")
            reasons = []

            if not item_id:
                reasons.append("missing track ID")
            if not _title_match(name, item_name):
                reasons.append("title mismatch")
            artist_score, artist_count, artist_reliable = _artist_match_score(
                artists, item_artists
            )
            album_points = _album_score(album, item_album_name)
            duration_points = _duration_score(
                duration_ms, item.get("duration_ms")
            )
            title_exact = _normalize_text(_title_core(name)) in _title_keys(item_name)
            if artist_score == 0:
                reasons.append("artist mismatch")
            elif not artist_reliable and not (
                title_exact and album_points >= 45
            ):
                reasons.append("artist not sufficiently corroborated")
            reasons.extend(_version_conflicts(
                name, album, item_name, item_album_name
            ))

            if reasons:
                print(
                    f"Rejected candidate: {item_name} - "
                    f"{', '.join(value.get('name', '') for value in item_artists)} - "
                    f"{item_album_name} ({', '.join(dict.fromkeys(reasons))})"
                )
                continue

            title_points = 300 if title_exact else 276
            version_points = 100
            score = (
                title_points
                + 500 * artist_score
                + album_points
                + duration_points
                + version_points
            )
            print(
                f"Candidate score: title={title_points}, "
                f"artist={artist_score:.2f}, album={album_points}, "
                f"duration={duration_points}, version={version_points}, "
                f"total={score}"
            )
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
        f"Match reason: artist + title"
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
