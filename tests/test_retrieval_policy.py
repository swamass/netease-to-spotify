from src import spotify


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def json(self):
        return {"tracks": {"items": self._items}}


def test_retrieval_alias_naturalizes_exact_musicbrainz_sort_name(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda path, params: {
            "artists": [
                {
                    "id": "akimoto-mbid",
                    "name": "秋元薫",
                    "sort-name": "Akimoto, Kaoru",
                    "aliases": [],
                }
            ]
        }
        if path == "artist"
        else None,
    )

    assert spotify._retrieval_artist_alias("秋元薫") == "Kaoru Akimoto"


def test_retrieval_alias_rejects_fuzzy_musicbrainz_result(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda *_args, **_kwargs: {
            "artists": [
                {
                    "id": "wrong-mbid",
                    "name": "秋元",
                    "sort-name": "Akimoto, Kaoru",
                    "aliases": [],
                }
            ]
        },
    )

    assert spotify._retrieval_artist_alias("秋元薫") is None


def test_retrieval_alias_skips_latin_source_without_musicbrainz(monkeypatch):
    calls = []
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda *_args, **_kwargs: calls.append(True),
    )

    assert spotify._retrieval_artist_alias("CINDY") is None
    assert calls == []


def test_second_query_uses_romanized_artist_and_simplified_title(monkeypatch):
    queries = []

    def fake_get(url, _token, params):
        if url.endswith("/search"):
            queries.append(params["q"])
        return FakeResponse([])

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_retrieval_artist_alias",
        lambda source: "Miki Matsubara" if source == "松原みき" else None,
    )

    spotify.search_track(
        "token",
        "真夜中のドア〜stay with me (シングルver.)",
        ["松原みき"],
        "Pocket Park",
    )

    assert len(queries) == 2
    assert 'artist:"松原みき"' in queries[0]
    assert 'album:"Pocket Park"' in queries[0]
    assert queries[1] == 'track:"真夜中のドア〜stay with me" artist:"Miki Matsubara"'


def test_second_query_falls_back_to_original_artist_without_safe_alias(monkeypatch):
    queries = []

    def fake_get(url, _token, params):
        if url.endswith("/search"):
            queries.append(params["q"])
        return FakeResponse([])

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(spotify, "_retrieval_artist_alias", lambda _source: None)

    spotify.search_track("token", "Secret Lover", ["角松敏生"], "After 5 Clash")

    assert len(queries) == 2
    assert queries[1] == 'track:"Secret Lover" artist:"角松敏生"'


def test_first_query_success_never_resolves_retrieval_alias(monkeypatch):
    item = {
        "id": "matched",
        "name": "余韻",
        "artists": [{"name": "来生たかお"}],
        "album": {"name": "Album"},
        "external_ids": {"isrc": "TEST"},
        "duration_ms": 200000,
    }
    calls = []

    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda *_args, **_kwargs: FakeResponse([item]),
    )
    monkeypatch.setattr(
        spotify,
        "_retrieval_artist_alias",
        lambda _source: calls.append(True) or "Takao Kisugi",
    )

    assert spotify.search_track("token", "余韻", ["来生たかお"], "Album") == "matched"
    assert calls == []
