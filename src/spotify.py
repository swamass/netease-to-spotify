import base64
import time

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
    """Normalize text for tolerant title and artist comparisons."""
    return "".join(value.casefold().split())


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
) -> str | None:
    """Search Spotify and require a verified artist match."""

    if not name or not artists:
        return None

    primary_artist = artists[0]
    response = _spotify_get(
        f"{SPOTIFY_API_URL}/search",
        access_token,
        {
            "q": f'track:"{name}" artist:"{primary_artist}"',
            "type": "track",
            "limit": 10,
        },
    )

    if response is None:
        return None

    normalized_name = _normalize_text(name)
    normalized_artists = {
        _normalize_text(artist)
        for artist in artists
        if artist
    }

    for item in response.json().get("tracks", {}).get("items", []):
        item_name = _normalize_text(item.get("name", ""))
        item_artists = {
            _normalize_text(artist.get("name", ""))
            for artist in item.get("artists", [])
        }

        if item_name == normalized_name and normalized_artists & item_artists:
            return item.get("id")

    # A title-only match is intentionally rejected: identical song titles can
    # belong to different artists, and localized names cannot be verified safely.
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
