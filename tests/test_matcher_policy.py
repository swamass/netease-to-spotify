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
