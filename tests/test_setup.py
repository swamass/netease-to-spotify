import base64
import os
import stat
from urllib.parse import parse_qs, urlparse

import pytest

import setup


def test_playlist_url_and_raw_id():
    assert setup.playlist_id_from_input("abc123") == "abc123"
    assert setup.playlist_id_from_input(
        "https://open.spotify.com/playlist/abc123"
    ) == "abc123"


def test_invalid_playlist_input():
    with pytest.raises(ValueError):
        setup.playlist_id_from_input("https://open.spotify.com/album/abc123")
    with pytest.raises(ValueError):
        setup.playlist_id_from_input("bad id")


def test_authorization_url_uses_required_scope_and_state():
    url = setup.build_authorization_url("client", "state-value")
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == [setup.SPOTIFY_SCOPE]
    assert query["state"] == ["state-value"]
    assert query["redirect_uri"] == [setup.REDIRECT_URI]
    assert query["scope"] == ["playlist-read-private playlist-modify-private"]


def test_public_scope_is_opt_in():
    url = setup.build_authorization_url("client", "state", setup.SPOTIFY_PUBLIC_SCOPE)
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == [setup.SPOTIFY_PUBLIC_SCOPE]


def test_callback_state_validation():
    callback = (
        f"{setup.REDIRECT_URI}?code=code-value&state=state-value"
    )
    assert setup.extract_callback_code(callback, "state-value") == "code-value"
    with pytest.raises(ValueError):
        setup.extract_callback_code(callback, "wrong-state")


def test_callback_authorization_error_is_rejected():
    callback = f"{setup.REDIRECT_URI}?error=access_denied&state=state-value"
    with pytest.raises(ValueError, match="authorization failed"):
        setup.extract_callback_code(callback, "state-value")


def test_callback_timeout_is_reported(monkeypatch):
    class FakeServer:
        callback = None
        timeout = None

        def handle_request(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(setup, "HTTPServer", lambda *args: FakeServer())
    clock = iter((0, 301))
    monkeypatch.setattr(setup.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        setup.receive_callback(timeout=300)


def test_token_exchange_does_not_expose_secret(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"refresh_token": "refresh-token"}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(setup.requests, "post", fake_post)
    assert setup.exchange_code("client", "secret", "code") == "refresh-token"
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["timeout"] == 30
    assert "secret" not in str(captured.get("data", {}))


def test_save_credentials_preserves_existing_env_and_writes_atomically(tmp_path, monkeypatch):
    env_dir = tmp_path / "config"
    env_path = env_dir / ".env"
    env_dir.mkdir(mode=0o700)
    env_path.write_text(
        "# keep this\nSPOTIFY_PLAYLIST_ID=existing-playlist\nOTHER=value\n",
        encoding="utf-8",
    )
    env_path.chmod(0o600)
    replaced = []
    original_replace = setup.os.replace
    monkeypatch.setattr(setup.os, "replace", lambda source, target: (replaced.append((source, target)), original_replace(source, target))[1])

    setup.save_credentials("new-id", "new-secret", "new-refresh", path=env_path)

    content = env_path.read_text(encoding="utf-8")
    assert "# keep this" in content
    assert "OTHER=value" in content
    assert "SPOTIFY_PLAYLIST_ID=existing-playlist" in content
    assert "SPOTIFY_CLIENT_ID=new-id" in content
    assert "SPOTIFY_CLIENT_SECRET=new-secret" in content
    assert "SPOTIFY_REFRESH_TOKEN=new-refresh" in content
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
    assert len(replaced) == 1
    assert not list(env_dir.glob(".env.*"))


def test_save_credentials_rejects_env_symlink(tmp_path):
    env_dir = tmp_path / "config"
    env_dir.mkdir(mode=0o700)
    target = env_dir / "real.env"
    target.write_text("OTHER=value\n", encoding="utf-8")
    target.chmod(0o600)
    env_path = env_dir / ".env"
    env_path.symlink_to(target)
    with pytest.raises(RuntimeError, match="Unsafe environment file"):
        setup.save_credentials("id", "secret", "refresh", path=env_path)
