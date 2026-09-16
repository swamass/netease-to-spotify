from src import retrieval_spotcheck


def test_spotcheck_hard_caps_spotify_search_requests(monkeypatch):
    class Response:
        def json(self):
            return {"tracks": {"items": []}}

    real_calls = []

    def fake_get(url, token, params, *args, **kwargs):
        real_calls.append(params)
        return Response()

    def fake_benchmark(access_token, songs, **kwargs):
        for index in range(20):
            retrieval_spotcheck.spotify._spotify_get(
                "https://api.spotify.test/v1/search",
                access_token,
                {"q": f"song-{index}", "type": "track"},
            )
        return {"read_only": True, "stopped_early": False, "tracks": []}

    monkeypatch.setattr(retrieval_spotcheck.spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(retrieval_spotcheck, "benchmark_production", fake_benchmark)

    report = retrieval_spotcheck.run_spotcheck(
        "token", [{"title": "Song", "artist": "Artist"}], max_search_requests=10
    )

    assert len(real_calls) == 10
    assert report["stopped_early"] is True
    assert report["stop_reason"] == "SEARCH_BUDGET_EXHAUSTED"
    assert report["budgeted_search_requests"] == 10
    assert report["search_budget"] == 10


def test_spotcheck_restores_spotify_get(monkeypatch):
    class Response:
        def json(self):
            return {"tracks": {"items": []}}

    def fake_get(*args, **kwargs):
        return Response()

    monkeypatch.setattr(retrieval_spotcheck.spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        retrieval_spotcheck,
        "benchmark_production",
        lambda *args, **kwargs: {
            "read_only": True,
            "stopped_early": False,
            "tracks": [],
            "spotify_search_requests": 0,
        },
    )

    original = retrieval_spotcheck.spotify._spotify_get
    report = retrieval_spotcheck.run_spotcheck(
        "token", [{"title": "Song", "artist": "Artist"}], max_search_requests=10
    )

    assert retrieval_spotcheck.spotify._spotify_get is original
    assert report["spotcheck"] is True
