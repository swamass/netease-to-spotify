from src import auto_title_alias_spotcheck, retrieval_policy, spotify


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


def test_diagnostic_title_variant_keeps_original_artist_in_query_two(monkeypatch):
    calls = []
    responses = [FakeResponse([]), FakeResponse([])]
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda _url, _token, params: calls.append(params) or responses.pop(0),
    )
    monkeypatch.setattr(
        retrieval_policy,
        "_diagnostic_title_variant_hook",
        lambda title: "Kusuri o Takusan" if title == "Kusuri Wo Takusan" else None,
    )
    spotify.search_track("token", "Kusuri Wo Takusan", ["大貫妙子"], "Album")
    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"Kusuri o Takusan" artist:"大貫妙子"'


def test_diagnostic_title_variant_does_not_require_cjk_artist(monkeypatch):
    calls = []
    responses = [FakeResponse([]), FakeResponse([])]
    monkeypatch.setattr(
        retrieval_policy,
        "_diagnostic_title_variant_hook",
        lambda title: "Alternate Title" if title == "Original Title" else None,
    )
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda _url, _token, params: calls.append(params) or responses.pop(0),
    )

    spotify.search_track("token", "Original Title", ["English Artist"], "Album")

    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"Alternate Title" artist:"English Artist"'


def test_default_title_variant_hook_preserves_current_query(monkeypatch):
    calls = []
    monkeypatch.setattr(retrieval_policy, "_diagnostic_title_variant_hook", None)
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda _url, _token, params: calls.append(params) or FakeResponse([]),
    )
    spotify.search_track("token", "Kusuri Wo Takusan", ["大貫妙子"], "Album")
    assert calls[1]["q"] == 'track:"Kusuri Wo Takusan" 大貫妙子'
    assert len(calls) == 2


def test_diagnostic_title_variant_does_not_run_after_nonempty_first_search(monkeypatch):
    calls = []
    hook_calls = []
    monkeypatch.setattr(
        retrieval_policy,
        "_diagnostic_title_variant_hook",
        lambda title: hook_calls.append(title) or "Variant",
    )
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda _url, _token, params: calls.append(params) or FakeResponse([candidate("id", "Song", "Artist")]),
    )
    spotify.search_track("token", "Song", ["Artist"], "Album")
    assert hook_calls == []
    assert len(calls) == 1


def test_diagnostic_title_variant_does_not_run_after_first_search_failure(monkeypatch):
    calls = []
    hook_calls = []
    monkeypatch.setattr(
        retrieval_policy,
        "_diagnostic_title_variant_hook",
        lambda title: hook_calls.append(title) or "Variant",
    )
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda _url, _token, params: calls.append(params) or None,
    )
    spotify.search_track("token", "Song", ["Artist"], "Album")
    assert hook_calls == []
    assert len(calls) == 2


def test_second_query_diagnostic_returns_none_without_override(monkeypatch):
    sentinel = {"diagnostic": "report"}
    observed = []

    def fake_run_spotcheck(*args, **kwargs):
        observed.append(
            retrieval_policy._diagnostic_title_variant_hook("Title")
        )
        observed.append(
            retrieval_policy._diagnostic_title_variant_hook("Unknown Title")
        )
        return sentinel

    monkeypatch.setattr(auto_title_alias_spotcheck, "run_spotcheck", fake_run_spotcheck)
    assert auto_title_alias_spotcheck._run_second_query_diagnostic(
        "token",
        [{"title": "Unknown Title", "artist": "艺人"}],
        max_search_requests=2,
        delay_seconds=0,
        overrides={"title": "Variant"},
    ) is sentinel
    assert observed == ["Variant", None]
    assert retrieval_policy._diagnostic_title_variant_hook is None


def test_second_query_diagnostic_restores_hook_after_exception(monkeypatch):
    original_hook = lambda _title: "original"

    def fail_run_spotcheck(*args, **kwargs):
        raise RuntimeError("diagnostic failure")

    monkeypatch.setattr(
        retrieval_policy, "_diagnostic_title_variant_hook", original_hook
    )
    monkeypatch.setattr(auto_title_alias_spotcheck, "run_spotcheck", fail_run_spotcheck)

    try:
        auto_title_alias_spotcheck._run_second_query_diagnostic(
            "token",
            [{"title": "Title", "artist": "艺人"}],
            max_search_requests=2,
            delay_seconds=0,
            overrides={"title": "Variant"},
        )
    except RuntimeError as error:
        assert str(error) == "diagnostic failure"
    else:
        raise AssertionError("expected diagnostic failure")

    assert retrieval_policy._diagnostic_title_variant_hook is original_hook
