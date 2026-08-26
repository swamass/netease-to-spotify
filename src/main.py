from src.config import load_settings
from src.netease import get_daily_recommendations
from src.spotify import (
    add_tracks_to_playlist,
    get_access_token,
    search_track,
)


def main() -> None:
    settings = load_settings()

    print("Getting NetEase daily recommendations...")
    songs = get_daily_recommendations(settings.netease_cookie)
    print(f"Found {len(songs)} NetEase daily recommendations.")

    print("Getting Spotify access token...")
    access_token = get_access_token(
        settings.spotify_client_id,
        settings.spotify_client_secret,
        settings.spotify_refresh_token,
    )

    track_ids = []

    for song in songs:
        track_id = search_track(
            access_token,
            song["name"],
            song["artists"],
        )

        if track_id:
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
