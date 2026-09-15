"""Conservative retrieval policy for cross-script artist recall.

The existing strict first Spotify search remains untouched. Only when that
search returns zero raw candidates do we relax query #2 from a strict
``artist:`` field to free artist text and use the simplified title. This keeps
the production budget at two Spotify searches and leaves all matcher safety
checks in place.
"""

from __future__ import annotations

from types import ModuleType


def apply(spotify: ModuleType) -> None:
    original_search_track = spotify.search_track

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

        def retrieval_get(url: str, token: str, params: dict):
            nonlocal spotify_search_count, first_search_empty
            if not url.endswith("/search"):
                return inner_get(url, token, params)

            spotify_search_count += 1
            effective_params = dict(params)
            if spotify_search_count == 2 and first_search_empty:
                title = spotify._spotify_query_value(
                    spotify._title_core(name) or name
                )
                artist_text = " ".join(
                    spotify._spotify_query_value(artist)
                    for artist in artists
                    if artist
                )
                query = f'track:"{title}"'
                if artist_text:
                    query += f" {artist_text}"
                effective_params["q"] = query
                effective_params["limit"] = 10
                print(
                    "Spotify retrieval fallback: "
                    f"query_index=2 mode=free-artist-text q={query}"
                )
                if diagnostics is not None:
                    diagnostics.setdefault("signals", []).append(
                        "RELAXED_SECOND_QUERY_AFTER_ZERO_CANDIDATES"
                    )
                    diagnostics["relaxed_second_query"] = query

            response = inner_get(url, token, effective_params)
            if spotify_search_count == 1:
                payload = {} if response is None else response.json()
                first_search_empty = not bool(
                    payload.get("tracks", {}).get("items", [])
                )
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
