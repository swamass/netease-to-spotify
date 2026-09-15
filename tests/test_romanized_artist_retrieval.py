from src import spotify


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def json(self):
        return {"tracks": {"items": self._items}}


def _candidate(track_id="match", title="余韻", artist="Takao Kisugi"):
    return {
        "id": track_id,
        "name": title,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
        "external_ids": {"isrc": "TESTISRC"},
        "duration_ms": 240000,
    }


def test_retrieval_artist_name_reverses_musicbrainz_sort_name(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda path, _params: {
            "id": "artist-mbid",
            "name": "山下達郎",
            "sort-name": "Yamashita, Tatsuro",
            "aliases": [],
        }
        if path == "artist/artist-mbid"
        else None,
    )

    assert (
        spotify._musicbrainz_retrieval_artist_name("山下達郎")
        == "Tatsuro Yamashita"
    )


def test_retrieval_artist_name_prefers_explicit_latin_alias(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda path, _params: {
            "id": "artist-mbid",
            "name": "山根麻以",
            "sort-name": "Yamane, Mai",
            "aliases": [{"name": "Mai Yamane"}],
        }
        if path == "artist/artist-mbid"
        else None,
    )

    assert spotify._musicbrainz_retrieval_artist_name("山根麻以") == "Mai Yamane"


def test_non_asian_artist_keeps_existing_retrieval(monkeypatch):
    called = False

    def fail_if_called(_name):
        nonlocal called
        called = True
        return {"artist-mbid"}

    monkeypatch.setattr(spotify, "_musicbrainz_artist_ids", fail_if_called)
    assert spotify._musicbrainz_retrieval_artist_name("CINDY") is None
    assert called is False


def test_only_second_spotify_search_uses_romanized_artist(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"artist-mbid"},
    )

    def fake_mb_get(path, _params):
        if path == "artist/artist-mbid":
            return {
                "id": "artist-mbid",
                "name": "来生たかお",
                "sort-name": "Kisugi, Takao",
                "aliases": [],
            }
        if path.startswith("isrc/"):
            return {"recordings": [{"id": "recording-mbid"}]}
        return None

    monkeypatch.setattr(spotify, "_musicbrainz_get", fake_mb_get)
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity_supported",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recording_identity_accepts",
        lambda *_args, **_kwargs: True,
    )

    queries = []
    responses = [FakeResponse([]), FakeResponse([_candidate()])]

    def fake_spotify_get(url, _token, params):
        if url.endswith("/search"):
            queries.append(params["q"])
            return responses.pop(0)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(spotify, "_spotify_get", fake_spotify_get)

    result = spotify.search_track(
        "token",
        "余韻",
        ["来生たかお"],
        "Album",
        duration_ms=240000,
    )

    assert result == "match"
    assert len(queries) == 2
    assert 'artist:"来生たかお"' in queries[0]
    assert 'artist:"Takao Kisugi"' in queries[1]
    assert 'artist:"来生たかお"' not in queries[1]
