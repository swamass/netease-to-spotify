import pytest

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
        status_code = 200

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


@pytest.mark.parametrize(
    ("cookie", "message"),
    [
        ("__csrf=csrf-token", "MUSIC_U"),
        ("MUSIC_U=session", "__csrf"),
        ("MUSIC_U=; __csrf=csrf-token", "MUSIC_U"),
        ("MUSIC_U=session; __csrf=", "__csrf"),
    ],
)
def test_missing_or_empty_required_cookie_is_classified_safely(cookie, message):
    with pytest.raises(netease.NetEaseCookieError, match=message):
        netease.get_daily_recommendations(cookie, verbose=False)


def test_http_auth_failure_is_classified_without_response_body(monkeypatch):
    class Response:
        status_code = 401
        text = "secret-looking response body"

    monkeypatch.setattr(netease.requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(netease.NetEaseAuthenticationError) as error:
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )

    assert "secret-looking" not in str(error.value)


def test_network_failure_is_classified(monkeypatch):
    def fail(*args, **kwargs):
        raise netease.requests.exceptions.Timeout("secret-looking request detail")

    monkeypatch.setattr(netease.requests, "post", fail)

    with pytest.raises(netease.NetEaseNetworkError, match="request failed"):
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )


@pytest.mark.parametrize(
    ("http_status", "business_code", "expected"),
    [
        (500, 200, netease.NetEaseHTTPError),
        (200, 301, netease.NetEaseAPIError),
    ],
)
def test_http_and_business_failures_are_distinct(
    monkeypatch,
    http_status,
    business_code,
    expected,
):
    class Response:
        status_code = http_status

        def json(self):
            return {"code": business_code}

    monkeypatch.setattr(netease.requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(expected):
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )


def test_invalid_json_and_response_structure_are_classified(monkeypatch):
    class InvalidJSONResponse:
        status_code = 200

        def json(self):
            raise ValueError("secret-looking response body")

    monkeypatch.setattr(
        netease.requests,
        "post",
        lambda *args, **kwargs: InvalidJSONResponse(),
    )
    with pytest.raises(netease.NetEaseResponseError) as error:
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )
    assert "secret-looking" not in str(error.value)

    class InvalidStructureResponse:
        status_code = 200

        def json(self):
            return {"code": 200, "data": {"dailySongs": {}}}

    monkeypatch.setattr(
        netease.requests,
        "post",
        lambda *args, **kwargs: InvalidStructureResponse(),
    )
    with pytest.raises(netease.NetEaseResponseError):
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )


def test_empty_recommendations_are_classified(monkeypatch):
    class Response:
        status_code = 200

        def json(self):
            return {"code": 200, "data": {"dailySongs": []}}

    monkeypatch.setattr(netease.requests, "post", lambda *args, **kwargs: Response())

    with pytest.raises(netease.NetEaseEmptyRecommendationsError):
        netease.get_daily_recommendations(
            "MUSIC_U=session; __csrf=csrf-token",
            verbose=False,
        )
