from src import identity_experiment as experiment


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_extract_spotify_isrc():
    assert experiment.extract_spotify_isrc({"external_ids": {"isrc": "US-TEST-1"}}) == "US-TEST-1"
    assert experiment.extract_spotify_isrc({}) is None


def test_identity_result():
    assert experiment.identity_result("EXACT", "STRONG", "MATCH", "DIFFERENT") == "SAME_RECORDING"
    assert experiment.identity_result("EXACT", "STRONG", "UNKNOWN", "DIFFERENT") == "LIKELY_SAME"
    assert experiment.identity_result("DIFFERENT", "STRONG", "UNKNOWN", "SAME") == "UNCERTAIN"


def test_musicbrainz_artist_recording_queries_are_mocked():
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append((url, params))
        if url.endswith("/artist"):
            return FakeResponse({"artists": [{"id": "artist-mbid", "name": "Faye Wong"}]})
        if url.endswith("/artist/artist-mbid"):
            return FakeResponse({"id": "artist-mbid", "name": "Faye Wong", "aliases": [{"name": "王菲", "locale": "zh"}]})
        if url.endswith("/recording"):
            return FakeResponse({"recordings": [{"id": "recording-mbid", "title": "Eyes On Me"}]})
        return FakeResponse({"id": "recording-mbid", "title": "Eyes On Me", "isrcs": ["US-TEST-1"]})

    result = experiment.analyze_case(
        experiment.CASES[0],
        {"name": "Eyes On Me", "artists": [{"name": "Faye Wong"}], "album": {"name": "Eyes On Me"}, "external_ids": {"isrc": "US-TEST-1"}},
        request_get=fake_get,
    )
    assert result["final_result"] == "SAME_RECORDING"
    assert result["musicbrainz_artist"]["aliases"][0]["name"] == "王菲"
    assert any("arid:artist-mbid" in params["query"] for url, params in calls if url.endswith("/recording"))
