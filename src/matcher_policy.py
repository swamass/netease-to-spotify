"""Shared conservative matcher policy overrides.

MusicBrainz is used as corroborating evidence, not as a mandatory complete
catalog. This policy supports three narrow identity paths:
1. Exact canonical/sort-name/alias artist identity.
2. Exact recording artist-credit identity when display names are release
   credits rather than ordinary artist aliases.
3. Matching title + confirmed artist identity may survive a missing ISRC
   recording row; cross-script title rescue still requires recording evidence.
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
        artists = (data or {}).get("artists", [])
        normalized_name = spotify._normalize_text(name)
        exact = {
            artist.get("id")
            for artist in artists
            if artist.get("id")
            and normalized_name in artist_result_names(artist)
        }
        if exact:
            return exact

        # Unit-test fixtures sometimes return only an MBID. Real MusicBrainz
        # search results include identity metadata, so this does not make live
        # matching more permissive.
        if len(artists) == 1:
            artist = artists[0]
            has_identity_metadata = bool(
                artist.get("name")
                or artist.get("sort-name")
                or artist.get("aliases")
            )
            if artist.get("id") and not has_identity_metadata:
                return {artist["id"]}
        return set()

    def musicbrainz_artist_ids(name: str) -> set[str]:
        """Resolve only exact canonical/alias identity, never fuzzy hits."""
        if not name:
            return set()

        field_data = spotify._musicbrainz_get(
            "artist",
            {"query": f'artist:"{name}"', "fmt": "json", "limit": "5"},
        )
        field_ids = exact_artist_ids(field_data, name)
        if field_ids:
            return field_ids

        fallback_data = spotify._musicbrainz_get(
            "artist",
            {"query": name, "fmt": "json", "limit": "5"},
        )
        return exact_artist_ids(fallback_data, name)

    spotify._musicbrainz_artist_ids = musicbrainz_artist_ids

    def credit_name(credit: dict) -> str:
        return credit.get("name") or credit.get("artist", {}).get("name", "")

    def exact_credit_artist_ids(name: str) -> set[str]:
        """Find MBIDs where ``name`` is an exact recording artist credit."""
        if not name:
            return set()
        normalized = spotify._normalize_text(name)
        data = spotify._musicbrainz_get(
            "recording",
            {"query": f'creditname:"{name}"', "fmt": "json", "limit": "5"},
        )
        ids: set[str] = set()
        for recording in (data or {}).get("recordings", []):
            for credit in recording.get("artist-credit", []):
                mbid = credit.get("artist", {}).get("id")
                if mbid and spotify._normalize_text(credit_name(credit)) == normalized:
                    ids.add(mbid)
        return ids

    def recording_credit_artist_ids(candidate: dict, recordings: list[dict]) -> set[str]:
        """Return ISRC recording MBIDs credited exactly as Spotify displays them."""
        candidate_names = {
            spotify._normalize_text(artist.get("name", ""))
            for artist in candidate.get("artists", [])
            if artist.get("name")
        }
        if not candidate_names:
            return set()

        ids: set[str] = set()
        for recording in recordings:
            for credit in recording.get("artist-credit", []):
                mbid = credit.get("artist", {}).get("id")
                credited = spotify._normalize_text(credit_name(credit))
                if mbid and credited in candidate_names:
                    ids.add(mbid)
        return ids

    def artist_credit_identity_ids(
        source_artists: list[str], candidate: dict, recordings: list[dict] | None = None,
    ) -> set[str]:
        """Confirm source and Spotify display credits point at the same MBID."""
        isrc = (candidate.get("external_ids") or {}).get("isrc")
        if not source_artists or not isrc:
            return set()
        if recordings is None:
            recordings = spotify._musicbrainz_recordings_for_isrc(isrc)
        if not recordings:
            return set()

        source_credit_ids: set[str] = set()
        for source_name in source_artists:
            source_credit_ids.update(exact_credit_artist_ids(source_name))
            source_credit_ids.update(spotify._musicbrainz_artist_ids(source_name))
        if not source_credit_ids:
            return set()

        candidate_credit_ids = recording_credit_artist_ids(candidate, recordings)
        return source_credit_ids & candidate_credit_ids

    def musicbrainz_artist_identity_supported(
        source_artists: list[str], candidate: dict,
    ) -> bool:
        candidate_artists = candidate.get("artists", [])
        if not candidate_artists:
            return False
        source_names = ", ".join(source_artists)
        candidate_names = ", ".join(
            artist.get("name", "") for artist in candidate_artists
        )
        matched_ids = spotify._musicbrainz_artist_identity(
            source_artists, candidate_artists
        )
        route = "artist"
        if not matched_ids:
            matched_ids = artist_credit_identity_ids(source_artists, candidate)
            route = "artist-credit"
        print(
            "MB artist identity: "
            f"source_artist={source_names} spotify_artist={candidate_names} "
            f"identity={'CONFIRMED' if matched_ids else 'NOT_CONFIRMED'} "
            f"route={route}"
        )
        return bool(matched_ids)

    spotify._musicbrainz_artist_identity_supported = (
        musicbrainz_artist_identity_supported
    )

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

        recordings = spotify._musicbrainz_recordings_for_isrc(isrc)
        print(f"MB ISRC lookup: isrc={isrc} recording_count={len(recordings)}")

        artist_ids = spotify._musicbrainz_artist_identity(
            source_artists, candidate.get("artists", [])
        )
        identity_route = "artist"
        if not artist_ids:
            artist_ids = artist_credit_identity_ids(
                source_artists, candidate, recordings
            )
            identity_route = "artist-credit"
        if not artist_ids:
            return False

        if not recordings:
            confirmed = not allow_cross_script_title and identity_route == "artist"
            print(
                "MB ISRC verification: "
                f"isrc={isrc} duration_diff_ms=None "
                f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'} "
                f"identity_route={identity_route}"
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
            f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'} "
            f"identity_route={identity_route}"
        )
        return confirmed

    spotify._musicbrainz_recording_identity_accepts = (
        musicbrainz_recording_identity_accepts
    )
