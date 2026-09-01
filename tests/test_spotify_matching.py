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


def test_weak_artist_case_is_not_made_more_permissive(monkeypatch):
    result = run_search(
        monkeypatch,
        "SMALL HAPPINESS",
        ["麗美"],
        "Love Letter ORIGINAL SOUND TRACK",
        [track(
            "remedios",
            "SMALL HAPPINESS",
            ["REMEDIOS"],
            "Love Letter ORIGINAL SOUND TRACK",
        )],
    )
    assert result is None
