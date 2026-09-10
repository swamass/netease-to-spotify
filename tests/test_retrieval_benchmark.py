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
    assert [call["offset"] for call in calls] == [0, 10, 0, 0]
    assert report["tracks"][0]["strategies"]["track_only"]["candidate_count"] == 0
