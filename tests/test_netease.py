from src import netease


def test_daily_recommendations_requests_and_returns_32_songs(monkeypatch, capsys):
    encrypted_payload = {}
    request = {}
    songs = [
        {
            "name": f"Test Song {index:02d}",
            "ar": [{"name": "Test Artist"}],
            "al": {"name": "Test Album"},
            "dt": 180000,
        }
        for index in range(1, 33)
    ]

    def fake_encrypt(payload):
        encrypted_payload.update(payload)
        return {"params": "encrypted-params", "encSecKey": "encrypted-key"}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 200, "data": {"dailySongs": songs}}

    def fake_post(url, **kwargs):
        request["url"] = url
        request.update(kwargs)
        return Response()

    monkeypatch.setattr(netease, "_encrypt_request", fake_encrypt)
    monkeypatch.setattr(netease.requests, "post", fake_post)

    result = netease.get_daily_recommendations(
        "MUSIC_U=test; __csrf=csrf-token",
        verbose=False,
    )

    assert encrypted_payload == {
        "csrf_token": "csrf-token",
        "limit": "32",
        "offset": "0",
        "total": "true",
    }
    assert request["url"] == netease.WEAPI_URL
    assert request["params"] == {"csrf_token": "csrf-token"}
    assert len(result) == 32
    assert result[0] == {
        "name": "Test Song 01",
        "artists": ["Test Artist"],
        "album": "Test Album",
        "duration_ms": 180000,
    }
    output = capsys.readouterr().out
    assert "Found 32 NetEase daily recommendations." in output
    assert "Test Song 01" not in output
