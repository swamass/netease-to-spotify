import requests


API_BASE_URL = "https://wyy.yiton.uk"
DAILY_RECOMMENDATIONS_URL = f"{API_BASE_URL}/recommend/songs"
PLAYLIST_TRACKS_URL = f"{API_BASE_URL}/playlist/track/all"
PRIVATE_RADAR_PLAYLIST_ID = "3136952023"


def _artist_names(song: dict) -> list[str]:
    raw_artists = song.get("ar") or song.get("artists") or song.get("artist") or []
    if isinstance(raw_artists, dict):
        raw_artists = [raw_artists]
    if isinstance(raw_artists, str):
        return [artist.strip() for artist in raw_artists.split("/") if artist.strip()]
    return [
        artist.get("name", "")
        for artist in raw_artists
        if isinstance(artist, dict) and artist.get("name")
    ]


def _normalize_song(song: dict) -> dict:
    duration = song.get("dt") or song.get("duration_ms") or song.get("duration")
    try:
        duration_ms = int(duration)
    except (TypeError, ValueError):
        duration_ms = None
    if duration_ms is not None and duration_ms <= 0:
        duration_ms = None

    album = song.get("al") or song.get("album") or {}
    if isinstance(album, str):
        album_name = album
    else:
        album_name = album.get("name", "") if isinstance(album, dict) else ""

    return {
        "name": song.get("name", ""),
        "artists": _artist_names(song),
        "album": album_name,
        "duration_ms": duration_ms,
    }


def _fetch_songs(
    url: str,
    cookie: str,
    *,
    params: dict,
    song_list_path: tuple[str, ...],
    source_name: str,
) -> list[dict]:
    response = requests.get(
        url,
        params=params,
        headers={
            "Cookie": cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://music.163.com/",
        },
        timeout=30,
    )
    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"NetEase API returned non-JSON response for {source_name}: "
            f"{response.text[:500]}"
        ) from exc

    if data.get("code") != 200:
        raise RuntimeError(
            f"NetEase API returned code {data.get('code')} for {source_name}: "
            f"{data.get('message', data.get('msg', 'unknown error'))}"
        )

    songs = data
    for key in song_list_path:
        songs = songs.get(key, {}) if isinstance(songs, dict) else {}
    if not isinstance(songs, list):
        raise RuntimeError(f"NetEase API returned an invalid song list for {source_name}.")
    if not songs:
        raise RuntimeError(f"NetEase returned no songs for {source_name}.")

    return [_normalize_song(song) for song in songs]


def _print_songs(source_name: str, songs: list[dict], *, verbose: bool) -> None:
    if verbose:
        print(f"\n===== NetEase {source_name} =====")
        for index, song in enumerate(songs, start=1):
            print(f"{index:02d}. {song['name']} - {', '.join(song['artists'])}")
        print("=" * (len(source_name) + 19))
    item_name = (
        "daily recommendations"
        if source_name == "Daily Recommendations"
        else "Private Radar tracks"
    )
    print(f"Found {len(songs)} NetEase {item_name}.\n")


def get_daily_recommendations(cookie: str, *, verbose: bool = True) -> list[dict]:
    """Fetch the logged-in account's NetEase daily recommendations."""
    songs = _fetch_songs(
        DAILY_RECOMMENDATIONS_URL,
        cookie,
        params={},
        song_list_path=("data", "dailySongs"),
        source_name="Daily Recommendations",
    )
    _print_songs("Daily Recommendations", songs, verbose=verbose)
    return songs


def get_private_radar_tracks(cookie: str, *, verbose: bool = True) -> list[dict]:
    """Fetch tracks in NetEase's daily-updated Private Radar playlist."""
    songs = _fetch_songs(
        PLAYLIST_TRACKS_URL,
        cookie,
        params={"id": PRIVATE_RADAR_PLAYLIST_ID, "limit": 1000, "offset": 0},
        song_list_path=("songs",),
        source_name="Private Radar",
    )
    _print_songs("Private Radar", songs, verbose=verbose)
    return songs
