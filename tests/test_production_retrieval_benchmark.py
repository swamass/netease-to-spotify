from src import production_retrieval_benchmark as benchmark


def test_production_benchmark_excludes_missing_reference_and_caps_two_searches(monkeypatch):
    class Response:
        def __init__(self, items):
            self._items = items

        def json(self):
            return {"tracks": {"items": self._items}}

    calls = []

    def fake_get(_url, _token, params, *args, **kwargs):
        calls.append(params)
        return Response([])

    def fake_search_track(token, title, artists, album, diagnostics=None):
        first = benchmark.spotify._spotify_get(
            "https://api.spotify.test/search",
            token,
            {"q": f'track:"{title}" artist:"{artists[0]}"', "type": "track", "limit": 10},
        )
        first.json()
        benchmark.spotify._spotify_get(
            "https://api.spotify.test/search",
            token,
            {"q": f'track:"{title}" {artists[0]}', "type": "track", "limit": 10},
        )
        if diagnostics is not None:
            diagnostics["spotify_search_requests"] = 2
            diagnostics["signals"] = ["RELAXED_SECOND_QUERY_AFTER_ZERO_CANDIDATES"]
        return "accepted-id" if title == "Keep" else None

    monkeypatch.setattr(benchmark.spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(benchmark.spotify, "search_track", fake_search_track)
    monkeypatch.setattr(benchmark.time, "sleep", lambda _seconds: None)

    songs = [
        {"title": "Keep", "artist": "Artist"},
        {"title": "Missing", "artist": "Artist"},
    ]
    missing = [{"title": "Missing", "artist": "Artist"}]

    report = benchmark.benchmark_production(
        "token", songs, missing_reference=missing, delay_seconds=0, baseline_accepted=0
    )

    assert report["reference_success_tracks"] == 1
    assert report["reference_missing_tracks"] == 1
    assert report["accepted_reference"] == 1
    assert report["accepted_all"] == 1
    assert report["spotify_search_requests"] == 4
    assert report["tracks_using_second_search"] == 2
    assert all(row["search_request_count"] <= 2 for row in report["tracks"])
    assert report["delta_from_baseline"] == 1
    assert report["retrieval_signal_counts"] == {
        "RELAXED_SECOND_QUERY_AFTER_ZERO_CANDIDATES": 2
    }
    assert len(calls) == 4


def test_partial_run_does_not_claim_baseline_delta(monkeypatch):
    class Response:
        def json(self):
            return {"tracks": {"items": []}}

    monkeypatch.setattr(benchmark.spotify, "_spotify_get", lambda *_args, **_kwargs: Response())

    def fake_search_track(*_args, **_kwargs):
        raise benchmark.spotify.SpotifyRateLimitError("limited", retry_after_seconds=60)

    monkeypatch.setattr(benchmark.spotify, "search_track", fake_search_track)

    report = benchmark.benchmark_production(
        "token",
        [{"title": "Song", "artist": "Artist"}],
        baseline_accepted=97,
        delay_seconds=0,
    )

    assert report["stopped_early"] is True
    assert report["delta_from_baseline"] is None
