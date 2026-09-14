"""Conservative final fallback based on Spotify artist-bound search consensus.

No extra Spotify requests are made. The existing two artist-bound searches run
first. Only when the normal matcher returns no result do we consider the top
result from each search, and only when both searches agree on the same ISRC.
"""

from __future__ import annotations

from types import ModuleType


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track

    class CapturedResponse:
        def __init__(self, payload: dict):
            self._payload = payload

        def json(self):
            return self._payload

    def eligible(
        name: str,
        artists: list[str],
        album: str,
        item: dict,
    ) -> bool:
        item_name = item.get("name", "")
        item_artists = item.get("artists", [])
        item_album = item.get("album", {}).get("name", "")
        isrc = (item.get("external_ids") or {}).get("isrc")
        if not item.get("id") or not isrc or not item_artists:
            return False

        title_exact = (
            spotify._normalize_text(spotify._title_core(name))
            in spotify._title_keys(item_name)
        )
        if not title_exact:
            return False
        if spotify._version_conflicts(name, album, item_name, item_album):
            return False

        artist_score, _, artist_reliable = spotify._artist_match_score(
            artists, item_artists
        )
        if artist_score != 0.35 or artist_reliable:
            return False

        source_asian = any(
            spotify._contains_cjk(value) or spotify._contains_kana(value)
            for value in artists
        )
        candidate_asian = any(
            spotify._contains_cjk(value.get("name", ""))
            or spotify._contains_kana(value.get("name", ""))
            for value in item_artists
        )
        if not source_asian or candidate_asian:
            return False

        album_points = spotify._album_score(album, item_album)
        if spotify._is_likely_rendition_project(
            artists,
            item_artists,
            album,
            item_name,
            item_album,
            album_points,
            True,
        ):
            return False
        return True

    def search_track(
        access_token: str,
        name: str,
        artists: list[str],
        album: str = "",
        duration_ms: int | None = None,
        *,
        diagnostics: dict | None = None,
    ) -> str | None:
        rank_one_items: list[dict] = []
        inner_get = spotify._spotify_get

        def capturing_get(url: str, token: str, params: dict):
            response = inner_get(url, token, params)
            if response is None:
                return None
            payload = response.json()
            query = str(params.get("q", ""))
            if url.endswith("/search") and 'artist:"' in query:
                items = payload.get("tracks", {}).get("items", [])
                if items:
                    rank_one_items.append(items[0])
            return CapturedResponse(payload)

        try:
            spotify._spotify_get = capturing_get
            matched = original_search_track(
                access_token,
                name,
                artists,
                album,
                duration_ms,
                diagnostics=diagnostics,
            )
        finally:
            spotify._spotify_get = inner_get

        if matched:
            return matched

        if len(rank_one_items) < 2:
            return None
        first, second = rank_one_items[0], rank_one_items[1]
        first_isrc = (first.get("external_ids") or {}).get("isrc")
        second_isrc = (second.get("external_ids") or {}).get("isrc")
        if not first_isrc or first_isrc != second_isrc:
            return None
        if not eligible(name, artists, album, first):
            return None

        print(
            "Spotify artist-bound rank consensus fallback: "
            f"track={first.get('name', '')} "
            f"artist={', '.join(a.get('name', '') for a in first.get('artists', []))} "
            f"isrc={first_isrc} result=ACCEPT"
        )
        if diagnostics is not None:
            diagnostics["category"] = None
            diagnostics.setdefault("signals", []).append(
                "ARTIST_BOUND_RANK1_CONSENSUS"
            )
            diagnostics["rank_consensus_isrc"] = first_isrc
        return first.get("id")

    spotify.search_track = search_track
