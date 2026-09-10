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
    monkeypatch.setattr(retrieval_benchmark.time, "sleep", lambda seconds: sleeps.append(seconds))
    retrieval_benchmark.benchmark("token", [{"title": "Song", "artist": "Artist"}], 0.25)
    assert sleeps == [0.25, 0.25]
