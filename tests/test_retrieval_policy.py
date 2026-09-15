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


def test_second_query_relaxes_only_after_zero_first_candidates(monkeypatch):
    calls = []
    responses = [
        FakeResponse([]),
        FakeResponse([candidate("dress", "Dress Down", "秋元薫")]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)

    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "Cologne") == "dress"
    assert len(calls) == 2
    assert 'artist:"秋元薫"' in calls[0]["q"]
    assert 'album:"Cologne"' in calls[0]["q"]
    assert calls[1]["q"] == 'track:"Dress Down" 秋元薫'
    assert "artist:" not in calls[1]["q"]


def test_second_query_stays_strict_when_first_search_has_candidates(monkeypatch):
    calls = []
    responses = [
        FakeResponse([candidate("wrong", "Inside Of Your Love", "Other Artist")]),
        FakeResponse([candidate("right", "Inside Of Your Love", "CINDY")]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)

    assert spotify.search_track("token", "Inside Of Your Love", ["CINDY"], "Album") == "right"
    assert len(calls) == 2
    assert 'artist:"CINDY"' in calls[1]["q"]
    assert calls[1]["q"] == 'track:"Inside Of Your Love" artist:"CINDY"'


def test_relaxed_second_query_does_not_accept_wrong_same_title_artist(monkeypatch):
    calls = []
    responses = [
        FakeResponse([]),
        FakeResponse([candidate("wrong", "RIDE ON TIME", "Black Box", isrc="GBCMX0509001")]),
    ]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
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

    assert spotify.search_track("token", "RIDE ON TIME", ["山下達郎"], "Ride On Time") is None
    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"RIDE ON TIME" 山下達郎'


def test_zero_candidate_retrieval_fallback_never_exceeds_two_searches(monkeypatch):
    calls = []

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return FakeResponse([])

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)

    assert spotify.search_track("token", "Unknown Song", ["未知艺人"], "Unknown Album") is None
    assert len(calls) == 2
