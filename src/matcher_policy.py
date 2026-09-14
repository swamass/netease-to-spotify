"""Shared conservative matcher policy overrides.

Two narrow MusicBrainz policies live here:
1. Artist lookup only trusts exact canonical/sort-name/alias evidence and falls
   back to an unfielded search when a fielded search returns fuzzy results.
2. When a title already matches and artist identity is confirmed, missing
   MusicBrainz recording rows for an ISRC do not veto the match.

Cross-script title rescue still requires recording-level evidence.
"""

from __future__ import annotations

from types import ModuleType


def apply(spotify: ModuleType) -> None:
    """Apply the shared matcher policy to the loaded ``spotify`` module."""

    def artist_result_names(artist: dict) -> set[str]:
        values = {
            artist.get("name", ""),
            artist.get("sort-name", ""),
        }
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

    def exact_artist_ids(data: dict | None, name: str) -> set[str]:
        normalized_name = spotify._normalize_text(name)
        return {
            artist.get("id")
            for artist in (data or {}).get("artists", [])
            if artist.get("id")
            and normalized_name in artist_result_names(artist)
        }

    def musicbrainz_artist_ids(name: str) -> set[str]:
        """Resolve only exact canonical/alias identity, never fuzzy search hits."""
        if not name:
            return set()

        field_data = spotify._musicbrainz_get(
            "artist",
            {"query": f'artist:"{name}"', "fmt": "json", "limit": "5"},
        )
        field_ids = exact_artist_ids(field_data, name)
        if field_ids:
            return field_ids

        # A non-empty field query can still be a fuzzy MusicBrainz hit. Do not
        # stop there. The unfielded query often exposes canonical names and
        # aliases that let us verify Japanese/Chinese <-> romanized identities.
        fallback_data = spotify._musicbrainz_get(
            "artist",
            {"query": name, "fmt": "json", "limit": "5"},
        )
        return exact_artist_ids(fallback_data, name)

    spotify._musicbrainz_artist_ids = musicbrainz_artist_ids

    def musicbrainz_recording_identity_accepts(
        source_name: str,
        source_artists: list[str],
        source_album: str,
        candidate: dict,
        allow_cross_script_title: bool = False,
    ) -> bool:
        isrc = (candidate.get("external_ids") or {}).get("isrc")
        if not isrc:
            return False

        candidate_name = candidate.get("name", "")
        if (
            not allow_cross_script_title
            and not spotify._title_match(source_name, candidate_name)
        ):
            return False

        if spotify._version_conflicts(
            source_name,
            source_album,
            candidate_name,
            candidate.get("album", {}).get("name", ""),
        ):
            return False

        artist_ids = spotify._musicbrainz_artist_identity(
            source_artists,
            candidate.get("artists", []),
        )
        if not artist_ids:
            return False

        recordings = spotify._musicbrainz_recordings_for_isrc(isrc)
        print(f"MB ISRC lookup: isrc={isrc} recording_count={len(recordings)}")

        if not recordings:
            confirmed = not allow_cross_script_title
            print(
                "MB ISRC verification: "
                f"isrc={isrc} duration_diff_ms=None "
                f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'} "
                f"reason={'artist+title fallback' if confirmed else 'cross-script requires recording evidence'}"
            )
            return confirmed

        candidate_duration = spotify._coerce_duration_ms(candidate.get("duration_ms"))
        best_difference = None
        matched_recording = False

        for recording in recordings:
            recording_artist_ids = {
                credit.get("artist", {}).get("id")
                for credit in recording.get("artist-credit", [])
                if credit.get("artist", {}).get("id")
            }
            if not artist_ids & recording_artist_ids:
                continue
            if not spotify._title_match(source_name, recording.get("title", "")):
                continue

            disambiguation = recording.get("disambiguation", "")
            if (
                spotify._version_conflicts(
                    source_name,
                    source_album,
                    disambiguation,
                    "",
                )
                or "djmix" in spotify._normalize_text(disambiguation)
            ):
                continue

            matched_recording = True
            duration = spotify._coerce_duration_ms(recording.get("length"))
            difference = (
                abs(duration - candidate_duration)
                if duration and candidate_duration
                else None
            )
            if best_difference is None or (
                difference is not None and difference < best_difference
            ):
                best_difference = difference

        if allow_cross_script_title:
            confirmed = (
                matched_recording
                and best_difference is not None
                and best_difference <= 30000
            )
        else:
            confirmed = matched_recording and (
                best_difference is None or best_difference <= 30000
            )

        print(
            "MB ISRC verification: "
            f"isrc={isrc} duration_diff_ms={best_difference} "
            f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'}"
        )
        return confirmed

    spotify._musicbrainz_recording_identity_accepts = (
        musicbrainz_recording_identity_accepts
    )
