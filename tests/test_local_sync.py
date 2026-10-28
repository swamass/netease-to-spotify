import json
import os
import plistlib
import stat
import sys
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import scripts.local_sync as local_sync
import scripts.local_launchd as local_launchd
import src.main as production_main


def test_cookie_header_requires_logged_in_session():
    with pytest.raises(RuntimeError):
        local_sync._cookie_header([{"name": "__csrf", "value": "csrf"}])


def test_local_sync_resolves_project_root_for_src_imports(monkeypatch):
    repo_root = str(local_sync.REPO_ROOT)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != repo_root])
    local_sync._ensure_repo_import_path()
    assert sys.path[0] == repo_root


def test_cookie_header_does_not_drop_required_cookie_values():
    cookie = local_sync._cookie_header(
        [
            {"name": "MUSIC_U", "value": "session"},
            {"name": "__csrf", "value": "csrf"},
        ]
    )
    assert cookie == "MUSIC_U=session; __csrf=csrf"


def test_local_env_must_be_private(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SPOTIFY_CLIENT_ID=id",
                "SPOTIFY_CLIENT_SECRET=secret",
                "SPOTIFY_REFRESH_TOKEN=refresh",
                "SPOTIFY_PLAYLIST_ID=playlist",
            ]
        ),
        encoding="utf-8",
    )
    env_file.chmod(0o644)
    with pytest.raises(RuntimeError, match="permissions"):
        local_sync._load_local_env(env_file)


def test_local_env_symlink_is_rejected(tmp_path: Path):
    target = tmp_path / "real.env"
    target.write_text("SPOTIFY_CLIENT_ID=id", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / ".env"
    link.symlink_to(target)
    with pytest.raises(RuntimeError, match="Unsafe Local environment file"):
        local_sync._load_local_env(link)


def test_browser_profile_permissions_and_symlinks_are_rejected(tmp_path: Path):
    profile = tmp_path / "profile"
    profile.mkdir(mode=0o755)
    with pytest.raises(RuntimeError, match="Unsafe directory"):
        local_sync._ensure_secure_directory(profile)

    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Unsafe directory"):
        local_sync._ensure_secure_directory(link)


def test_sensitive_parent_symlink_is_rejected(tmp_path: Path):
    real_parent = tmp_path / "real"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(RuntimeError, match="Unsafe directory path"):
        local_sync._ensure_secure_directory(linked_parent / "app")


def test_state_write_is_atomic_private_and_has_no_fixed_tmp(tmp_path: Path):
    state = tmp_path / "state" / "last-run.json"
    state.parent.mkdir(mode=0o700)
    local_sync._write_state(state, {"last_attempt_date": "2026-10-27"})
    assert json.loads(state.read_text(encoding="utf-8"))["last_attempt_date"] == "2026-10-27"
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    assert not (state.parent / "last-run.tmp").exists()


def test_beijing_schedule_cutoff():
    before = datetime(2026, 10, 27, 6, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    at_cutoff = datetime(2026, 10, 27, 6, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert local_sync._after_schedule(before) is False
    assert local_sync._after_schedule(at_cutoff) is True


def test_scheduled_run_is_once_per_beijing_day(tmp_path: Path):
    now = datetime(2026, 10, 27, 6, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    state = tmp_path / "state" / "last-run.json"
    lock = tmp_path / "state" / "run.lock"
    with local_sync._scheduled_guard(now, state, lock) as should_run:
        assert should_run is True
    with local_sync._scheduled_guard(now.replace(hour=7), state, lock) as should_run:
        assert should_run is False


def test_local_script_fetches_recommendations_once_and_reuses_them(monkeypatch):
    songs = [{"name": "Song", "artists": ["Artist"]}]
    fetched = []
    synced = []
    monkeypatch.setattr(local_sync, "_load_local_env", lambda path: None)
    monkeypatch.setattr(local_sync, "_read_browser_cookie", lambda path: "cookie")
    monkeypatch.setattr(
        "src.netease.get_daily_recommendations",
        lambda cookie: fetched.append(cookie) or songs,
    )
    monkeypatch.setattr("src.main.main", lambda songs=None: synced.append(songs))
    local_sync._run_sync()
    assert fetched == ["cookie"]
    assert synced == [songs]


def test_empty_recommendations_do_not_enter_spotify_sync(monkeypatch):
    synced = []
    monkeypatch.setattr(local_sync, "_load_local_env", lambda path: None)
    monkeypatch.setattr(local_sync, "_read_browser_cookie", lambda path: "cookie")
    monkeypatch.setattr("src.netease.get_daily_recommendations", lambda cookie: [])
    monkeypatch.setattr("src.main.main", lambda songs=None: synced.append(songs))
    with pytest.raises(RuntimeError, match="推荐为空"):
        local_sync._run_sync()
    assert synced == []


def test_recommendation_failure_does_not_enter_spotify_sync(monkeypatch):
    synced = []
    monkeypatch.setattr(local_sync, "_load_local_env", lambda path: None)
    monkeypatch.setattr(local_sync, "_read_browser_cookie", lambda path: "cookie")
    monkeypatch.setattr(
        "src.netease.get_daily_recommendations",
        lambda cookie: (_ for _ in ()).throw(RuntimeError("code 301")),
    )
    monkeypatch.setattr("src.main.main", lambda songs=None: synced.append(songs))
    with pytest.raises(RuntimeError, match="301"):
        local_sync._run_sync()
    assert synced == []


def test_default_production_entry_still_fetches_recommendations(monkeypatch):
    songs = [{"name": "Song", "artists": ["Artist"]}]
    fetched = []
    monkeypatch.setattr(
        production_main,
        "load_settings",
        lambda: SimpleNamespace(
            netease_cookie="cookie",
            spotify_client_id="id",
            spotify_client_secret="secret",
            spotify_refresh_token="refresh",
            spotify_playlist_id="playlist",
        ),
    )
    monkeypatch.setattr(
        production_main,
        "get_daily_recommendations",
        lambda cookie: fetched.append(cookie) or songs,
    )
    monkeypatch.setattr(production_main, "get_access_token", lambda *args: "token")
    monkeypatch.setattr(production_main, "check_playlist", lambda *args: None)
    monkeypatch.setattr(production_main, "search_track", lambda *args, **kwargs: "track")
    monkeypatch.setattr(production_main, "replace_playlist_tracks", lambda *args: None)
    production_main.main()
    assert fetched == ["cookie"]


def test_production_sync_uses_one_playlist_replace_request(monkeypatch):
    calls = []
    monkeypatch.setattr(
        production_main,
        "load_settings",
        lambda: SimpleNamespace(
            netease_cookie="cookie",
            spotify_client_id="id",
            spotify_client_secret="secret",
            spotify_refresh_token="refresh",
            spotify_playlist_id="playlist",
        ),
    )
    monkeypatch.setattr(production_main, "get_access_token", lambda *args: "token")
    monkeypatch.setattr(production_main, "check_playlist", lambda *args: None)
    monkeypatch.setattr(production_main, "search_track", lambda *args, **kwargs: "track-id")
    monkeypatch.setattr(
        production_main,
        "replace_playlist_tracks",
        lambda *args: calls.append(args),
    )
    production_main.main([{"name": "Song", "artists": ["Artist"]}])
    assert calls == [("token", "playlist", ["track-id"])]


def test_zero_matches_do_not_call_playlist_replace(monkeypatch):
    calls = []
    monkeypatch.setattr(
        production_main,
        "load_settings",
        lambda: SimpleNamespace(
            netease_cookie="cookie",
            spotify_client_id="id",
            spotify_client_secret="secret",
            spotify_refresh_token="refresh",
            spotify_playlist_id="playlist",
        ),
    )
    monkeypatch.setattr(production_main, "get_access_token", lambda *args: "token")
    monkeypatch.setattr(production_main, "check_playlist", lambda *args: None)
    monkeypatch.setattr(production_main, "search_track", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        production_main,
        "replace_playlist_tracks",
        lambda *args: calls.append(args),
    )
    with pytest.raises(RuntimeError, match="No NetEase recommendations matched"):
        production_main.main([{"name": "Song", "artists": ["Artist"]}])
    assert calls == []


def test_failure_notification_does_not_include_sensitive_values(monkeypatch):
    calls = []
    monkeypatch.setattr(local_sync.subprocess, "run", lambda args, **kwargs: calls.append(args))
    local_sync._notify_failure()
    rendered = " ".join(" ".join(call) for call in calls)
    assert "cookie" not in rendered.lower()
    assert "secret" not in rendered.lower()
    assert "token" not in rendered.lower()
    assert "不会自动重试" in rendered


def test_launchd_plist_escapes_special_paths_and_validates(tmp_path: Path):
    plist = tmp_path / "Launch Agents" / "sync & test.plist"
    payload = local_launchd.build_plist(
        "/tmp/Python & 3.12",
        "/tmp/sync <script>.py",
        "/tmp/repo 'quoted'",
        "/tmp/logs & local",
    )
    encoded = plistlib.dumps(payload)
    assert plistlib.loads(encoded) == payload
    local_launchd._write_plist(plist, payload)
    assert plistlib.loads(plist.read_bytes()) == payload
    assert stat.S_IMODE(plist.stat().st_mode) == 0o600


def test_launchd_install_failure_restores_existing_plist(tmp_path: Path, monkeypatch):
    plist = tmp_path / "agent.plist"
    log_dir = tmp_path / "logs"
    original = local_launchd.build_plist("old-python", "old-script", "old-repo", str(log_dir))
    local_launchd._write_plist(plist, original)
    monkeypatch.setattr(
        local_launchd.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(returncode=1),
    )
    with pytest.raises(RuntimeError, match="previous configuration was restored"):
        local_launchd.install(plist, "new-python", "new-script", "new-repo", log_dir)
    assert plistlib.loads(plist.read_bytes()) == original
    assert stat.S_IMODE(log_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((log_dir / "sync.log").stat().st_mode) == 0o600
    assert stat.S_IMODE((log_dir / "sync.error.log").stat().st_mode) == 0o600


def test_launchd_install_exception_restores_existing_plist(tmp_path: Path, monkeypatch):
    plist = tmp_path / "agent.plist"
    log_dir = tmp_path / "logs"
    original = local_launchd.build_plist("old-python", "old-script", "old-repo", str(log_dir))
    local_launchd._write_plist(plist, original)
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("launchctl unavailable")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(local_launchd.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="previous configuration was restored"):
        local_launchd.install(plist, "new-python", "new-script", "new-repo", log_dir)
    assert plistlib.loads(plist.read_bytes()) == original
    assert len(calls) == 4


def test_uninstall_only_removes_our_plist(tmp_path: Path, monkeypatch):
    plist = tmp_path / "agent.plist"
    payload = local_launchd.build_plist("python", "script", "repo", str(tmp_path / "logs"))
    local_launchd._write_plist(plist, payload)
    monkeypatch.setattr(
        local_launchd.subprocess,
        "run",
        lambda args, **kwargs: SimpleNamespace(returncode=0),
    )
    local_launchd.uninstall(plist)
    assert not plist.exists()
    assert (tmp_path / "logs").exists() is False
