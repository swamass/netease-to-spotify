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
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: {"same-artist-mbid"})
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [])
    assert spotify._musicbrainz_recording_identity_accepts("余韻", ["来生たかお"], "", item) is True


def test_cross_script_title_still_requires_recording_evidence(monkeypatch):
    item = candidate("tokai", "Tokai", "Taeko Onuki", isrc="TESTTOKAI")
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: {"same-artist-mbid"})
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [])
    assert spotify._musicbrainz_recording_identity_accepts(
        "都会", ["大貫妙子"], "", item, allow_cross_script_title=True
    ) is False


def test_recording_verification_diagnostics_preserve_result(monkeypatch):
    item = candidate("diag", "Song", "Artist", isrc="TESTDIAG")
    recording = {
        "id": "recording-mbid",
        "title": "Song",
        "length": 180000,
        "artist-credit": [
            {"name": "Artist", "artist": {"id": "artist-mbid", "name": "Artist"}}
        ],
        "disambiguation": "",
        "releases": [{"title": "Album", "release-group": {"title": "Album"}}],
    }
    item["duration_ms"] = 180000
    monkeypatch.setattr(
        spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: {"artist-mbid"}
    )
    monkeypatch.setattr(
        spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [recording]
    )
    diagnostics = {}

    assert spotify._musicbrainz_recording_identity_accepts(
        "Song", ["Artist"], "Album", item, diagnostics=diagnostics
    ) is True

    verification = diagnostics["musicbrainz_verifications"][0]
    assert verification["recording_count"] == 1
    assert verification["recordings"][0]["mbid"] == "recording-mbid"
    assert verification["predicates"]["title_identity"] == "PASS"
    assert verification["predicates"]["artist_identity"] == "PASS"
    assert verification["predicates"]["duration"] == "PASS"
    assert verification["result"] == "CONFIRMED"


def test_version_conflict_remains_hard_reject(monkeypatch):
    item = candidate("remix", "余韻 - Remix", "Takao Kisugi", isrc="TESTREMIX")
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: {"same-artist-mbid"})
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [])
    assert spotify._musicbrainz_recording_identity_accepts("余韻", ["来生たかお"], "", item) is False


def test_wrong_artist_remains_hard_reject(monkeypatch):
    item = candidate("wrong", "RIDE ON TIME", "Black Box", isrc="TESTWRONG")
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: set())
    assert spotify._musicbrainz_recording_identity_accepts("RIDE ON TIME", ["山下達郎"], "", item) is False


def test_search_track_accepts_confirmed_cross_language_artist_without_mb_recording(monkeypatch):
    item = candidate("yo-in", "余韻", "Takao Kisugi", isrc="JPKT08900101")
    monkeypatch.setattr(spotify, "_spotify_get", lambda *_args, **_kwargs: FakeResponse([item]))
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity_supported", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args, **_kwargs: {"same-artist-mbid"})
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [])
    assert spotify.search_track("test-token", "余韻", ["来生たかお"], "") == "yo-in"


def test_artist_id_resolver_ignores_fuzzy_field_hit_and_uses_exact_fallback_alias(monkeypatch):
    responses = [
        {"artists": [{"id": "wrong", "name": "Kaoru", "aliases": []}]},
        {"artists": [{"id": "akimoto-mbid", "name": "秋元薫", "sort-name": "Akimoto, Kaoru", "aliases": [{"name": "Kaoru Akimoto"}]}]},
    ]
    queries = []
    monkeypatch.setattr(spotify, "_musicbrainz_get", lambda _path, params: queries.append(params["query"]) or responses.pop(0))
    assert spotify._musicbrainz_artist_ids("Kaoru Akimoto") == {"akimoto-mbid"}
    assert queries == ['artist:"Kaoru Akimoto"', "Kaoru Akimoto"]


def test_artist_id_resolver_accepts_exact_alias_from_field_search(monkeypatch):
    calls = []
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_get",
        lambda _path, params: calls.append(params["query"]) or {
            "artists": [{"id": "yuko-mbid", "name": "今井優子", "aliases": [{"name": "Yuko Imai"}]}]
        },
    )
    assert spotify._musicbrainz_artist_ids("Yuko Imai") == {"yuko-mbid"}
    assert calls == ['artist:"Yuko Imai"']


def test_artist_id_resolver_rejects_unrelated_fuzzy_results(monkeypatch):
    responses = [
        {"artists": [{"id": "one", "name": "Omega Tribe Tribute", "aliases": []}]},
        {"artists": [{"id": "two", "name": "Omega", "aliases": [{"name": "Other Band"}]}]},
    ]
    monkeypatch.setattr(spotify, "_musicbrainz_get", lambda _path, _params: responses.pop(0))
    assert spotify._musicbrainz_artist_ids("1986 OMEGA TRIBE") == set()


def test_artist_identity_can_intersect_japanese_and_romanized_alias_results(monkeypatch):
    payloads = {
        'artist:"秋元薫"': {"artists": [{"id": "akimoto-mbid", "name": "秋元薫", "aliases": []}]},
        'artist:"Kaoru Akimoto"': {"artists": [{"id": "akimoto-mbid", "name": "秋元薫", "aliases": [{"name": "Kaoru Akimoto"}]}]},
    }
    monkeypatch.setattr(spotify, "_musicbrainz_get", lambda _path, params: payloads[params["query"]])
    assert spotify._musicbrainz_artist_identity(["秋元薫"], [{"name": "Kaoru Akimoto"}]) == {"akimoto-mbid"}


def test_artist_credit_identity_confirms_same_entity_with_different_display_credit(monkeypatch):
    item = candidate("older-girl", "Older Girl", "1986 OMEGA TRIBE", isrc="JPVP08601107")
    recording = {
        "id": "older-girl-recording", "title": "Older Girl",
        "artist-credit": [{"name": "1986 OMEGA TRIBE", "artist": {"id": "omega-mbid", "name": "オメガトライブ"}}],
        "disambiguation": "",
    }
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args: set())
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [recording])
    def fake_mb_get(path, params):
        query = params.get("query", "")
        if path == "artist" and "1986オメガトライブ" in query:
            return {"artists": []}
        if path == "recording" and query == 'creditname:"1986オメガトライブ"':
            return {"recordings": [{"artist-credit": [{"name": "1986オメガトライブ", "artist": {"id": "omega-mbid", "name": "オメガトライブ"}}]}]}
        return {"artists": []}
    monkeypatch.setattr(spotify, "_musicbrainz_get", fake_mb_get)
    assert spotify._musicbrainz_artist_identity_supported(["1986オメガトライブ"], item) is True
    assert spotify._musicbrainz_recording_identity_accepts("Older Girl", ["1986オメガトライブ"], "", item) is True


def test_artist_credit_identity_rejects_different_entity_even_when_title_matches(monkeypatch):
    item = candidate("wrong", "RIDE ON TIME", "Black Box", isrc="TESTWRONG")
    recording = {
        "id": "wrong-recording", "title": "RIDE ON TIME",
        "artist-credit": [{"name": "Black Box", "artist": {"id": "black-box-mbid", "name": "Black Box"}}],
        "disambiguation": "",
    }
    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity", lambda *_args: set())
    monkeypatch.setattr(spotify, "_musicbrainz_recordings_for_isrc", lambda _isrc: [recording])
    def fake_mb_get(path, params):
        query = params.get("query", "")
        if path == "artist" and "山下達郎" in query:
            return {"artists": [{"id": "yamashita-mbid", "name": "山下達郎"}]}
        if path == "recording" and query == 'creditname:"山下達郎"':
            return {"recordings": [{"artist-credit": [{"name": "山下達郎", "artist": {"id": "yamashita-mbid", "name": "山下達郎"}}]}]}
        return {"artists": []}
    monkeypatch.setattr(spotify, "_musicbrainz_get", fake_mb_get)
    assert spotify._musicbrainz_artist_identity_supported(["山下達郎"], item) is False
    assert spotify._musicbrainz_recording_identity_accepts("RIDE ON TIME", ["山下達郎"], "", item) is False


def _rank_fallback_setup(monkeypatch, first_items, second_items, mb_isrc_available=True):
    responses = [FakeResponse(first_items), FakeResponse(second_items)]
    monkeypatch.setattr(spotify, "_spotify_get", lambda *_args, **_kwargs: responses.pop(0))

    def fake_mb_get(path, _params):
        if mb_isrc_available and path.startswith("isrc/"):
            return {"recordings": [{"id": "recording"}]}
        return None

    monkeypatch.setattr(spotify, "_musicbrainz_get", fake_mb_get)

    def unsupported(source_artists, item):
        isrc = (item.get("external_ids") or {}).get("isrc")
        if isrc:
            spotify._musicbrainz_get(f"isrc/{isrc}", {"fmt": "json"})
        return False

    monkeypatch.setattr(spotify, "_musicbrainz_artist_identity_supported", unsupported)


def test_rank_consensus_accepts_exact_cross_script_artist_with_mb_isrc(monkeypatch):
    item = candidate("dress-down", "Dress Down", "Kaoru Akimoto", album="Cologne", isrc="JPVI08613060")
    _rank_fallback_setup(monkeypatch, [item], [item])
    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "") == "dress-down"


def test_rank_consensus_rejects_when_mb_isrc_is_unavailable(monkeypatch):
    item = candidate("dress-down", "Dress Down", "Kaoru Akimoto", isrc="JPVI08613060")
    _rank_fallback_setup(monkeypatch, [item], [item], mb_isrc_available=False)
    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "") is None


def test_rank_consensus_rejects_disagreeing_top_isrcs(monkeypatch):
    first = candidate("a", "Dress Down", "Kaoru Akimoto", isrc="JPVI08613060")
    second = candidate("b", "Dress Down", "Other Artist", isrc="OTHER")
    _rank_fallback_setup(monkeypatch, [first], [second])
    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "") is None


def test_rank_consensus_rejects_hard_artist_conflict(monkeypatch):
    item = candidate("wrong", "RIDE ON TIME", "Black Box", isrc="GBCMX0509001")
    _rank_fallback_setup(monkeypatch, [item], [item])
    monkeypatch.setattr(spotify, "_artist_match_score", lambda *_args: (0.0, 0, False))
    assert spotify.search_track("token", "RIDE ON TIME", ["山下達郎"], "") is None


def test_rank_consensus_rejects_version_conflict(monkeypatch):
    item = candidate("remix", "Dress Down - Remix", "Kaoru Akimoto", isrc="REMIXISRC")
    _rank_fallback_setup(monkeypatch, [item], [item])
    assert spotify.search_track("token", "Dress Down", ["秋元薫"], "") is None
