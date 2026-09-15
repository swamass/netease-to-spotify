"""Use a MusicBrainz romanized artist name for Spotify search #2.

The first Spotify query stays unchanged. For Asian-script source artists, the
second query may replace only the artist field with a verified Latin-script
MusicBrainz canonical/alias name. This does not add Spotify Search requests and
does not change matcher acceptance rules.
"""

from __future__ import annotations

import re
from types import ModuleType


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track
    artist_record_cache: dict[str, dict | None] = {}

    def clear_cache() -> None:
        artist_record_cache.clear()

    def latin_only(value: str) -> bool:
        return bool(re.search(r"[A-Za-z]", value)) and not (
            spotify._contains_cjk(value) or spotify._contains_kana(value)
        )

    def display_name(value: str) -> str:
        value = " ".join(value.split()).strip()
        if value.count(",") == 1:
            family, given = (part.strip() for part in value.split(",", 1))
            if family and given:
                return f"{given} {family}"
        return value

    def retrieval_artist_record(source_artist: str) -> dict | None:
        key = spotify._normalize_text(source_artist)
        if key in artist_record_cache:
            return artist_record_cache[key]
        if not source_artist or not (
            spotify._contains_cjk(source_artist)
            or spotify._contains_kana(source_artist)
        ):
            artist_record_cache[key] = None
            return None

        artist_ids = spotify._musicbrainz_artist_ids(source_artist)
        if len(artist_ids) != 1:
            artist_record_cache[key] = None
            return None

        mbid = next(iter(artist_ids))
        data = spotify._musicbrainz_get(
            f"artist/{mbid}",
            {"fmt": "json", "inc": "aliases"},
        )
        if not data:
            artist_record_cache[key] = None
            return None

        candidates: list[tuple[int, str]] = []
        canonical = data.get("name", "")
        sort_name = data.get("sort-name", "")
        aliases = [
            alias.get("name", "")
            for alias in data.get("aliases", [])
            if alias.get("name")
        ]

        for alias in aliases:
            shown = display_name(alias)
            if latin_only(shown):
                candidates.append((30 if "," not in alias else 20, shown))
        if sort_name:
            shown = display_name(sort_name)
            if latin_only(shown):
                candidates.append((25 if "," in sort_name else 15, shown))
        if canonical:
            shown = display_name(canonical)
            if latin_only(shown):
                candidates.append((10, shown))

        if not candidates:
            artist_record_cache[key] = None
            return None

        _, chosen = max(
            candidates,
            key=lambda pair: (pair[0], -len(pair[1]), pair[1].casefold()),
        )
        record = {
            "mbid": mbid,
            "data": data,
            "display_name": chosen,
        }
        artist_record_cache[key] = record
        return record

    def retrieval_artist_name(source_artist: str) -> str | None:
        record = retrieval_artist_record(source_artist)
        return record["display_name"] if record else None

    spotify._clear_musicbrainz_retrieval_artist_cache = clear_cache
    spotify._musicbrainz_retrieval_artist_record = retrieval_artist_record
    spotify._musicbrainz_retrieval_artist_name = retrieval_artist_name

    def search_track(
        access_token: str,
        name: str,
        artists: list[str],
        album: str = "",
        duration_ms: int | None = None,
        *,
        diagnostics: dict | None = None,
    ) -> str | None:
        retrieval_name = retrieval_artist_name(artists[0]) if artists else None
        if not retrieval_name:
            return original_search_track(
                access_token,
                name,
                artists,
                album,
                duration_ms,
                diagnostics=diagnostics,
            )

        source_query_artist = spotify._spotify_query_value(artists[0])
        alternate_query_artist = spotify._spotify_query_value(retrieval_name)
        original_get = spotify._spotify_get
        search_number = 0

        def query_rewriting_get(url: str, token: str, params: dict):
            nonlocal search_number
            rewritten = dict(params)
            if url.endswith("/search"):
                search_number += 1
                if search_number == 2:
                    q = str(rewritten.get("q", ""))
                    source_field = f'artist:"{source_query_artist}"'
                    alternate_field = f'artist:"{alternate_query_artist}"'
                    if source_field in q:
                        rewritten["q"] = q.replace(source_field, alternate_field, 1)
                        print(
                            "Spotify retrieval artist fallback: "
                            f"source_artist={artists[0]} "
                            f"search_artist={retrieval_name}"
                        )
            return original_get(url, token, rewritten)

        try:
            spotify._spotify_get = query_rewriting_get
            return original_search_track(
                access_token,
                name,
                artists,
                album,
                duration_ms,
                diagnostics=diagnostics,
            )
        finally:
            spotify._spotify_get = original_get

    spotify.search_track = search_track
