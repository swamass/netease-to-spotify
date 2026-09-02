from src import spotify


class FakeResponse:
    def __init__(self, items):
        self.items = items

    def json(self):
        return {"tracks": {"items": self.items}}


def run_search(monkeypatch, source_title, source_artists, source_album, items):
    monkeypatch.setattr(
        spotify,
        "_spotify_get",
        lambda *_args, **_kwargs: FakeResponse(items),
    )
    return spotify.search_track(
        "test-token",
        source_title,
        source_artists,
        source_album,
    )


def track(track_id, name, artists, album):
    return {
        "id": track_id,
        "name": name,
        "artists": [{"name": artist} for artist in artists],
        "album": {"name": album},
    }


def test_the_girl_is_mine_accepts_collaboration_title_and_thriller(monkeypatch):
    result = run_search(
        monkeypatch,
        "The Girl Is Mine",
        ["Paul McCartney", "Michael Jackson"],
        "Thriller",
        [
            track(
                "thriller-track",
                "The Girl Is Mine (with Paul McCartney)",
                ["Michael Jackson", "Paul McCartney"],
                "Thriller",
            ),
            track(
                "tribute-track",
                "The Girl Is Mine - Michael Jackson Tribute",
                ["Michael Jackson Tribute"],
                "Tribute Collection",
            ),
        ],
    )
    assert result == "thriller-track"


def test_album_release_difference_is_allowed(monkeypatch):
    result = run_search(
        monkeypatch,
        "Chiquitita",
        ["ABBA"],
        "ABBA Gold: Greatest Hits (40th Anniversary Edition)",
        [track("abba", "Chiquitita", ["ABBA"], "ABBA Gold")],
    )
    assert result == "abba"


def test_different_compilation_album_is_allowed(monkeypatch):
    result = run_search(
        monkeypatch,
        "Everybody Plays The Fool",
        ["Aaron Neville"],
        "Warm Your Heart",
        [track("aaron", "Everybody Plays The Fool", ["Aaron Neville"], "Greatest Hits")],
    )
    assert result == "aaron"


def test_cross_language_artist_aliases(monkeypatch):
    cases = [
        ("Casket Girl", ["藤井風"], "Fujii Kaze"),
        ("Tornado", ["吉田美奈子"], "Minako Yoshida"),
        ("クルージング・オン", ["ブレッド&バター"], "Bread And Butter"),
    ]
    for title, source_artists, spotify_artist in cases:
        assert run_search(
            monkeypatch,
            title,
            source_artists,
            "",
            [track(title, title, [spotify_artist], "Album")],
        ) is not None


def test_fool_accepts_correct_artist_from_other_album(monkeypatch):
    result = run_search(
        monkeypatch,
        "Fool (If You Think It's Over)",
        ["Chris Rea"],
        "Whatever",
        [track("fool", "Fool (If You Think It's Over)", ["Chris Rea"], "Compilation")],
    )
    assert result == "fool"


def test_rejects_invalid_and_conflicting_versions(monkeypatch):
    cases = [
        ("Tribute", "Live"),
        ("Cover", "Live"),
        ("Karaoke", "Live"),
        ("Live", ""),
        ("Remix", ""),
        ("Acoustic", ""),
        ("Instrumental", ""),
    ]
    for source_version, candidate_version in cases:
        source_title = f"Song ({source_version})" if source_version else "Song"
        candidate_title = f"Song ({candidate_version})" if candidate_version else "Song"
        result = run_search(
            monkeypatch,
            source_title,
            ["Artist"],
            "Album",
            [track("candidate", candidate_title, ["Artist"], "Album")],
        )
        if source_version in {"Tribute", "Cover", "Karaoke"}:
            assert result is None
        else:
            assert result is None if source_version else result == "candidate"


def test_title_core_accepts_safe_metadata_variants():
    assert spotify._title_match(
        "FREE WAY 5 TO SOUTH",
        "FREE WAY 5 TO SOUTH - 2022 Remaster",
    )
    assert spotify._title_match(
        "As You Walked Away From Me",
        "As You Walked Away Frome Me (You Are Free)",
    )
    assert spotify._title_match(
        "Amaze Amaze Amaze (Life on Erid)",
        'Amaze Amaze Amaze (Life on Erid) - from "Project Hail Mary"',
    )
    assert not spotify._title_match(
        "Romeo And Juliet",
        "Romeo And Juliet - Live Version",
    )


def test_additional_safe_metadata_and_artist_aliases(monkeypatch):
    cases = [
        ("FREE WAY 5 TO SOUTH", ["芳野藤丸"], "FREE WAY 5 TO SOUTH - 2022 Remaster", "Album", "芳野藤丸"),
        ("Amaze Amaze Amaze (Life on Erid)", ["Daniel Pemberton"], 'Amaze Amaze Amaze (Life on Erid) - from "Project Hail Mary"', "Project Hail Mary", "Daniel Pemberton"),
        ("From Me", ["Artist"], "Frome Me", "Album", "Artist"),
        ("Theme", ["林ゆうき"], "Theme", "Album", "Yuki Hayashi"),
        ("Theme", ["宇多田ヒカル"], "Theme", "Album", "Hikaru Utada"),
        ("Theme", ["ラ・ムー"], "Theme", "Album", "RA MU"),
    ]
    for source_title, artists, candidate_title, album, spotify_artist in cases:
        assert run_search(monkeypatch, source_title, artists, album, [track("candidate", candidate_title, [spotify_artist], album)]) == "candidate"


def test_all_explicit_recording_conflicts_are_rejected(monkeypatch):
    for marker in ["Live Version", "Remix", "Acoustic", "Instrumental", "Demo", "Radio Edit", "Extended Mix", "DJ Version", "Tribute", "Cover", "Karaoke"]:
        result = run_search(monkeypatch, "Romeo And Juliet", ["Dire Straits"], "Brothers in Arms", [track("wrong", f"Romeo And Juliet - {marker}", ["Dire Straits"], "Brothers in Arms")])
        assert result is None


def test_murata_song_accepts_remaster_from_different_album(monkeypatch):
    result = run_search(
        monkeypatch,
        "電話しても",
        ["村田和人"],
        "Real Collection 1982-1984",
        [
            track(
                "murata-2002-remaster",
                "電話しても - 2002 Remaster",
                ["Kazuhito Murata"],
                "Treasures in the Box - 1982-1984",
            )
        ],
    )
    assert result == "murata-2002-remaster"


def test_multilingual_artist_mismatch_can_use_title_and_album(monkeypatch):
    cases = [
        ("夜に駆ける", ["YOASOBI中文名"], "ヨアソビ"),
        ("Theme", ["中文艺人名"], "Romanized Artist"),
        ("タイトル", ["日本語名"], "Romanized Artist"),
    ]
    for title, source_artists, spotify_artist in cases:
        assert run_search(
            monkeypatch,
            title,
            source_artists,
            "Exact Album",
            [track("multilingual", title, [spotify_artist], "Exact Album")],
        ) == "multilingual"


def test_same_title_with_clearly_different_artist_is_rejected(monkeypatch):
    result = run_search(
        monkeypatch,
        "晴天",
        ["周杰伦"],
        "叶惠美",
        [track("wrong", "晴天", ["Other Artist"], "Other Album")],
    )
    assert result is None


def test_candidate_scoring_prefers_exact_artist_and_album(monkeypatch):
    candidates = [
        track("wrong-artist", "Home", ["Artist B"], "Album"),
        track("right", "Home", ["Artist A"], "Album"),
        track("right-other-album", "Home", ["Artist A"], "Compilation"),
    ]
    assert run_search(monkeypatch, "Home", ["Artist A"], "Album", candidates) == "right"


def test_duration_is_supporting_evidence_not_a_hard_reject(monkeypatch):
    candidate = track("duration", "Song", ["Artist"], "Album")
    candidate["duration_ms"] = 223000
    monkeypatch.setattr(spotify, "_spotify_get", lambda *_args, **_kwargs: FakeResponse([candidate]))
    assert spotify.search_track("test-token", "Song", ["Artist"], "Album", duration_ms=220000) == "duration"


def test_search_stays_bounded_at_two_queries(monkeypatch):
    calls = []
    def fake_get(*_args, **kwargs):
        calls.append(kwargs.get("params", {}).get("q"))
        return FakeResponse([])
    monkeypatch.setattr(spotify, "_spotify_get", fake_get)
    assert spotify.search_track("test-token", "Missing", ["Artist"], "Album") is None
    assert len(calls) <= 2


def test_real_dry_run_artist_and_ost_variants(monkeypatch):
    cases = [
        ("中原めいこ", "Meiko Nakahara", "Track", "Album"),
        ("松下誠", "Makoto Matsushita", "September Rain", "Album"),
        ("Belle & Sebastian", "Belle and Sebastian", "Track", "Album"),
    ]
    for source_artist, spotify_artist, title, album in cases:
        assert run_search(
            monkeypatch,
            title,
            [source_artist],
            album,
            [track("match", title, [spotify_artist], album)],
        ) == "match"


def test_ost_bracket_attribution_is_ignored():
    assert spotify._title_match(
        "First Youth/Love Theme for Nata [From Cinema Paradiso]",
        "First Youth/Love Theme For Nata",
    )


def test_english_and_japanese_versions_do_not_cross_match(monkeypatch):
    result = run_search(
        monkeypatch,
        "September Rain (English Version)",
        ["松下誠"],
        "Album",
        [track(
            "japanese",
            "September Rain - Japanese Version",
            ["Makoto Matsushita"],
            "Album",
        )],
    )
    assert result is None


def test_safe_unicode_variant_matches_without_romanization():
    assert spotify._title_match("絶え间なく", "絶え間なく")


def test_romanized_cjk_title_remains_unmatched():
    assert not spotify._title_match("皆既月食", "Kaiki Gesshoku")


def test_live_in_album_proves_candidate_live_version(monkeypatch):
    result = run_search(
        monkeypatch,
        "One Day",
        ["OMA", "Shing02"],
        "Luv(Sic) Hexalogy (OMA and Shing02 Live at Liquidroom)",
        [track(
            "one-day-live",
            "One Day - Live",
            ["OMA", "Shing02"],
            "Luv(Sic) Hexalogy [OMA and Shing02 Live at Liquidroom]",
        )],
    )
    assert result == "one-day-live"


def test_duration_is_passed_through_recommendation_shape():
    recommendation = {"name": "Song", "artists": ["Artist"], "album": "Album", "duration_ms": 210000}
    assert recommendation["duration_ms"] == 210000


def test_duration_score_is_positive_for_close_millisecond_values():
    assert spotify._duration_score(240000, 241500) > 0


def test_search_scoring_uses_duration_to_prefer_closer_candidate(monkeypatch):
    close = track("close", "Song", ["Artist"], "Album")
    close["duration_ms"] = 241500
    far = track("far", "Song", ["Artist"], "Compilation")
    far["duration_ms"] = 280000
    assert run_search(
        monkeypatch,
        "Song",
        ["Artist"],
        "Album",
        [far, close],
    ) == "close"


def test_fukuhara_artist_alias_matches():
    score, count, reliable = spotify._artist_match_score(
        ["福原美穂"],
        [{"name": "Miho Fukuhara"}],
    )
    assert score == 1.0
    assert reliable


def test_fukuhara_song_matches_with_romanized_artist(monkeypatch):
    result = run_search(
        monkeypatch,
        "絶え间なく",
        ["福原美穂"],
        "Album",
        [track("fukuhara", "絶え間なく", ["Miho Fukuhara"], "Album")],
    )
    assert result == "fukuhara"


def test_additional_artists_are_penalized_only_with_weak_album(monkeypatch):
    candidates = [
        track(
            "solo",
            "Deborah's Theme",
            ["Ennio Morricone"],
            "Once Upon a Time In America",
        ),
        track(
            "ensemble",
            "Deborah's Theme",
            ["Ennio Morricone", "Jeroen van Veen", "Joachim Eijlander"],
            "Film Music Volume 1",
        ),
    ]
    result = run_search(
        monkeypatch,
        "Deborah's Theme",
        ["Ennio Morricone"],
        "Once Upon a Time In America",
        candidates,
    )
    assert result == "solo"


def test_additional_artists_remain_allowed_with_exact_album(monkeypatch):
    for candidate_artists in [
        ["KAROL G", "Bruno Mars"],
        ["Revo Marty", "Alya Zurayya"],
    ]:
        result = run_search(
            monkeypatch,
            "Still",
            [candidate_artists[0]],
            "Exact Album",
            [track("collab", "Still", candidate_artists, "Exact Album")],
        )
        assert result == "collab"


def test_weak_artist_case_is_not_made_more_permissive():
    score, _, reliable = spotify._artist_match_score(
        ["麗美"],
        [{"name": "REMEDIOS"}],
    )
    assert score == 0.35
    assert not reliable


def test_musicbrainz_fallback_confirms_cross_language_artist_and_isrc(monkeypatch):
    candidate = track("faye", "Eyes On Me", ["Faye Wong"], "Eyes On Me")
    candidate.update({"external_ids": {"isrc": "US-TEST"}, "duration_ms": 240000})

    def fake_get(url, params, **_kwargs):
        query = params.get("query", "")
        if url.endswith("/artist"):
            if "王菲" in query:
                return FakeMBResponse({"artists": [{"id": "faye-mbid"}]})
            return FakeMBResponse({"artists": [{"id": "faye-mbid"}]})
        if "/isrc/US-TEST" in url:
            return FakeMBResponse({"recordings": [{"id": "recording-mbid"}]})
        return FakeMBResponse({
            "id": "recording-mbid",
            "title": "Eyes On Me",
            "length": 240500,
            "artist-credit": [{"artist": {"id": "faye-mbid"}}],
            "disambiguation": "",
        })

    monkeypatch.setattr(spotify.requests, "get", fake_get)
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(spotify.time, "monotonic", lambda: 100.0)
    assert run_search(monkeypatch, "Eyes On Me", ["王菲"], "Eyes On Me", [candidate]) == "faye"


class FakeMBResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise spotify.requests.HTTPError()


def test_musicbrainz_artist_fallback_runs_without_isrc_and_skips_recording_lookup(monkeypatch):
    candidate = track("faye-no-isrc", "Eyes On Me", ["Faye Wong"], "Eyes On Me")
    calls = []

    def fake_get(url, params, **_kwargs):
        calls.append(url)
        return FakeMBResponse({"artists": [{"id": "faye-mbid"}]})

    monkeypatch.setattr(spotify.requests, "get", fake_get)
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    assert run_search(
        monkeypatch, "Eyes On Me", ["王菲"], "Eyes On Me", [candidate]
    ) == "faye-no-isrc"
    assert not any("/isrc/" in url for url in calls)


def test_musicbrainz_isrc_chooses_close_recording_over_dj_mix(monkeypatch):
    candidate = track("hiroko", "あなたを・もっと・知りたくて", ["Hiroko Yakushimaru"], "Best")
    candidate.update({"external_ids": {"isrc": "JPTO08517910"}, "duration_ms": 233040})
    calls = []

    def fake_get(url, params, **_kwargs):
        calls.append(url)
        if url.endswith("/artist"):
            return FakeMBResponse({"artists": [{"id": "hiroko-mbid"}]})
        if url.endswith("/isrc/JPTO08517910"):
            return FakeMBResponse({"recordings": [{"id": "dj"}, {"id": "normal"}]})
        if url.endswith("/recording/dj"):
            return FakeMBResponse({"id": "dj", "title": "あなたを・もっと・知りたくて", "length": 109000,
                                    "artist-credit": [{"artist": {"id": "hiroko-mbid"}}],
                                    "disambiguation": "DJ-mixed"})
        return FakeMBResponse({"id": "normal", "title": "あなたを・もっと・知りたくて", "length": 232293,
                                "artist-credit": [{"artist": {"id": "hiroko-mbid"}}],
                                "disambiguation": ""})

    monkeypatch.setattr(spotify.requests, "get", fake_get)
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    assert run_search(monkeypatch, "あなたを・もっと・知りたくて", ["薬師丸ひろ子"], "", [candidate]) == "hiroko"
    assert calls.count("https://musicbrainz.org/ws/2/recording/dj") == 1


def test_musicbrainz_not_found_preserves_baseline_accept(monkeypatch):
    candidate = track("on-my-own", "On My Own", ["Taisei Iwasaki"], "Album")
    candidate.update({"external_ids": {"isrc": "US5941406269"}})

    def fake_get(url, params, **_kwargs):
        if url.endswith("/artist"):
            return FakeMBResponse({"artists": [{"id": "artist-mbid"}]})
        return FakeMBResponse({}, status_code=404)

    monkeypatch.setattr(spotify.requests, "get", fake_get)
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    assert run_search(monkeypatch, "On My Own", ["岩崎太整"], "Album", [candidate]) == "on-my-own"


def test_musicbrainz_503_preserves_baseline_accept(monkeypatch):
    candidate = track("candidate", "Song", ["Romanized Artist"], "Album")
    candidate["external_ids"] = {"isrc": "US-503"}

    def fake_get(*_args, **_kwargs):
        return FakeMBResponse({}, status_code=503)

    monkeypatch.setattr(spotify.requests, "get", fake_get)
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    assert run_search(monkeypatch, "Song", ["中文艺人"], "Album", [candidate]) == "candidate"


def test_musicbrainz_failure_preserves_baseline_reject(monkeypatch):
    candidate = track("uncertain", "Song", ["Romanized Artist"], "Other Collection")
    candidate["external_ids"] = {"isrc": "US-UNCERTAIN"}

    monkeypatch.setattr(
        spotify.requests,
        "get",
        lambda *_args, **_kwargs: FakeMBResponse({}, status_code=503),
    )
    monkeypatch.setattr(spotify.time, "sleep", lambda *_args: None)
    assert run_search(monkeypatch, "Song", ["中文艺人"], "Album", [candidate]) is None


def test_musicbrainz_cannot_override_title_or_version_conflict(monkeypatch):
    candidate = track("wrong", "Other Song - Live", ["Romanized Artist"], "Album")
    candidate["external_ids"] = {"isrc": "US-TEST"}
    called = []
    monkeypatch.setattr(spotify.requests, "get", lambda *args, **kwargs: called.append(args) or FakeMBResponse({}))
    assert run_search(monkeypatch, "Song", ["中文艺人"], "Album", [candidate]) is None
    assert not called


def test_musicbrainz_artist_alias_confirms_cross_language_names(monkeypatch):
    ids = {
        "王菲": {"faye-mbid"},
        "Faye Wong": {"faye-search-mbid"},
        "薬師丸ひろ子": {"hiroko-mbid"},
        "Hiroko Yakushimaru": {"hiroko-search-mbid"},
        "岩崎太整": {"taisei-mbid"},
        "Taisei Iwasaki": {"taisei-search-mbid"},
    }
    aliases = {
        "faye-mbid": {"王菲", "fayewong"},
        "hiroko-mbid": {"薬師丸ひろ子", "hirokoyakushimaru"},
        "taisei-mbid": {"岩崎太整", "taiseiiwasaki"},
    }
    monkeypatch.setattr(spotify, "_musicbrainz_artist_ids", ids.get)
    monkeypatch.setattr(spotify, "_musicbrainz_artist_names", aliases.get)
    for source, candidate in [
        ("王菲", "Faye Wong"),
        ("薬師丸ひろ子", "Hiroko Yakushimaru"),
        ("岩崎太整", "Taisei Iwasaki"),
    ]:
        assert spotify._musicbrainz_artist_identity(
            [source], [{"name": candidate}]
        )


def test_musicbrainz_artist_alias_rejects_unrelated_names(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda name: {"faye-mbid"} if name == "王菲" else {"a7s-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_names",
        lambda mbid: {"王菲", "fayewong"} if mbid == "faye-mbid" else {"a7s"},
    )
    assert not spotify._musicbrainz_artist_identity(["王菲"], [{"name": "A7S"}])


def test_musicbrainz_artist_alias_requires_relevant_multi_artist_match(monkeypatch):
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_ids",
        lambda name: {"source-mbid"} if name == "岩崎太整" else {"unrelated-mbid"},
    )
    monkeypatch.setattr(
        spotify,
        "_musicbrainz_artist_names",
        lambda mbid: {"taisei iwasaki"} if mbid == "source-mbid" else {"ai ninomiya"},
    )
    assert not spotify._musicbrainz_artist_identity(
        ["岩崎太整"], [{"name": "Ai Ninomiya"}]
    )
