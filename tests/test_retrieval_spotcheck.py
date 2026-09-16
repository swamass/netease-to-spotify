from pathlib import Path

import pytest

from src import retrieval_spotcheck
from src.retrieval_benchmark import parse_lines


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


def test_live_search_scope_rejects_any_track_outside_retrieval_failures():
    allowed = [{"title": "CRESCENT AVENTURE", "artist": "角松敏生"}]
    retrieval_spotcheck.validate_search_scope(
        [{"title": "CRESCENT AVENTURE", "artist": "角松敏生"}], allowed
    )

    with pytest.raises(ValueError, match="Disallowed input"):
        retrieval_spotcheck.validate_search_scope(
            [{"title": "Dress Down", "artist": "秋元薫"}], allowed
        )


def test_baseline_comparison_is_analysis_only():
    report = {"accepted_all": 2}
    baseline = {
        "reference_total": 140,
        "baseline_accepted": 97,
        "retrieval_failures_without_saved_candidates": 37,
        "matcher_failures_with_saved_candidates": 6,
    }

    retrieval_spotcheck.attach_baseline_analysis(report, baseline, sample_size=5)
    comparison = report["analysis_comparison"]

    assert comparison["baseline_accepted"] == 97
    assert comparison["reference_total"] == 140
    assert comparison["baseline_accepted_tracks_searched"] == 0
    assert comparison["saved_candidate_failure_tracks_searched"] == 0
    assert comparison["retrieval_failure_tracks_total"] == 37
    assert comparison["retrieval_failure_sample_tracks"] == 5
    assert comparison["sample_newly_accepted"] == 2


def test_repository_failure_partition_and_spotcheck_scope_are_consistent():
    root = Path(__file__).resolve().parents[1]
    retrieval_failures = parse_lines(
        str(root / "data" / "tunemymusic_retrieval_failures_37.txt")
    )
    saved_candidate_failures = parse_lines(
        str(root / "data" / "tunemymusic_saved_candidate_failures_6.txt")
    )
    spotcheck = parse_lines(str(root / "data" / "retrieval_spotcheck_5.txt"))

    retrieval_keys = {retrieval_spotcheck._song_key(song) for song in retrieval_failures}
    saved_keys = {
        retrieval_spotcheck._song_key(song) for song in saved_candidate_failures
    }
    spotcheck_keys = {retrieval_spotcheck._song_key(song) for song in spotcheck}

    assert len(retrieval_keys) == 37
    assert len(saved_keys) == 6
    assert len(retrieval_keys | saved_keys) == 43
    assert retrieval_keys.isdisjoint(saved_keys)
    assert spotcheck_keys <= retrieval_keys
