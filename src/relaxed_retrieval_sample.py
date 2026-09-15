"""Small read-only sample for the relaxed second Spotify query.

Exactly ten Spotify Search requests are made. No playlist writes and no
MusicBrainz calls are performed. The report records the top ten candidates so
we can see whether formerly zero-candidate tracks gain useful recall.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import spotify


SAMPLES = [
    ("MUSIC BOOK", "山下達郎"),
    ("Magic Ways", "山下達郎"),
    ("CRESCENT AVENTURE", "角松敏生"),
    ("Do You Love Me", "国分友里恵"),
    ("Kusuri Wo Takusan", "大貫妙子"),
    ("Machibouke", "豊島たづみ"),
    ("TALK TO ME", "刀根麻理子"),
    ("Hidari Mune No Seiza", "林哲司"),
    ("Subterranean Futari Bocci", "佐藤奈々子"),
    ("真夜中のドア〜stay with me (シングルver.)", "松原みき"),
]


def main() -> None:
    token = spotify.get_access_token(
        os.environ["SPOTIFY_CLIENT_ID"],
        os.environ["SPOTIFY_CLIENT_SECRET"],
        os.environ["SPOTIFY_REFRESH_TOKEN"],
    )
    rows = []
    for title, artist in SAMPLES:
        query = (
            f'track:"{spotify._spotify_query_value(title)}" '
            f'{spotify._spotify_query_value(artist)}'
        )
        response = spotify._spotify_get(
            f"{spotify.SPOTIFY_API_URL}/search",
            token,
            {"q": query, "type": "track", "limit": 10},
        )
        items = [] if response is None else response.json().get("tracks", {}).get("items", [])
        candidates = []
        for rank, item in enumerate(items, 1):
            item_artists = item.get("artists", [])
            artist_score, _, artist_reliable = spotify._artist_match_score(
                [artist], item_artists
            )
            candidates.append({
                "rank": rank,
                "spotify_track_id": item.get("id"),
                "title": item.get("name", ""),
                "artists": [value.get("name", "") for value in item_artists],
                "album": item.get("album", {}).get("name", ""),
                "isrc": (item.get("external_ids") or {}).get("isrc"),
                "title_match": spotify._title_match(title, item.get("name", "")),
                "artist_score": artist_score,
                "artist_reliable": artist_reliable,
                "version_conflicts": spotify._version_conflicts(
                    title,
                    "",
                    item.get("name", ""),
                    item.get("album", {}).get("name", ""),
                ),
            })
        rows.append({
            "source_title": title,
            "source_artist": artist,
            "query": query,
            "candidate_count": len(candidates),
            "candidates": candidates,
        })
        print(f"{title} - {artist}: {len(candidates)} candidates")

    report = {
        "spotify_search_requests": len(SAMPLES),
        "sample_count": len(SAMPLES),
        "tracks_with_candidates": sum(bool(row["candidate_count"]) for row in rows),
        "tracks_with_title_match": sum(
            any(item["title_match"] for item in row["candidates"])
            for row in rows
        ),
        "tracks": rows,
    }
    Path("relaxed_retrieval_sample.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
