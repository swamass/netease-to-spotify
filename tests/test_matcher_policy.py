from src import spotify


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


def test_matching_title_and_confirmed_artist_survives_missing_mb_recording(monkeypatch):
    item = candidate("yo-in", "余韻", "Takao Kisugi", isrc="JPKT08900101")
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity",
        lambda *_args, **_kwargs: {"same-artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recordings_for_isrc",
        lambda _isrc: [],
    )

    assert spotify._musicbrainz_recording_identity_accepts(
        "余韻", ["来生たかお"], "", item
    ) is True


def test_cross_script_title_still_requires_recording_evidence(monkeypatch):
    item = candidate("tokai", "Tokai", "Taeko Onuki", isrc="TESTTOKAI")
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity",
        lambda *_args, **_kwargs: {"same-artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recordings_for_isrc",
        lambda _isrc: [],
    )

    assert spotify._musicbrainz_recording_identity_accepts(
        "都会", ["大貫妙子"], "", item, allow_cross_script_title=True
    ) is False


def test_version_conflict_remains_hard_reject(monkeypatch):
    item = candidate(
        "remix",
        "余韻 - Remix",
        "Takao Kisugi",
        isrc="TESTREMIX",
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity",
        lambda *_args, **_kwargs: {"same-artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recordings_for_isrc",
        lambda _isrc: [],
    )

    assert spotify._musicbrainz_recording_identity_accepts(
        "余韻", ["来生たかお"], "", item
    ) is False


def test_wrong_artist_remains_hard_reject(monkeypatch):
    item = candidate("wrong", "RIDE ON TIME", "Black Box", isrc="TESTWRONG")
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity",
        lambda *_args, **_kwargs: set(),
    )

    assert spotify._musicbrainz_recording_identity_accepts(
        "RIDE ON TIME", ["山下達郎"], "", item
    ) is False


def test_search_track_accepts_confirmed_cross_language_artist_without_mb_recording(monkeypatch):
    item = candidate("yo-in", "余韻", "Takao Kisugi", isrc="JPKT08900101")
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda *_args, **_kwargs: FakeResponse([item]),
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity_supported",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity",
        lambda *_args, **_kwargs: {"same-artist-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recordings_for_isrc",
        lambda _isrc: [],
    )

    assert spotify.search_track(
        "test-token", "余韻", ["来生たかお"], ""
    ) == "yo-in"


def test_artist_id_resolver_ignores_fuzzy_field_hit_and_uses_exact_fallback_alias(monkeypatch):
    responses = [
        {"artists": [{"id": "wrong", "name": "Kaoru", "aliases": []}]},
        {"artists": [{
            "id": "akimoto-mbid",
            "name": "秋元薫",
            "sort-name": "Akimoto, Kaoru",
            "aliases": [{"name": "Kaoru Akimoto"}],
        }]},
    ]
    queries = []
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, params: queries.append(params["query"]) or responses.pop(0),
    )

    assert spotify._musicbrainz_artist_ids("Kaoru Akimoto") == {"akimoto-mbid"}
    assert queries == ['artist:"Kaoru Akimoto"', "Kaoru Akimoto"]


def test_artist_id_resolver_accepts_exact_alias_from_field_search(monkeypatch):
    calls = []
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, params: calls.append(params["query"]) or {
            "artists": [{
                "id": "yuko-mbid",
                "name": "今井優子",
                "aliases": [{"name": "Yuko Imai"}],
            }]
        },
    )

    assert spotify._musicbrainz_artist_ids("Yuko Imai") == {"yuko-mbid"}
    assert calls == ['artist:"Yuko Imai"']


def test_artist_id_resolver_rejects_unrelated_fuzzy_results(monkeypatch):
    responses = [
        {"artists": [{"id": "one", "name": "Omega Tribe Tribute", "aliases": []}]},
        {"artists": [{"id": "two", "name": "Omega", "aliases": [{"name": "Other Band"}]}]},
    ]
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, _params: responses.pop(0),
    )

    assert spotify._musicbrainz_artist_ids("1986 OMEGA TRIBE") == set()


def test_artist_identity_can_intersect_japanese_and_romanized_alias_results(monkeypatch):
    payloads = {
        'artist:"秋元薫"': {
            "artists": [{"id": "akimoto-mbid", "name": "秋元薫", "aliases": []}]
        },
        'artist:"Kaoru Akimoto"': {
            "artists": [{
                "id": "akimoto-mbid",
                "name": "秋元薫",
                "aliases": [{"name": "Kaoru Akimoto"}],
            }]
        },
    }
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, params: payloads[params["query"]],
    )

    assert spotify._musicbrainz_artist_identity(
        ["秋元薫"], [{"name": "Kaoru Akimoto"}]
    ) == {"akimoto-mbid"}
