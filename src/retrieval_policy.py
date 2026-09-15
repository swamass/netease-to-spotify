"""Conservative cross-language retrieval policy.

The production matcher still performs at most two Spotify searches. Query #1
is untouched. Only when query #1 succeeds but returns zero candidates do we
allow query #2 to replace the source artist with one unambiguous Latin display
name derived from MusicBrainz.
"""

from __future__ import annotations

import re
from types import ModuleType


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track
    retrieval_name_cache: dict[str, str | None] = {}

    def is_latin_display_name(value: str) -> bool:
        return bool(
            value
            and re.search(r"[A-Za-z]", value)
            and not spotify._contains_cjk(value)
            and not spotify._contains_kana(value)
        )

    def normalize_sort_name(value: str) -> str:
        parts = [part.strip() for part in value.split(",")]
        if len(parts) == 2 and all(parts):
            return f"{parts[1]} {parts[0]}"
        return value.strip()

    def artist_names(artist: dict) -> set[str]:
        values = {artist.get("name", ""), artist.get("sort-name", "")}
        values.update(
            alias.get("name", "")
            for alias in artist.get("aliases", [])
            if alias.get("name")
        )
        return {
            spotify._normalize_text(value)
            for value in values
            if value
        }

    def exact_artist_rows(data: dict | None, source_artist: str) -> list[dict]:
        source_key = spotify._normalize_text(source_artist)
        return [
            artist
            for artist in (data or {}).get("artists", [])
            if artist.get("id") and source_key in artist_names(artist)
        ]

    def choose_display_name(data: dict, source_artist: str) -> str | None:
        candidates: list[tuple[int, str]] = []
        for alias in data.get("aliases", []):
            raw = (alias.get("name") or "").strip()
            if not is_latin_display_name(raw):
                continue
            display = normalize_sort_name(raw)
            if is_latin_display_name(display):
                candidates.append((0 if "," not in raw else 2, display))

        sort_name = (data.get("sort-name") or "").strip()
        if is_latin_display_name(sort_name):
            display = normalize_sort_name(sort_name)
            if is_latin_display_name(display):
                candidates.append((1, display))

        canonical = (data.get("name") or "").strip()
        if is_latin_display_name(canonical):
            candidates.append((1, normalize_sort_name(canonical)))

        source_key = spotify._normalize_text(source_artist)
        unique: dict[str, tuple[int, str]] = {}
        for priority, value in candidates:
            key = spotify._normalize_text(value)
            if not key or key == source_key:
                continue
            previous = unique.get(key)
            if previous is None or priority < previous[0]:
                unique[key] = (priority, value)
        if not unique:
            return None
        return min(unique.values(), key=lambda item: (item[0], len(item[1])))[1]

    def retrieval_artist_name(source_artist: str) -> str | None:
        key = spotify._normalize_text(source_artist)
        if key in retrieval_name_cache:
            return retrieval_name_cache[key]
        if not source_artist or not (
            spotify._contains_cjk(source_artist)
            or spotify._contains_kana(source_artist)
        ):
            retrieval_name_cache[key] = None
            return None

        data = spotify._musicbrainz_get(
            "artist",
            {
                "query": f'artist:"{source_artist}"',
                "fmt": "json",
                "limit": "5",
            },
        )
        rows = exact_artist_rows(data, source_artist)
        if not rows:
            data = spotify._musicbrainz_get(
                "artist",
                {"query": source_artist, "fmt": "json", "limit": "5"},
            )
            rows = exact_artist_rows(data, source_artist)
        if len(rows) != 1:
            retrieval_name_cache[key] = None
            return None

        row = rows[0]
        display = choose_display_name(row, source_artist)
        if not display:
            detail = spotify._musicbrainz_get(
                f"artist/{row['id']}",
                {"fmt": "json", "inc": "aliases"},
            )
            if detail:
                display = choose_display_name(detail, source_artist)

        retrieval_name_cache[key] = display
        return display

    spotify._musicbrainz_retrieval_artist_name = retrieval_artist_name
    spotify._musicbrainz_retrieval_name_cache = retrieval_name_cache

    def search_track(
        access_token: str,
        name: str,
        artists: list[str],
        album: str = "",
        duration_ms: int | None = None,
        *,
        diagnostics: dict | None = None,
    ) -> str | None:
        inner_get = spotify._spotify_get
        search_calls = 0
        first_search_returned_zero = False

        def rewriting_get(url: str, token: str, params: dict):
            nonlocal search_calls, first_search_returned_zero
            adjusted = params
            if url.endswith("/search"):
                search_calls += 1
                if (
                    search_calls == 2
                    and first_search_returned_zero
                    and artists
                ):
                    alternate = retrieval_artist_name(artists[0])
                    if alternate:
                        adjusted = dict(params)
                        adjusted["q"] = (
                            f'track:"{spotify._spotify_query_value(name)}" '
                            f'artist:"{spotify._spotify_query_value(alternate)}"'
                        )
                        print(
                            "Spotify retrieval fallback: "
                            f"source_artist={artists[0]} "
                            f"alternate_artist={alternate}"
                        )
                        if diagnostics is not None:
                            diagnostics.setdefault("signals", []).append(
                                "MB_DISPLAY_ARTIST_QUERY2"
                            )
                            diagnostics["query2_artist"] = alternate

            response = inner_get(url, token, adjusted)
            if url.endswith("/search") and search_calls == 1 and response is not None:
                payload = response.json()
                first_search_returned_zero = not bool(
                    payload.get("tracks", {}).get("items", [])
                )
            return response

        try:
            spotify._spotify_get = rewriting_get
            return original_search_track(
                access_token,
                name,
                artists,
                album,
                duration_ms,
                diagnostics=diagnostics,
            )
        finally:
            spotify._spotify_get = inner_get

    spotify.search_track = search_track
