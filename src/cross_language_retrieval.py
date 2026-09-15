"""Narrow cross-language retrieval fallback for Spotify query #2.

The normal two-search matcher remains unchanged unless query #1 succeeds but
returns zero tracks for an Asian-script source artist. In that one case, query
#2 may use a MusicBrainz-confirmed Latin display name for the same artist.

This never adds a Spotify request and never broadens to track-only search.
"""

from __future__ import annotations

import re
from types import ModuleType


def _has_asian_script(value: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff"
        for char in value
    )


def _looks_latin_display_name(value: str) -> bool:
    return bool(value and not _has_asian_script(value) and re.search(r"[A-Za-z]", value))


def _display_from_sort_name(value: str) -> str | None:
    """Convert MusicBrainz ``Family, Given`` sort names to display order."""
    value = (value or "").strip()
    if not _looks_latin_display_name(value):
        return None
    if "," not in value:
        return value
    family, given = (part.strip() for part in value.split(",", 1))
    if not family or not given:
        return None
    return f"{given} {family}"


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track

    def cross_language_retrieval_artist(source_artist: str) -> str | None:
        """Return a conservative Latin display name for the exact MB artist."""
        if not source_artist or not _has_asian_script(source_artist):
            return None

        artist_ids = spotify._musicbrainz_artist_ids(source_artist)
        if len(artist_ids) != 1:
            return None
        mbid = next(iter(artist_ids))
        data = spotify._musicbrainz_get(
            f"artist/{mbid}",
            {"fmt": "json", "inc": "aliases"},
        )
        if not data:
            return None

        # Prefer an explicit Latin alias in natural display order. MusicBrainz
        # aliases can include locale-specific/native names, so only Latin
        # values are considered here.
        aliases = [
            (alias.get("name") or "").strip()
            for alias in data.get("aliases", [])
        ]
        natural_aliases = [
            value
            for value in aliases
            if _looks_latin_display_name(value) and "," not in value
        ]
        if natural_aliases:
            natural_aliases.sort(key=lambda value: (len(value.split()) < 2, len(value)))
            return natural_aliases[0]

        # The common MusicBrainz fallback is a Latin sort-name such as
        # ``Yamashita, Tatsuro``. Spotify generally indexes display order.
        sort_display = _display_from_sort_name(data.get("sort-name", ""))
        if sort_display:
            return sort_display

        canonical = (data.get("name") or "").strip()
        if _looks_latin_display_name(canonical):
            return canonical
        return None

    spotify._cross_language_retrieval_artist = cross_language_retrieval_artist

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
        search_count = 0
        first_search_was_empty = False
        alternate_artist: str | None = None

        def retrieval_get(url: str, token: str, params: dict):
            nonlocal search_count, first_search_was_empty, alternate_artist
            if not url.endswith("/search"):
                return inner_get(url, token, params)

            search_count += 1
            request_params = dict(params)

            if search_count == 2 and first_search_was_empty and artists:
                alternate_artist = spotify._cross_language_retrieval_artist(artists[0])
                if alternate_artist:
                    query_name = spotify._spotify_query_value(name)
                    query_artist = spotify._spotify_query_value(alternate_artist)
                    request_params["q"] = (
                        f'track:"{query_name}" artist:"{query_artist}"'
                    )
                    print(
                        "Spotify cross-language retrieval fallback: "
                        f"source_artist={artists[0]} alternate_artist={alternate_artist}"
                    )
                    if diagnostics is not None:
                        diagnostics.setdefault("signals", []).append(
                            "CROSS_LANGUAGE_SECOND_QUERY"
                        )
                        diagnostics["cross_language_query_artist"] = alternate_artist

            response = inner_get(url, token, request_params)
            if search_count == 1 and response is not None:
                try:
                    first_search_was_empty = not response.json().get("tracks", {}).get("items", [])
                except (AttributeError, ValueError):
                    first_search_was_empty = False
            return response

        try:
            spotify._spotify_get = retrieval_get
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
