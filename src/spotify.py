import base64

import requests


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"


def get_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    """用 Refresh Token 换取新的 Spotify Access Token。"""
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

    if "access_token" not in data:
        raise RuntimeError("Spotify did not return an access token.")

    return data["access_token"]


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
) -> str | None:
    """在 Spotify 搜索歌曲，返回 Track ID。"""
    artist_text = " ".join(artists)
    query = f'track:"{name}" artist:"{artist_text}"'

    response = requests.get(
        f"{SPOTIFY_API_URL}/search",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
        params={
            "q": query,
            "type": "track",
            "limit": 5,
        },
        timeout=30,
    )
    response.raise_for_status()

    items = response.json().get("tracks", {}).get("items", [])

    if not items:
        return None

    return items[0]["id"]


def add_tracks_to_playlist(
    access_token: str,
    playlist_id: str,
    track_ids: list[str],
) -> None:
    """把歌曲添加到 Spotify Playlist。"""
    if not track_ids:
        return

    uris = [f"spotify:track:{track_id}" for track_id in track_ids]

    for start in range(0, len(uris), 100):
        batch = uris[start : start + 100]

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
        response.raise_for_status()
