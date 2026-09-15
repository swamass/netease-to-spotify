"""Small read-only live check for romanized artist retrieval.

Never writes playlists. Uses at most two Spotify Search requests per source
track through the production matcher stack and records the actual outgoing
queries plus returned candidates.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import spotify


CASES = [
    {"title": "CRESCENT AVENTURE", "artist": "角松敏生"},
    {"title": "香港街燈", "artist": "角松敏生"},
    {"title": "たそがれ (Twilight)", "artist": "山根麻以"},
    {"title": "Hidari Mune No Seiza", "artist": "林哲司"},
    {"title": "Kusuri Wo Takusan", "artist": "大貫妙子"},
]


def main() -> None:
    token = spotify.get_access_token(
        os.environ["SPOTIFY_CLIENT_ID"],
        os.environ["SPOTIFY_CLIENT_SECRET"],
        os.environ["SPOTIFY_REFRESH_TOKEN"],
    )
    report = {"spotify_writes": 0, "cases": []}
    real_get = spotify._spotify_get

    for source in CASES:
        queries = []
        responses = []

        def capture_get(url: str, access_token: str, params: dict):
            response = real_get(url, access_token, params)
            if url.endswith("/search"):
                payload = {} if response is None else response.json()
                items = payload.get("tracks", {}).get("items", [])
                queries.append(str(params.get("q", "")))
                responses.append([
                    {
                        "rank": rank,
                        "id": item.get("id"),
                        "title": item.get("name", ""),
                        "artists": [a.get("name", "") for a in item.get("artists", [])],
                        "album": item.get("album", {}).get("name", ""),
                        "isrc": (item.get("external_ids") or {}).get("isrc"),
                    }
                    for rank, item in enumerate(items, 1)
                ])
            return response

        spotify._spotify_get = capture_get
        diagnostics = {}
        try:
            accepted = spotify.search_track(
                token,
                source["title"],
                [source["artist"]],
                "",
                diagnostics=diagnostics,
            )
        finally:
            spotify._spotify_get = real_get

        report["cases"].append({
            **source,
            "queries": queries,
            "responses": responses,
            "accepted_track_id": accepted,
            "matcher_diagnostics": diagnostics,
        })
        print(
            f"{source['title']} - {source['artist']}: "
            f"accepted={accepted or 'NONE'} searches={len(queries)}"
        )

    Path("romanized_retrieval_spotcheck.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
