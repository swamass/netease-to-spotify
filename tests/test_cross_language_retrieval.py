from src import spotify
from src.cross_language_retrieval import _display_from_sort_name


class FakeResponse:
    def __init__(self, items):
        self.items = items

    def json(self):
        return {"tracks": {"items": self.items}}


def candidate(track_id, title, artist, album="Album", isrc="TESTISRC"):
    return {
        "id": track_id,
        "name": title,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "external_ids": {"isrc": isrc},
    }


def test_sort_name_is_converted_to_spotify_display_order():
    assert _display_from_sort_name("Yamashita, Tatsuro") == "Tatsuro Yamashita"
    assert _display_from_sort_name("Kadomatsu, Toshiki") == "Toshiki Kadomatsu"


def test_non_latin_sort_name_is_not_used():
    assert _display_from_sort_name("山下, 達郎") is None


def test_retrieval_artist_prefers_natural_latin_alias(monkeypatch):
    monkeypatch.setattr(spotify, "_musicbrainz_artist_ids", lambda _name: {"mbid"})
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, _params: {
            "name": "山下達郎",
            "sort-name": "Yamashita, Tatsuro",
            "aliases": [
                {"name": "山下達郎"},
                {"name": "Tatsuro Yamashita"},
            ],
        },
    )
    assert spotify._cross_language_retrieval_artist("山下達郎") == "Tatsuro Yamashita"


def test_retrieval_artist_uses_reordered_sort_name(monkeypatch):
    monkeypatch.setattr(spotify, "_musicbrainz_artist_ids", lambda _name: {"mbid"})
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, _params: {
            "name": "角松敏生",
            "sort-name": "Kadomatsu, Toshiki",
            "aliases": [],
        },
    )
    assert spotify._cross_language_retrieval_artist("角松敏生") == "Toshiki Kadomatsu"


def test_retrieval_artist_requires_single_exact_mbid(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"one", "two"},
    )
    assert spotify._cross_language_retrieval_artist("山下達郎") is None


def test_retrieval_artist_does_not_rewrite_latin_source(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: (_ for _ in ()).throw(AssertionError("MB should not be called")),
    )
    assert spotify._cross_language_retrieval_artist("CINDY") is None


def test_second_query_uses_latin_artist_only_after_empty_first_search(monkeypatch):
    queries = []
    responses = [
        FakeResponse([]),
        FakeResponse([candidate("music-book", "MUSIC BOOK", "山下達郎")]),
    ]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_cross_language_retrieval_artist",
        lambda _artist: "Tatsuro Yamashita",
    )

    result = spotify.search_track(
        "token",
        "MUSIC BOOK",
        ["山下達郎"],
        "MOONGLOW",
    )

    assert result == "music-book"
    assert len(queries) == 2
    assert 'album:"MOONGLOW"' in queries[0]
    assert 'artist:"山下達郎"' in queries[0]
    assert 'artist:"Tatsuro Yamashita"' in queries[1]
    assert "album:" not in queries[1]


def test_nonempty_first_search_preserves_original_second_query(monkeypatch):
    queries = []
    responses = [
        FakeResponse([candidate("wrong", "Different Song", "山下達郎")]),
        FakeResponse([]),
    ]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_cross_language_retrieval_artist",
        lambda _artist: (_ for _ in ()).throw(
            AssertionError("alternate artist should not be requested")
        ),
    )

    assert spotify.search_track(
        "token",
        "MUSIC BOOK",
        ["山下達郎"],
        "MOONGLOW",
    ) is None
    assert len(queries) == 2
    assert 'artist:"山下達郎"' in queries[1]


def test_failed_first_search_does_not_trigger_retrieval_rewrite(monkeypatch):
    queries = []
    responses = [
        None,
        FakeResponse([]),
    ]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_cross_language_retrieval_artist",
        lambda _artist: (_ for _ in ()).throw(
            AssertionError("network failure must not broaden retrieval")
        ),
    )

    assert spotify.search_track(
        "token",
        "MUSIC BOOK",
        ["山下達郎"],
        "MOONGLOW",
    ) is None
    assert len(queries) == 2
    assert 'artist:"山下達郎"' in queries[1]
