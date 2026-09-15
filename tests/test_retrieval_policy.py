from src import spotify


class FakeResponse:
    def __init__(self, items):
        self.items = items

    def json(self):
        return {"tracks": {"items": self.items}}


def candidate(track_id="track", title="Song", artist="山下達郎"):
    return {
        "id": track_id,
        "name": title,
        "artists": [{"name": artist}],
        "album": {"name": "Album"},
        "external_ids": {"isrc": "TESTISRC"},
        "duration_ms": 240000,
    }


def _mb_artist(monkeypatch, source, *, ids=None, detail=None):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda name: set(ids or {"artist-mbid"}) if name == source else set(),
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda path, _params: detail
        if path == "artist/artist-mbid"
        else None,
    )


def test_retrieval_artist_name_prefers_display_alias(monkeypatch):
    _mb_artist(
        monkeypatch,
        "山下達郎",
        detail={
            "name": "山下達郎",
            "sort-name": "Yamashita, Tatsuro",
            "aliases": [{"name": "Tatsuro Yamashita"}],
        },
    )
    assert spotify._musicbrainz_retrieval_artist_name("山下達郎") == "Tatsuro Yamashita"


def test_retrieval_artist_name_reorders_sort_name(monkeypatch):
    _mb_artist(
        monkeypatch,
        "角松敏生",
        detail={
            "name": "角松敏生",
            "sort-name": "Kadomatsu, Toshiki",
            "aliases": [],
        },
    )
    assert spotify._musicbrainz_retrieval_artist_name("角松敏生") == "Toshiki Kadomatsu"


def test_query2_uses_mb_display_artist_only_when_query1_is_empty(monkeypatch):
    queries = []
    responses = [FakeResponse([]), FakeResponse([])]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    _mb_artist(
        monkeypatch,
        "山下達郎",
        detail={
            "name": "山下達郎",
            "sort-name": "Yamashita, Tatsuro",
            "aliases": [{"name": "Tatsuro Yamashita"}],
        },
    )

    assert spotify.search_track("token", "MUSIC BOOK", ["山下達郎"], "Album") is None
    assert len(queries) == 2
    assert 'artist:"山下達郎"' in queries[0]
    assert 'album:"Album"' in queries[0]
    assert queries[1] == 'track:"MUSIC BOOK" artist:"Tatsuro Yamashita"'


def test_query2_keeps_source_artist_when_query1_has_candidates(monkeypatch):
    queries = []
    exact = candidate(title="Song", artist="山下達郎")
    responses = [FakeResponse([exact]), FakeResponse([])]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_retrieval_artist_name",
        lambda _artist: "Tatsuro Yamashita",
    )

    assert spotify.search_track("token", "Song", ["山下達郎"], "") == "track"
    assert len(queries) == 2
    assert queries[1] == 'track:"Song" artist:"山下達郎"'


def test_query2_keeps_source_artist_when_mb_identity_is_ambiguous(monkeypatch):
    queries = []
    responses = [FakeResponse([]), FakeResponse([])]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"one", "two"},
    )

    assert spotify.search_track("token", "Song", ["山下達郎"], "") is None
    assert len(queries) == 2
    assert queries[1] == 'track:"Song" artist:"山下達郎"'


def test_non_asian_source_artist_never_uses_mb_retrieval_fallback(monkeypatch):
    queries = []
    responses = [FakeResponse([]), FakeResponse([])]

    def fake_get(_url, _token, params):
        queries.append(params["q"])
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda _name: {"artist-mbid"},
    )

    assert spotify.search_track("token", "Song", ["CINDY"], "") is None
    assert len(queries) == 2
    assert queries[1] == 'track:"Song" artist:"CINDY"'
