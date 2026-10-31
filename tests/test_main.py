from types import SimpleNamespace

import pytest

import src.main as sync_main


def test_radar_sync_uses_a_separate_spotify_playlist(monkeypatch):
    settings = SimpleNamespace(
        netease_cookie="cookie",
        spotify_client_id="client",
        spotify_client_secret="secret",
        spotify_refresh_token="refresh",
        spotify_playlist_id="daily-playlist",
        spotify_radar_playlist_id="radar-playlist",
    )
    daily = [{"name": "Daily Song", "artists": ["Artist"]}]
    radar = [{"name": "Radar Song", "artists": ["Artist"]}]
    replaces = []
    monkeypatch.setattr(sync_main, "load_settings", lambda: settings)
    monkeypatch.setattr(sync_main, "get_daily_recommendations", lambda cookie: daily)
    monkeypatch.setattr(sync_main, "get_private_radar_tracks", lambda cookie: radar)
    monkeypatch.setattr(sync_main, "get_access_token", lambda *args: "token")
    monkeypatch.setattr(sync_main, "check_playlist", lambda *args: None)
    monkeypatch.setattr(sync_main, "search_track", lambda *args, **kwargs: "track-id")
    monkeypatch.setattr(
        sync_main,
        "replace_playlist_tracks",
        lambda *args: replaces.append(args),
    )

    sync_main.main()

    assert replaces == [
        ("token", "daily-playlist", ["track-id"]),
        ("token", "radar-playlist", ["track-id"]),
    ]


def test_radar_target_cannot_overwrite_daily_target(monkeypatch):
    monkeypatch.setattr(
        sync_main,
        "load_settings",
        lambda: SimpleNamespace(
            netease_cookie="cookie",
            spotify_client_id="client",
            spotify_client_secret="secret",
            spotify_refresh_token="refresh",
            spotify_playlist_id="same-playlist",
            spotify_radar_playlist_id="same-playlist",
        ),
    )

    with pytest.raises(RuntimeError, match="must be different"):
        sync_main.main([{"name": "Song", "artists": ["Artist"]}])
