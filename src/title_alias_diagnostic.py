"""Conservative MusicBrainz title-alias discovery for diagnostics only.

This module never changes production matching. It tries to identify one
recording using an exact source-artist MusicBrainz identity plus the source
track title, then inspects track titles attached to releases of that same
recording. A unique high-confidence release title can be used as a diagnostic
Spotify query title.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from . import spotify


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _exact_artist_mbids(source_artist: str) -> set[str]:
    if not source_artist:
        return set()
    data = spotify._musicbrainz_get(
        "artist",
        {
            "query": f'artist:"{_escape_query(source_artist)}"',
            "fmt": "json",
            "limit": "5",
        },
    )
    source_key = spotify._normalize_text(source_artist)
    exact: set[str] = set()
    for artist in (data or {}).get("artists", []):
        values = [
            artist.get("name", ""),
            artist.get("sort-name", ""),
            *(alias.get("name", "") for alias in artist.get("aliases", [])),
        ]
        if source_key in {
            spotify._normalize_text(value) for value in values if value
        }:
            mbid = artist.get("id")
            if mbid:
                exact.add(mbid)
    return exact


def _title_variants(source_title: str) -> list[str]:
    original = unicodedata.normalize("NFKC", source_title).strip()
    simplified = re.sub(r"\s*[\(（][^\)）]*[\)）]\s*$", "", original).strip()
    variants = [original]
    if simplified and simplified != original:
        variants.append(simplified)
    return list(dict.fromkeys(value for value in variants if value))


def _recording_artist_ids(recording: dict) -> set[str]:
    ids: set[str] = set()
    for credit in recording.get("artist-credit", []):
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") or {}
        mbid = artist.get("id")
        if mbid:
            ids.add(mbid)
    return ids


def _find_recording_ids(source_title: str, artist_mbid: str) -> set[str]:
    best_score = -1
    best_rows: list[dict] = []
    for title in _title_variants(source_title):
        data = spotify._musicbrainz_get(
            "recording",
            {
                "query": (
                    f'recording:"{_escape_query(title)}" AND arid:{artist_mbid}'
                ),
                "fmt": "json",
                "limit": "5",
            },
        )
        for row in (data or {}).get("recordings", []):
            try:
                score = int(row.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            if score < 95 or artist_mbid not in _recording_artist_ids(row):
                continue
            if score > best_score:
                best_score = score
                best_rows = [row]
            elif score == best_score:
                best_rows.append(row)
        if best_score == 100:
            break

    return {
        row.get("id")
        for row in best_rows
        if row.get("id")
    }


def _track_title_evidence(recording_id: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    data = spotify._musicbrainz_get(
        "release",
        {
            "recording": recording_id,
            "fmt": "json",
            "limit": "50",
            "inc": "media+recordings",
        },
    )
    evidence: list[tuple[str, tuple[int, int, int, int]]] = []
    for release in (data or {}).get("releases", []):
        country = str(release.get("country", "")).upper()
        official = str(release.get("status", "")).casefold() == "official"
        for medium in release.get("media", []):
            is_digital = str(medium.get("format", "")).casefold() == "digital media"
            for track in medium.get("tracks", []):
                recording = track.get("recording") or {}
                if recording.get("id") != recording_id:
                    continue
                title = str(track.get("title", "")).strip()
                if not title:
                    continue
                rank = (
                    int(is_digital and country == "XW"),
                    int(is_digital),
                    int(country == "XW"),
                    int(official),
                )
                evidence.append((title, rank))
    return evidence


def discover_title_alias(source_title: str, source_artist: str) -> tuple[str | None, dict]:
    """Return one uniquely supported alternate release title, or ``None``."""
    trace: dict = {
        "source_title": source_title,
        "source_artist": source_artist,
        "artist_mbid": None,
        "recording_ids": [],
        "selected_title": None,
        "reason": None,
    }

    artist_ids = _exact_artist_mbids(source_artist)
    if len(artist_ids) != 1:
        trace["reason"] = "ARTIST_IDENTITY_NOT_UNIQUE"
        return None, trace
    artist_mbid = next(iter(artist_ids))
    trace["artist_mbid"] = artist_mbid

    recording_ids = _find_recording_ids(source_title, artist_mbid)
    trace["recording_ids"] = sorted(recording_ids)
    if not recording_ids:
        trace["reason"] = "RECORDING_NOT_FOUND"
        return None, trace

    source_key = spotify._normalize_text(source_title)
    simplified_keys = {
        spotify._normalize_text(value) for value in _title_variants(source_title)
    }
    candidates: dict[str, dict] = defaultdict(
        lambda: {"title": "", "best_rank": (0, 0, 0, 0), "count": 0}
    )
    for recording_id in sorted(recording_ids):
        for title, rank in _track_title_evidence(recording_id):
            key = spotify._normalize_text(title)
            if not key or key == source_key or key in simplified_keys:
                continue
            if spotify._version_conflicts(source_title, "", title, ""):
                continue
            item = candidates[key]
            item["title"] = title
            item["best_rank"] = max(item["best_rank"], rank)
            item["count"] += 1

    if not candidates:
        trace["reason"] = "NO_ALTERNATE_RELEASE_TITLE"
        return None, trace

    ranked = sorted(
        candidates.values(),
        key=lambda item: (item["best_rank"], item["count"]),
        reverse=True,
    )
    best_key = (ranked[0]["best_rank"], ranked[0]["count"])
    tied = [item for item in ranked if (item["best_rank"], item["count"]) == best_key]
    if len(tied) != 1:
        trace["reason"] = "ALTERNATE_TITLE_AMBIGUOUS"
        return None, trace

    selected = tied[0]["title"]
    trace["selected_title"] = selected
    trace["reason"] = "UNIQUE_RELEASE_TITLE"
    trace["evidence_rank"] = list(tied[0]["best_rank"])
    trace["evidence_count"] = tied[0]["count"]
    return selected, trace


def discover_title_aliases(
    songs: list[dict[str, str]],
) -> tuple[dict[tuple[str, str], str], list[dict]]:
    aliases: dict[tuple[str, str], str] = {}
    traces: list[dict] = []
    for song in songs:
        alias, trace = discover_title_alias(song["title"], song["artist"])
        traces.append(trace)
        if alias:
            aliases[
                (
                    spotify._normalize_text(song["title"]),
                    spotify._normalize_text(song["artist"]),
                )
            ] = alias
    return aliases, traces
