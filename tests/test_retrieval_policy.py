from src import spotify


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def json(self):
        return {"tracks": {"items": self._items}}


def candidate(track_id, title, artist, album="Album", isrc="TESTISRC"):
    return {
        "id": track_id,
        "name": title,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "external_ids": {"isrc": isrc},
        "duration_ms": 240000,
    }


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


def test_second_query_prefers_romanized_artist_after_zero_first_candidates(monkeypatch):
    calls = []
    responses = [FakeResponse([]), FakeResponse([])]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_retrieval_artist_alias",
        lambda source: "Miki Matsubara" if source == "松原みき" else None,
    )

    assert spotify.search_track(
        "token",
        "真夜中のドア〜stay with me (シングルver.)",
        ["松原みき"],
        "Pocket Park",
    ) is None

    assert len(calls) == 2
    assert 'artist:"松原みき"' in calls[0]["q"]
    assert 'album:"Pocket Park"' in calls[0]["q"]
    assert calls[1]["q"] == (
        'track:"真夜中のドア〜stay with me" artist:"Miki Matsubara"'
    )


def test_second_query_uses_free_artist_text_when_no_safe_alias(monkeypatch):
    calls = []
    responses = [
        FakeResponse([]),
        FakeResponse([candidate("dress", "Dress Down", "秋元薫")]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(spotify, "_retrieval_artist_alias", lambda _source: None)

    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "Cologne") == "dress"
    assert len(calls) == 2
    assert 'artist:"秋元薫"' in calls[0]["q"]
    assert 'album:"Cologne"' in calls[0]["q"]
    assert calls[1]["q"] == 'track:"Dress Down" 秋元薫'
    assert "artist:" not in calls[1]["q"]


def test_second_query_stays_strict_when_first_search_has_candidates(monkeypatch):
    calls = []
    alias_calls = []
    responses = [
        FakeResponse([candidate("wrong", "RIDE ON TIME", "Black Box")]),
        FakeResponse([]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_retrieval_artist_alias",
        lambda _source: alias_calls.append(True) or "Tatsuro Yamashita",
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity_supported",
        lambda *_args, **_kwargs: False,
    )

    assert spotify.search_track(
        "token", "RIDE ON TIME", ["山下達郎"], "Ride On Time"
    ) is None
    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"RIDE ON TIME" artist:"山下達郎"'
    assert alias_calls == []


def test_relaxed_second_query_does_not_accept_wrong_same_title_artist(monkeypatch):
    calls = []
    responses = [
        FakeResponse([]),
        FakeResponse([
            candidate(
                "wrong", "RIDE ON TIME", "Black Box", isrc="GBCMX0509001"
            )
        ]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(spotify, "_retrieval_artist_alias", lambda _source: None)
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_identity_supported",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_recording_identity_accepts",
        lambda *_args, **_kwargs: False,
    )

    assert spotify.search_track(
        "token", "RIDE ON TIME", ["山下達郎"], "Ride On Time"
    ) is None
    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"RIDE ON TIME" 山下達郎'


def test_zero_candidate_retrieval_fallback_never_exceeds_two_searches(monkeypatch):
    calls = []

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return FakeResponse([])

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(spotify, "_retrieval_artist_alias", lambda _source: None)

    assert spotify.search_track(
        "token", "Unknown Song", ["未知艺人"], "Unknown Album"
    ) is None
    assert len(calls) == 2
