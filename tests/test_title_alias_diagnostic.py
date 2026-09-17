from src import title_alias_diagnostic


def test_discovers_unique_worldwide_digital_release_title(monkeypatch):
    def fake_mb(path, params):
        if path == "artist":
            return {
                "artists": [
                    {
                        "id": "takanaka",
                        "name": "高中正義",
                        "sort-name": "Takanaka, Masayoshi",
                        "aliases": [{"name": "Masayoshi Takanaka"}],
                    }
                ]
            }
        if path == "recording":
            return {
                "recordings": [
                    {
                        "id": "sad-space-alien",
                        "title": "哀愁の宇宙人",
                        "score": "100",
                        "artist-credit": [
                            {"artist": {"id": "takanaka", "name": "高中正義"}}
                        ],
                    }
                ]
            }
        if path == "release":
            return {
                "releases": [
                    {
                        "country": "JP",
                        "status": "Official",
                        "media": [
                            {
                                "format": "CD",
                                "tracks": [
                                    {
                                        "title": "哀愁の宇宙人",
                                        "recording": {"id": "sad-space-alien"},
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "country": "XW",
                        "status": "Official",
                        "media": [
                            {
                                "format": "Digital Media",
                                "tracks": [
                                    {
                                        "title": "Sad Space Alien",
                                        "recording": {"id": "sad-space-alien"},
                                    }
                                ],
                            }
                        ],
                    },
                ]
            }
        raise AssertionError((path, params))

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias(
        "哀愁の宇宙人", "高中正義"
    )

    assert alias == "Sad Space Alien"
    assert trace["artist_mbid"] == "takanaka"
    assert trace["recording_ids"] == ["sad-space-alien"]
    assert trace["reason"] == "UNIQUE_RELEASE_TITLE"


def test_rejects_ambiguous_equal_strength_release_titles(monkeypatch):
    def fake_mb(path, params):
        if path == "artist":
            return {
                "artists": [
                    {"id": "artist-1", "name": "山根麻以", "aliases": []}
                ]
            }
        if path == "recording":
            return {
                "recordings": [
                    {
                        "id": "recording-1",
                        "title": "たそがれ",
                        "score": "100",
                        "artist-credit": [{"artist": {"id": "artist-1"}}],
                    }
                ]
            }
        if path == "release":
            return {
                "releases": [
                    {
                        "country": "XW",
                        "status": "Official",
                        "media": [
                            {
                                "format": "Digital Media",
                                "tracks": [
                                    {
                                        "title": "Tasogare",
                                        "recording": {"id": "recording-1"},
                                    },
                                    {
                                        "title": "Twilight",
                                        "recording": {"id": "recording-1"},
                                    },
                                ],
                            }
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias(
        "たそがれ", "山根麻以"
    )

    assert alias is None
    assert trace["reason"] == "ALTERNATE_TITLE_AMBIGUOUS"


def test_rejects_non_unique_artist_identity(monkeypatch):
    monkeypatch.setattr(
        title_alias_diagnostic.spotify,
        "_musicbrainz_get",
        lambda path, params: {
            "artists": [
                {"id": "a", "name": "Same Artist", "aliases": []},
                {"id": "b", "name": "Same Artist", "aliases": []},
            ]
        },
    )

    alias, trace = title_alias_diagnostic.discover_title_alias(
        "Song", "Same Artist"
    )

    assert alias is None
    assert trace["reason"] == "ARTIST_IDENTITY_NOT_UNIQUE"


def test_rejects_version_conflicting_alternate_title(monkeypatch):
    def fake_mb(path, params):
        if path == "artist":
            return {"artists": [{"id": "a", "name": "Artist", "aliases": []}]}
        if path == "recording":
            return {
                "recordings": [
                    {
                        "id": "r",
                        "title": "Song",
                        "score": "100",
                        "artist-credit": [{"artist": {"id": "a"}}],
                    }
                ]
            }
        if path == "release":
            return {
                "releases": [
                    {
                        "country": "XW",
                        "status": "Official",
                        "media": [
                            {
                                "format": "Digital Media",
                                "tracks": [
                                    {
                                        "title": "Song - Live",
                                        "recording": {"id": "r"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias("Song", "Artist")

    assert alias is None
    assert trace["reason"] == "NO_ALTERNATE_RELEASE_TITLE"
