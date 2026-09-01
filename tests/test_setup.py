import base64
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


def test_callback_state_validation():
    callback = (
        f"{setup.REDIRECT_URI}?code=code-value&state=state-value"
    )
    assert setup.extract_callback_code(callback, "state-value") == "code-value"
    with pytest.raises(ValueError):
        setup.extract_callback_code(callback, "wrong-state")


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
