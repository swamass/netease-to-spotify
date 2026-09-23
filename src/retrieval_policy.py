"""Conservative retrieval policy for cross-script artist recall.

The strict first Spotify search remains untouched. Only when that search
successfully returns zero raw candidates and the source artist uses CJK or
kana do we alter query #2. A trustworthy MusicBrainz-derived Latin artist name
is preferred; otherwise we retain the existing free-artist-text fallback. The
production budget remains at two Spotify searches and matcher safety checks are
unchanged.
"""

from __future__ import annotations

import re
import unicodedata
from types import ModuleType

_diagnostic_title_variant_hook = None


def set_diagnostic_title_variant_hook(hook) -> None:
    global _diagnostic_title_variant_hook
    _diagnostic_title_variant_hook = hook


def diagnostic_title_variant(title: str) -> str | None:
    if _diagnostic_title_variant_hook is None:
        return None
    return _diagnostic_title_variant_hook(title)


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track
    retrieval_alias_cache: dict[tuple[str, int], str | None] = {}
    spotify._retrieval_artist_alias_cache = retrieval_alias_cache

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
            return (
                natural
                if family and given and is_latin_display_name(natural)
                else None
            )
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

        # Including the getter identity keeps the production cache stable while
        # naturally isolating tests or alternate providers that monkeypatch it.
        cache_key = (
            spotify._normalize_text(source_name),
            id(spotify._musicbrainz_get),
        )
        if cache_key in retrieval_alias_cache:
            return retrieval_alias_cache[cache_key]

        result: str | None = None
        data = spotify._musicbrainz_get(
            "artist",
            {"query": f'artist:"{source_name}"', "fmt": "json", "limit": "5"},
        )
        exact_results = [
            artist
            for artist in (data or {}).get("artists", [])
            if exact_source_artist(artist, source_name)
        ]

        for artist in exact_results:
            natural_sort = naturalize_sort_name(artist.get("sort-name", ""))
            if (
                natural_sort
                and spotify._normalize_text(natural_sort)
                != spotify._normalize_text(source_name)
            ):
                result = natural_sort
                break

            canonical = artist.get("name", "")
            if (
                is_latin_display_name(canonical)
                and spotify._normalize_text(canonical)
                != spotify._normalize_text(source_name)
            ):
                result = canonical
                break

            for alias in artist.get("aliases", []):
                alias_name = alias.get("name", "")
                if (
                    is_latin_display_name(alias_name)
                    and spotify._normalize_text(alias_name)
                    != spotify._normalize_text(source_name)
                ):
                    result = naturalize_sort_name(alias_name) or alias_name
                    break
            if result:
                break

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
            if (
                natural_sort
                and spotify._normalize_text(natural_sort)
                != spotify._normalize_text(source_name)
            ):
                result = natural_sort
                break
            canonical = detail.get("name", "")
            if (
                is_latin_display_name(canonical)
                and spotify._normalize_text(canonical)
                != spotify._normalize_text(source_name)
            ):
                result = canonical
                break
            for alias in detail.get("aliases", []):
                alias_name = alias.get("name", "")
                if (
                    is_latin_display_name(alias_name)
                    and spotify._normalize_text(alias_name)
                    != spotify._normalize_text(source_name)
                ):
                    result = naturalize_sort_name(alias_name) or alias_name
                    break
            if result:
                break

        retrieval_alias_cache[cache_key] = result
        return result

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
        spotify_search_count = 0
        first_search_empty = False
        source_artist_has_asian_script = any(
            spotify._contains_cjk(artist) or spotify._contains_kana(artist)
            for artist in artists
        )

        def retrieval_get(url: str, token: str, params: dict):
            nonlocal spotify_search_count, first_search_empty
            if not url.endswith("/search"):
                return inner_get(url, token, params)

            spotify_search_count += 1
            effective_params = dict(params)
            if spotify_search_count == 2 and first_search_empty:
                title_override = diagnostic_title_variant(name)
                alias = None
                if title_override:
                    query = (
                        f'track:"{spotify._spotify_query_value(title_override)}" '
                        f'artist:"{spotify._spotify_query_value(artists[0])}"'
                    )
                    signal = "DIAGNOSTIC_TITLE_VARIANT_SECOND_QUERY"
                    print(
                        "Spotify retrieval fallback: "
                        f"query_index=2 mode=diagnostic-title-variant "
                        f"source_artist={artists[0]} q={query}"
                    )
                    if diagnostics is not None:
                        diagnostics["retrieval_title"] = title_override
                elif source_artist_has_asian_script:
                    alias = (
                        spotify._retrieval_artist_alias(artists[0])
                        if artists
                        else None
                    )
                if (
                    not title_override
                    and source_artist_has_asian_script
                    and alias
                ):
                    title = spotify._retrieval_query_title(name)
                    query = (
                        f'track:"{spotify._spotify_query_value(title)}" '
                        f'artist:"{spotify._spotify_query_value(alias)}"'
                    )
                    signal = "ROMANIZED_SECOND_QUERY_AFTER_ZERO_CANDIDATES"
                    print(
                        "Spotify retrieval fallback: "
                        f"query_index=2 mode=romanized-artist-field "
                        f"source_artist={artists[0]} retrieval_artist={alias} "
                        f"q={query}"
                    )
                    if diagnostics is not None:
                        diagnostics["retrieval_artist"] = alias
                        diagnostics["retrieval_title"] = title
                elif not title_override and source_artist_has_asian_script:
                    title = spotify._spotify_query_value(name)
                    artist_text = " ".join(
                        spotify._spotify_query_value(artist)
                        for artist in artists
                        if artist
                    )
                    query = f'track:"{title}"'
                    if artist_text:
                        query += f" {artist_text}"
                    signal = "RELAXED_SECOND_QUERY_AFTER_ZERO_CANDIDATES"
                    print(
                        "Spotify retrieval fallback: "
                        f"query_index=2 mode=free-artist-text q={query}"
                    )
                if title_override or source_artist_has_asian_script:
                    effective_params["q"] = query
                    effective_params["limit"] = 10
                    if diagnostics is not None:
                        signals = diagnostics.setdefault("signals", [])
                        if signal not in signals:
                            signals.append(signal)
                        diagnostics["relaxed_second_query"] = query

            response = inner_get(url, token, effective_params)
            if spotify_search_count == 1:
                # A transport/API failure is not evidence that the strict
                # query had zero results, so never broaden on ``None``.
                if response is None:
                    first_search_empty = False
                else:
                    try:
                        first_search_empty = not bool(
                            response.json().get("tracks", {}).get("items", [])
                        )
                    except (AttributeError, ValueError):
                        first_search_empty = False
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
