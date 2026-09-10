from src import retrieval_benchmark


def test_parse_lines_uses_last_separator(tmp_path):
    path = tmp_path / "songs.txt"
    path.write_text("No More - Love - Artist\ninvalid\n", encoding="utf-8")
    assert retrieval_benchmark.parse_lines(str(path)) == [{"title": "No More - Love", "artist": "Artist"}]


def test_build_queries_are_structured_and_sanitized():
    queries = retrieval_benchmark.build_queries({"title": 'No More "Love"', "artist": "Artist",})
    assert queries["structured_page_0"]["q"] == 'track:"No More Love" artist:"Artist"'
    assert queries["structured_page_10"]["offset"] == 10
    assert queries["simplified_title"]["q"] == 'track:"No More Love" artist:"Artist"'


def test_benchmark_uses_offsets_and_never_playlist_writes(monkeypatch):
    calls = []

    class Response:
        def json(self):
            return {"tracks": {"items": []}}

    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: calls.append(args[2]) or Response())
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: set())
    report = retrieval_benchmark.benchmark("token", [{"title": "Song", "artist": "Artist"}])
    assert [call["offset"] for call in calls] == [0, 10, 0]
    assert report["tracks"][0]["strategies"]["track_only"]["candidate_count"] == 0
    assert report["logical_searches"] == 4
    assert report["real_spotify_searches"] == 3
    assert report["cache_hits"] == 1
    assert report["tracks"][0]["strategies"]["simplified_title"]["cache_hit"] is True


def test_request_key_distinguishes_offset_and_query():
    first = {"q": "track:\"Song\"", "type": "track", "limit": 10, "offset": 0}
    second = {**first, "offset": 10}
    third = {**first, "q": "track:\"Other\""}
    assert retrieval_benchmark._request_key(first) != retrieval_benchmark._request_key(second)
    assert retrieval_benchmark._request_key(first) != retrieval_benchmark._request_key(third)


def test_delay_applies_only_to_real_requests(monkeypatch):
    sleeps = []
    class Response:
        def json(self):
            return {"tracks": {"items": []}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: Response())
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: set())
    monkeypatch.setattr(retrieval_benchmark.time, "sleep", lambda seconds: sleeps.append(seconds))
    retrieval_benchmark.benchmark("token", [{"title": "Song", "artist": "Artist"}], 0.25)
    assert sleeps == [0.25, 0.25]


def test_artist_alias_uses_same_mbid_and_original_title(monkeypatch):
    calls = []
    class Response:
        def json(self):
            return {"tracks": {"items": []}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: calls.append(args[2]) or Response())
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda name: {"mbid"} if name == "角松敏生" else set())
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_names", lambda _mbid: {"角松敏生", "toshiki kadomatsu"})
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_get", lambda *_args: {"name": "角松敏生", "aliases": [{"name": "Toshiki Kadomatsu"}]})
    report = retrieval_benchmark.benchmark("token", [{"title": "曲名", "artist": "角松敏生"}], 0)
    alias = report["tracks"][0]["strategies"]["artist_alias"]
    assert alias["mbid"] == "mbid"
    assert alias["alternate_artist"] == "Toshiki Kadomatsu"
    assert 'track:"曲名" artist:"Toshiki Kadomatsu"' == alias["query"]


def test_ambiguous_or_unavailable_artist_alias_is_skipped(monkeypatch):
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: set())
    report = retrieval_benchmark.benchmark("token", [{"title": "Song", "artist": "Artist / Guest"}], 0)
    assert report["tracks"][0]["strategies"]["artist_alias"]["skipped"] is True


def test_repeated_source_artist_reuses_musicbrainz_cache(monkeypatch):
    lookups = []
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda name: lookups.append(name) or {"mbid"})
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_names", lambda _mbid: {"角松敏生", "toshiki kadomatsu"})
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_get", lambda *_args: {"name": "角松敏生", "aliases": [{"name": "Toshiki Kadomatsu"}]})
    class Response:
        def json(self):
            return {"tracks": {"items": []}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: Response())
    report = retrieval_benchmark.benchmark("token", [
        {"title": "One", "artist": "角松敏生"},
        {"title": "Two", "artist": "角松敏生"},
    ], 0)
    assert lookups == ["角松敏生"]
    assert report["unique_musicbrainz_artist_lookups"] == 1


def test_existing_structured_candidates_skip_musicbrainz_alias_lookup(monkeypatch):
    lookups = []
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda name: lookups.append(name) or {"mbid"})
    class Response:
        def json(self):
            return {"tracks": {"items": [{"id": "track", "name": "Song", "artists": [{"name": "Artist"}], "album": {"name": "Album"}}]}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: Response())
    report = retrieval_benchmark.benchmark("token", [{"title": "Song", "artist": "Artist"}], 0)
    assert lookups == []
    assert "artist_alias" not in report["tracks"][0]["strategies"]


def test_resolved_mbid_without_alternate_skips_spotify_alias_search(monkeypatch):
    calls = []
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: {"mbid"})
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_names", lambda _mbid: {"角松敏生"})
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_get", lambda *_args: {"name": "角松敏生", "aliases": []})
    class Response:
        def json(self):
            return {"tracks": {"items": []}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: calls.append(args[2]["q"]) or Response())
    report = retrieval_benchmark.benchmark("token", [{"title": "曲名", "artist": "角松敏生"}], 0)
    assert report["tracks"][0]["strategies"]["artist_alias"]["skipped"] is True
    assert len(calls) == 3


def test_long_rate_limit_returns_partial_report_without_finishing_row(monkeypatch):
    calls = []
    class RateLimit( retrieval_benchmark.spotify.SpotifyRateLimitError):
        retry_after_seconds = 67776
    def fake_get(*args):
        calls.append(args[2])
        if len(calls) == 1:
            raise RateLimit("long retry")
        raise AssertionError("request after rate limit")
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: (_ for _ in ()).throw(AssertionError("MusicBrainz called")))
    report = retrieval_benchmark.benchmark("token", [
        {"title": "First", "artist": "Artist"}, {"title": "Second", "artist": "Artist"}
    ], 0)
    assert report["tracks"] == []
    assert report["completed_input_rows"] == 0
    assert report["stopped_early"] is True
    assert report["stop_reason"] == "SPOTIFY_RATE_LIMIT"
    assert report["retry_after_seconds"] == 67776
    assert report["next_start_index"] == 0
    assert len(calls) == 1


def test_start_index_skips_earlier_rows_and_preserves_original_indexes(monkeypatch):
    class Response:
        def json(self):
            return {"tracks": {"items": []}}
    monkeypatch.setattr(retrieval_benchmark.spotify, "_spotify_get", lambda *args: Response())
    monkeypatch.setattr(retrieval_benchmark.spotify, "_musicbrainz_artist_ids", lambda _name: set())
    songs = [{"title": "One", "artist": "A"}, {"title": "Two", "artist": "B"}, {"title": "Three", "artist": "C"}]
    report = retrieval_benchmark.benchmark("token", songs, 0, start_index=1)
    assert [entry["input_index"] for entry in report["tracks"]] == [1, 2]
    assert report["start_index"] == 1
    assert report["total_input_rows"] == 3


def test_alias_from_ambiguous_other_mbid_is_never_selected(monkeypatch):
    monkeypatch.setattr(
        retrieval_benchmark.spotify, "_musicbrainz_artist_ids",
        lambda _name: {"source-mbid", "other-mbid"},
    )
    assert retrieval_benchmark._artist_alias("角松敏生", {}) is None
