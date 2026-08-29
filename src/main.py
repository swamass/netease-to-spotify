import requests

from src.config import load_settings
from src.netease import get_daily_recommendations
from src.spotify import (
    add_tracks_to_playlist,
    get_access_token,
    replace_playlist_tracks,
    search_track,
)


def check_playlist(
    access_token: str,
    playlist_id: str,
) -> None:
    """Check whether the Spotify playlist can be accessed."""
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"

    print("Checking Spotify playlist...")

    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
        },
        timeout=30,
    )

    print(f"Playlist check status: {response.status_code}")

    if response.status_code != 200:
        print("Playlist check response:")
        print(response.text)

        response.raise_for_status()

    data = response.json()

    playlist_name = data.get("name", "")
    owner = data.get("owner", {}).get("display_name", "")

    print(f"Playlist name: {playlist_name}")
    print(f"Playlist owner: {owner}")
    print("Spotify playlist access: OK")


def main() -> None:
    settings = load_settings()

    print("Getting NetEase daily recommendations...")
    songs = get_daily_recommendations(settings.netease_cookie)
    print(f"Found {len(songs)} NetEase daily recommendations.")

    if not songs:
        raise RuntimeError(
            "NetEase returned an empty recommendation list. "
            "Keeping the existing Spotify playlist."
        )

    print("Getting Spotify access token...")
    access_token = get_access_token(
        settings.spotify_client_id,
        settings.spotify_client_secret,
        settings.spotify_refresh_token,
    )

    check_playlist(
        access_token,
        settings.spotify_playlist_id,
    )

    track_ids = []
    seen_track_ids = set()

    for song in songs:
        track_id = search_track(
            access_token,
            song["name"],
            song["artists"],
            song.get("album", ""),
        )

        if track_id and track_id not in seen_track_ids:
            seen_track_ids.add(track_id)
            track_ids.append(track_id)
            print(
                f"Matched: {song['name']} - "
                f"{', '.join(song['artists'])}"
            )
        else:
            print(
                f"Not found: {song['name']} - "
                f"{', '.join(song['artists'])}"
            )

    print(f"Matched {len(track_ids)} tracks.")

    if not track_ids:
        raise RuntimeError(
            "No NetEase recommendations matched valid Spotify tracks. "
            "Keeping the existing Spotify playlist."
        )

    replace_playlist_tracks(
        access_token,
        settings.spotify_playlist_id,
    )

    add_tracks_to_playlist(
        access_token,
        settings.spotify_playlist_id,
        track_ids,
    )

    print(
        f"Added {len(track_ids)} tracks to Spotify playlist."
    )


if __name__ == "__main__":
    main()
