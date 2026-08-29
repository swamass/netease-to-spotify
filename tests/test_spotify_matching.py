from src import spotify


class FakeResponse:
    def __init__(self, items):
        self.items = items

    def json(self):
        return {"tracks": {"items": self.items}}


def test_the_girl_is_mine_accepts_collaboration_title(monkeypatch):
    def fake_get(_url, _token, params):
        query = params["q"]
        if "Michael Jackson" in query or "Paul McCartney" in query:
            return FakeResponse([
                {
                    "id": "thriller-track",
                    "name": "The Girl Is Mine (with Paul McCartney)",
                    "artists": [
                        {"name": "Michael Jackson"},
                        {"name": "Paul McCartney"},
                    ],
                    "album": {"name": "Thriller"},
                },
                {
                    "id": "tribute-track",
                    "name": "The Girl Is Mine",
                    "artists": [{"name": "Michael Jackson Tribute"}],
                    "album": {"name": "I'll Be There - A Smash Hits Collection"},
                },
            ])
        return FakeResponse([])

    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    track_id = spotify.search_track(
        "test-token",
        "The Girl Is Mine",
        ["Paul McCartney", "Michael Jackson"],
        "Thriller",
    )

    assert track_id == "thriller-track"
