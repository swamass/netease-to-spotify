import base64
import time
import unicodedata

import requests


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]


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
                    f"Spotify rate limit reached. "
                    f"Waiting {wait_seconds} seconds..."
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
    "Paul McCartney": ["Michael Jackson"],
}

TITLE_ALIASES = {
    "Just My Imagination": ["Just My Imagination (Running Away with Me)"],
    "トゥルー・トゥ・ユア・ハート(キャグネット)": ["True to Your Heart"],
}

TITLE_ALIASES = {
    "マイ・ベイビー・クイーン": ["My Baby Queen"],
    "トゥルー・トゥ・ユア・ハート(キャグネット)": [
        "True to Your Heart",
        "True to Your Heart (From Mulan)",
    ],
}


def _title_variants(name: str) -> list[str]:
    """Create safe title variants for remaster and edition suffixes."""
    variants = [name, *TITLE_ALIASES.get(name, [])]
    base_name = name.split(" [", 1)[0].split(" (", 1)[0].strip()
    if base_name and base_name != name:
        variants.append(base_name)
    hyphen_name = name.split(" - ", 1)[0].strip()
    if hyphen_name and hyphen_name != name:
        variants.append(hyphen_name)
    return list(dict.fromkeys(variants))


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
    album: str = "",
) -> str | None:
    """Search Spotify with title variants and verified artist constraints."""

    if not name or not artists:
        return None

    artist_queries = []
    for artist in artists:
        artist_queries.extend([artist, *ARTIST_ALIASES.get(artist, [])])
    normalized_artist_queries = {
        _normalize_text(artist)
        for artist in artist_queries
        if artist
    }
    normalized_names = {_normalize_text(title) for title in _title_variants(name)}
    album_query = f" album:\"{album}\"" if album else ""

    for artist in artist_queries:
        for title in _title_variants(name):
            queries = [
                f'track:"{title}" artist:"{artist}"{album_query}',
                f"{title} {artist} {album}".strip(),
            ]

            for query in queries:
                response = _spotify_get(
                    f"{SPOTIFY_API_URL}/search",
                    access_token,
                    {
                        "q": query,
                        "type": "track",
                        "limit": 10,
                    },
                )

                if response is None:
                    continue

                for item in response.json().get("tracks", {}).get("items", []):
                    if _normalize_text(item.get("name", "")) not in normalized_names:
                        continue

                    item_artists = {
                        _normalize_text(artist.get("name", ""))
                        for artist in item.get("artists", [])
                    }

                    if normalized_artist_queries & item_artists:
                        if album and item.get("album", {}).get("name"):
                            normalized_album = _normalize_text(album)
                            item_album = _normalize_text(item["album"]["name"])
                            if normalized_album not in item_album and item_album not in normalized_album:
                                continue
                        return item.get("id")

    return None

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
