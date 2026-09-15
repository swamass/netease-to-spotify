from src import spotify


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def json(self):
        return {"tracks": {"items": self._items}}


def test_retrieval_artist_alias_is_cached_per_source(monkeypatch):
    spotify._retrieval_artist_alias_cache.clear()
    calls = []

    def fake_mb_get(path, params):
        calls.append((path, dict(params)))
        return {
            "artists": [
                {
                    "id": "kadomatsu-mbid",
                    "name": "角松敏生",
                    "sort-name": "Kadomatsu, Toshiki",
                    "aliases": [],
                }
            ]
        }

    monkeypatch.setattr(spotify, "_musicbrainz_get", fake_mb_get)

    assert spotify._retrieval_artist_alias("角松敏生") == "Toshiki Kadomatsu"
    assert spotify._retrieval_artist_alias("角松敏生") == "Toshiki Kadomatsu"
    assert len(calls) == 1


def test_failed_first_search_never_relaxes_second_query(monkeypatch):
    spotify._retrieval_artist_alias_cache.clear()
    calls = []
    responses = [None, FakeResponse([])]

    def fake_get(_url, _token, params):
        calls.append(dict(params))
        return responses.pop(0)

    alias_calls = []
    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    monkeypatch.setattr(
        spotify,
        "_retrieval_artist_alias",
        lambda _source: alias_calls.append(True) or "Tatsuro Yamashita",
    )

    assert spotify.search_track(
        "token", "MUSIC BOOK", ["山下達郎"], "MOONGLOW"
    ) is None

    assert len(calls) == 2
    assert calls[1]["q"] == 'track:"MUSIC BOOK" artist:"山下達郎"'
    assert alias_calls == []
