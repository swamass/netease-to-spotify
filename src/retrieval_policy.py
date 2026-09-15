"""Improve Spotify query #2 without increasing the search budget.

The first, album-aware artist-bound query is unchanged. Only when matching
reaches the second Spotify Search do we try a trustworthy MusicBrainz-derived
Latin display name for an Asian-script source artist. If no such name can be
verified, the original second query is used unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from types import ModuleType


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track

    def is_latin_display_name(value: str) -> bool:
        normalized = unicodedata.normalize("NFKC", value).strip()
        if not normalized:
            return False
        if spotify._contains_cjk(normalized) or spotify._contains_kana(normalized):
            return False
        return any("a" <= char.casefold() <= "z" for char in normalized)

    def naturalize_sort_name(value: str) -> str | None:
        value = unicodedata.normalize("NFKC", value).strip()
        if value.count(",") == 1:
            family, given = (part.strip() for part in value.split(",", 1))
            natural = f"{given} {family}".strip()
            return natural if family and given and is_latin_display_name(natural) else None
        return value if is_latin_display_name(value) else None

    def exact_source_artist(result: dict, source_name: str) -> bool:
        source_key = spotify._normalize_text(source_name)
        values = [
            result.get("name", ""),
            result.get("sort-name", ""),
            *(alias.get("name", "") for alias in result.get("aliases", [])),
        ]
        return source_key in {
            spotify._normalize_text(value) for value in values if value
        }

    def retrieval_artist_alias(source_name: str) -> str | None:
        if not source_name or not (
            spotify._contains_cjk(source_name) or spotify._contains_kana(source_name)
        ):
            return None

        search_data = spotify._musicbrainz_get(
            "artist",
            {"query": f'artist:"{source_name}"', "fmt": "json", "limit": "5"},
        )
        exact_results = [
            artist
            for artist in (search_data or {}).get("artists", [])
            if exact_source_artist(artist, source_name)
        ]
        if not exact_results:
            return None

        for artist in exact_results:
            natural_sort = naturalize_sort_name(artist.get("sort-name", ""))
            if natural_sort and spotify._normalize_text(natural_sort) != spotify._normalize_text(source_name):
                return natural_sort

            canonical = artist.get("name", "")
            if (
                is_latin_display_name(canonical)
                and spotify._normalize_text(canonical) != spotify._normalize_text(source_name)
            ):
                return canonical

            for alias in artist.get("aliases", []):
                alias_name = alias.get("name", "")
                if (
                    is_latin_display_name(alias_name)
                    and spotify._normalize_text(alias_name) != spotify._normalize_text(source_name)
                ):
                    return naturalize_sort_name(alias_name) or alias_name

            mbid = artist.get("id")
            if not mbid:
                continue
            detail = spotify._musicbrainz_get(
                f"artist/{mbid}",
                {"fmt": "json", "inc": "aliases"},
            )
            if not detail:
                continue
            natural_sort = naturalize_sort_name(detail.get("sort-name", ""))
            if natural_sort and spotify._normalize_text(natural_sort) != spotify._normalize_text(source_name):
                return natural_sort
            canonical = detail.get("name", "")
            if (
                is_latin_display_name(canonical)
                and spotify._normalize_text(canonical) != spotify._normalize_text(source_name)
            ):
                return canonical
            for alias in detail.get("aliases", []):
                alias_name = alias.get("name", "")
                if (
                    is_latin_display_name(alias_name)
                    and spotify._normalize_text(alias_name) != spotify._normalize_text(source_name)
                ):
                    return naturalize_sort_name(alias_name) or alias_name
        return None

    def retrieval_title(name: str) -> str:
        core = spotify._title_core(name)
        simplified = re.sub(r"\s*\([^)]*\)\s*$", "", core).strip()
        return simplified or core or name

    spotify._retrieval_artist_alias = retrieval_artist_alias
    spotify._retrieval_query_title = retrieval_title

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

        def rewriting_get(url: str, token: str, params: dict):
            nonlocal search_calls
            if not url.endswith("/search"):
                return inner_get(url, token, params)

            search_calls += 1
            if search_calls != 2 or not artists:
                return inner_get(url, token, params)

            alias = spotify._retrieval_artist_alias(artists[0])
            if not alias:
                return inner_get(url, token, params)

            query_title = spotify._retrieval_query_title(name)
            rewritten = dict(params)
            rewritten["q"] = (
                f'track:"{spotify._spotify_query_value(query_title)}" '
                f'artist:"{spotify._spotify_query_value(alias)}"'
            )
            print(
                "Spotify retrieval query #2 romanized artist: "
                f"source_artist={artists[0]} retrieval_artist={alias} "
                f"title={query_title}"
            )
            if diagnostics is not None:
                diagnostics.setdefault("signals", []).append(
                    "ROMANIZED_SECOND_QUERY"
                )
                diagnostics["retrieval_artist"] = alias
                diagnostics["retrieval_title"] = query_title
            return inner_get(url, token, rewritten)

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
