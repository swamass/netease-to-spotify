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
    assert trace["artist_mbids"] == ["takanaka"]
    assert trace["recording_ids"] == ["sad-space-alien"]
    assert trace["reason"] == "UNIQUE_RELEASE_TITLE"


def test_prefers_romanized_title_over_parenthetical_translation(monkeypatch):
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
        "たそがれ (Twilight)", "山根麻以"
    )

    assert alias == "Tasogare"
    assert trace["reason"] == "UNIQUE_RELEASE_TITLE"
    assert trace["parenthetical_translation"] is False



def test_uses_particle_o_as_recording_query_variant(monkeypatch):
    seen_queries = []

    def fake_mb(path, params):
        if path == "artist":
            return {"artists": [{"id": "onuki", "name": "大貫妙子", "aliases": []}]}
        if path == "recording":
            seen_queries.append(params["query"])
            if 'recording:"Kusuri o Takusan"' in params["query"]:
                return {
                    "recordings": [
                        {
                            "id": "kusuri",
                            "score": "100",
                            "artist-credit": [{"artist": {"id": "onuki"}}],
                        }
                    ]
                }
            return {"recordings": []}
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
                                        "title": "Kusuri o Takusan",
                                        "recording": {"id": "kusuri"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias(
        "Kusuri Wo Takusan", "大貫妙子"
    )

    assert alias == "Kusuri o Takusan"
    assert any('recording:"Kusuri o Takusan"' in query for query in seen_queries)
    assert trace["recording_ids"] == ["kusuri"]


def test_uses_botchi_spelling_as_recording_query_variant(monkeypatch):
    seen_queries = []

    def fake_mb(path, params):
        if path == "artist":
            return {"artists": [{"id": "sato", "name": "佐藤奈々子", "aliases": []}]}
        if path == "recording":
            seen_queries.append(params["query"])
            if 'recording:"Subterranean Futari Botchi"' in params["query"]:
                return {
                    "recordings": [
                        {
                            "id": "botchi",
                            "score": "100",
                            "artist-credit": [{"artist": {"id": "sato"}}],
                        }
                    ]
                }
            return {"recordings": []}
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
                                        "title": "Subterranean Futari Botchi",
                                        "recording": {"id": "botchi"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias(
        "Subterranean Futari Bocci", "佐藤奈々子"
    )

    assert alias == "Subterranean Futari Botchi"
    assert any(
        'recording:"Subterranean Futari Botchi"' in query for query in seen_queries
    )
    assert trace["recording_ids"] == ["botchi"]


def test_multiple_exact_artist_ids_can_resolve_to_one_recording(monkeypatch):
    def fake_mb(path, params):
        if path == "artist":
            return {
                "artists": [
                    {"id": "a", "name": "林哲司", "aliases": []},
                    {"id": "b", "name": "林哲司", "aliases": []},
                ]
            }
        if path == "recording":
            if "arid:a" in params["query"]:
                return {"recordings": []}
            return {
                "recordings": [
                    {
                        "id": "hidari",
                        "score": "100",
                        "artist-credit": [{"artist": {"id": "b"}}],
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
                                        "title": "HIDARIMUNE NO SEIZA",
                                        "recording": {"id": "hidari"},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(title_alias_diagnostic.spotify, "_musicbrainz_get", fake_mb)
    alias, trace = title_alias_diagnostic.discover_title_alias(
        "Hidari Mune No Seiza", "林哲司"
    )

    assert alias == "HIDARIMUNE NO SEIZA"
    assert trace["artist_mbids"] == ["a", "b"]
    assert trace["recording_ids"] == ["hidari"]


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
    assert trace["reason"] == "RECORDING_NOT_FOUND"


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
