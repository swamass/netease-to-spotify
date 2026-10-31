import requests

from src.config import load_settings
from src.netease import get_daily_recommendations, get_private_radar_tracks
from src.spotify import (
    get_access_token,
    SpotifyRateLimitError,
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


def _match_tracks(access_token: str, songs: list[dict], source_name: str) -> list[str]:
    track_ids = []
    seen_track_ids = set()
    try:
        for song in songs:
            track_id = search_track(
                access_token,
                song["name"],
                song["artists"],
                song.get("album", ""),
                duration_ms=song.get("duration_ms"),
            )

            if track_id and track_id not in seen_track_ids:
                seen_track_ids.add(track_id)
                track_ids.append(track_id)
                print(f"Matched: {song['name']} - {', '.join(song['artists'])}")
            else:
                print(f"Not found: {song['name']} - {', '.join(song['artists'])}")
    except SpotifyRateLimitError as error:
        raise RuntimeError(str(error)) from error

    print(f"Matched {len(track_ids)} {source_name} tracks.")
    if not track_ids:
        if source_name == "NetEase recommendations":
            raise RuntimeError(
                "No NetEase recommendations matched valid Spotify tracks. "
                "Keeping the existing Spotify playlist."
            )
        raise RuntimeError(
            f"No {source_name} tracks matched valid Spotify tracks. "
            "Keeping the existing Spotify playlist."
        )
    return track_ids


def main(songs: list[dict] | None = None) -> None:
    settings = load_settings()

    if songs is None:
        print("Getting NetEase daily recommendations...")
        songs = get_daily_recommendations(settings.netease_cookie)
    print(f"Found {len(songs)} NetEase daily recommendations.")

    if not songs:
        raise RuntimeError(
            "NetEase returned an empty recommendation list. "
            "Keeping the existing Spotify playlist."
        )

    radar_playlist_id = getattr(settings, "spotify_radar_playlist_id", None)
    radar_songs = None
    if radar_playlist_id:
        if radar_playlist_id == settings.spotify_playlist_id:
            raise RuntimeError(
                "SPOTIFY_RADAR_PLAYLIST_ID must be different from "
                "SPOTIFY_PLAYLIST_ID because each playlist is replaced separately."
            )
        print("Getting NetEase Private Radar tracks...")
        radar_songs = get_private_radar_tracks(settings.netease_cookie)
        if not radar_songs:
            raise RuntimeError("NetEase Private Radar returned no tracks.")

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
    if radar_playlist_id:
        check_playlist(access_token, radar_playlist_id)

    track_ids = _match_tracks(access_token, songs, "NetEase recommendations")
    radar_track_ids = (
        _match_tracks(access_token, radar_songs, "NetEase Private Radar")
        if radar_songs is not None
        else None
    )

    replace_playlist_tracks(
        access_token,
        settings.spotify_playlist_id,
        track_ids,
    )

    if radar_playlist_id and radar_track_ids:
        replace_playlist_tracks(access_token, radar_playlist_id, radar_track_ids)
        print(
            f"Replaced Spotify Private Radar playlist with {len(radar_track_ids)} tracks."
        )

    print(
        f"Replaced Spotify daily recommendations playlist with {len(track_ids)} tracks."
    )


if __name__ == "__main__":
    main()
