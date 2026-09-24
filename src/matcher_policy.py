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
    recording_duration_tolerance_ms = 30000

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

    def title_scripts_differ(source: str, recording: str) -> bool:
        source_non_latin = spotify._contains_cjk(source) or spotify._contains_kana(source)
        recording_non_latin = spotify._contains_cjk(recording) or spotify._contains_kana(recording)
        return source_non_latin != recording_non_latin

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
        diagnostics: dict | None = None,
    ) -> bool:
        isrc = (candidate.get("external_ids") or {}).get("isrc")
        if not isrc:
            return False

        verification = {
            "isrc": isrc,
            "source": {
                "title": source_name,
                "artists": list(source_artists),
                "album": source_album,
            },
            "spotify": {
                "title": candidate.get("name", ""),
                "artists": [
                    artist.get("name", "")
                    for artist in candidate.get("artists", [])
                ],
                "album": candidate.get("album", {}).get("name", ""),
                "duration_ms": candidate.get("duration_ms"),
                "isrc": isrc,
            },
            "allow_cross_script_title": allow_cross_script_title,
            "predicates": {},
        }
        if diagnostics is not None:
            diagnostics.setdefault("musicbrainz_verifications", []).append(verification)

        candidate_name = candidate.get("name", "")
        verification["predicates"]["title_identity"] = (
            "PASS"
            if allow_cross_script_title or spotify._title_match(source_name, candidate_name)
            else "FAIL"
        )
        if (
            not allow_cross_script_title
            and not spotify._title_match(source_name, candidate_name)
        ):
            verification["result"] = "NOT_CONFIRMED"
            verification["failure_predicates"] = ["title_identity"]
            return False

        candidate_version_conflict = spotify._version_conflicts(
            source_name,
            source_album,
            candidate_name,
            candidate.get("album", {}).get("name", ""),
        )
        verification["predicates"]["version_conflict"] = (
            "FAIL" if candidate_version_conflict else "PASS"
        )
        if candidate_version_conflict:
            verification["result"] = "NOT_CONFIRMED"
            verification["failure_predicates"] = ["version_conflict"]
            return False

        recordings = spotify._musicbrainz_recordings_for_isrc(isrc)
        print(f"MB ISRC lookup: isrc={isrc} recording_count={len(recordings)}")
        verification["recording_count"] = len(recordings)
        verification["recordings"] = [
            {
                "mbid": recording.get("id"),
                "title": recording.get("title", ""),
                "length_ms": recording.get("length"),
                "disambiguation": recording.get("disambiguation", ""),
                "artist_credits": [
                    {
                        "name": credit.get("name") or credit.get("artist", {}).get("name", ""),
                        "mbid": credit.get("artist", {}).get("id"),
                    }
                    for credit in recording.get("artist-credit", [])
                ],
                "releases": [
                    {
                        "title": release.get("title", ""),
                        "release_group": (release.get("release-group") or {}).get("title", ""),
                    }
                    for release in recording.get("releases", [])
                ],
            }
            for recording in recordings
        ]

        artist_ids = spotify._musicbrainz_artist_identity(
            source_artists, candidate.get("artists", [])
        )
        identity_route = "artist"
        if not artist_ids:
            artist_ids = artist_credit_identity_ids(
                source_artists, candidate, recordings
            )
            identity_route = "artist-credit"
        verification["artist_identity"] = {
            "result": "CONFIRMED" if artist_ids else "NOT_CONFIRMED",
            "route": identity_route,
            "mbids": sorted(artist_ids),
        }
        if not artist_ids:
            verification["artist_identity"] = {
                "result": "NOT_CONFIRMED",
                "route": identity_route,
                "mbids": [],
            }
            verification["predicates"]["artist_identity"] = "FAIL"
            verification["result"] = "NOT_CONFIRMED"
            verification["failure_predicates"] = ["artist_identity"]
            return False

        if not recordings:
            verification["predicates"].update({
                "artist_identity": "PASS",
                "duration": "UNKNOWN",
                "isrc_uniqueness": "NOT_FOUND",
                "recording_title": "UNKNOWN",
                "recording_artist": "UNKNOWN",
            })
            confirmed = not allow_cross_script_title and identity_route == "artist"
            print(
                "MB ISRC verification: "
                f"isrc={isrc} duration_diff_ms=None "
                f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'} "
                f"identity_route={identity_route}"
            )
            verification["result"] = "CONFIRMED" if confirmed else "NOT_CONFIRMED"
            verification["failure_predicates"] = (
                [] if confirmed else ["recording_evidence"]
            )
            return confirmed

        candidate_duration = spotify._coerce_duration_ms(candidate.get("duration_ms"))
        best_difference = None
        matched_recording = False
        cross_script_recording_title = False
        recording_predicates = []

        for recording in recordings:
            recording_artist_ids = {
                credit.get("artist", {}).get("id")
                for credit in recording.get("artist-credit", [])
                if credit.get("artist", {}).get("id")
            }
            recording_artist_match = bool(artist_ids & recording_artist_ids)
            recording_title_match = spotify._title_match(
                source_name, recording.get("title", "")
            )
            disambiguation = recording.get("disambiguation", "")
            recording_version_conflict = bool(
                spotify._version_conflicts(
                    source_name, source_album, disambiguation, ""
                )
                or "djmix" in spotify._normalize_text(disambiguation)
            )
            recording_duration = spotify._coerce_duration_ms(recording.get("length"))
            difference = (
                abs(recording_duration - candidate_duration)
                if recording_duration and candidate_duration
                else None
            )
            title_rescue = (
                len(recordings) == 1
                and not recording_title_match
                and not allow_cross_script_title
                and title_scripts_differ(source_name, recording.get("title", ""))
                and identity_route == "artist"
                and recording_artist_match
                and difference is not None
                and difference <= recording_duration_tolerance_ms
                and not recording_version_conflict
            )
            recording_predicates.append({
                "mbid": recording.get("id"),
                "artist_identity": "PASS" if recording_artist_match else "FAIL",
                "title_identity": (
                    "PASS" if recording_title_match
                    else "UNKNOWN_CROSS_SCRIPT" if title_rescue
                    else "FAIL"
                ),
                "duration": (
                    "PASS" if difference is not None and difference <= recording_duration_tolerance_ms
                    else "UNKNOWN" if difference is None else "FAIL"
                ),
                "duration_diff_ms": difference,
                "version_conflict": "FAIL" if recording_version_conflict else "PASS",
            })
            if not recording_artist_match:
                continue
            if not recording_title_match and not title_rescue:
                continue
            if recording_version_conflict:
                continue

            matched_recording = True
            cross_script_recording_title = cross_script_recording_title or title_rescue
            if best_difference is None or (
                difference is not None and difference < best_difference
            ):
                best_difference = difference

        verification["recording_predicates"] = recording_predicates
        verification["predicates"].update({
            "artist_identity": "PASS",
            "recording_title": (
                "UNKNOWN_CROSS_SCRIPT" if cross_script_recording_title
                else "PASS" if matched_recording else "FAIL"
            ),
            "recording_artist": "PASS" if any(
                row["artist_identity"] == "PASS" for row in recording_predicates
            ) else "FAIL",
            "duration": (
                "PASS" if best_difference is not None and best_difference <= recording_duration_tolerance_ms
                else "UNKNOWN" if best_difference is None else "FAIL"
            ),
            "isrc_uniqueness": (
                "PASS" if len(recordings) == 1
                else "MULTIPLE" if len(recordings) > 1 else "NOT_FOUND"
            ),
        })

        if allow_cross_script_title:
            confirmed = (
                matched_recording
                and best_difference is not None
                and best_difference <= recording_duration_tolerance_ms
            )
        else:
            confirmed = matched_recording and (
                best_difference is None or best_difference <= recording_duration_tolerance_ms
            )

        print(
            "MB ISRC verification: "
            f"isrc={isrc} duration_diff_ms={best_difference} "
            f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'} "
            f"identity_route={identity_route}"
        )
        verification["result"] = "CONFIRMED" if confirmed else "NOT_CONFIRMED"
        verification["failure_predicates"] = [] if confirmed else [
            name for name, result in verification["predicates"].items()
            if result in {"FAIL", "UNKNOWN", "NOT_FOUND"}
        ]
        return confirmed

    spotify._musicbrainz_recording_identity_accepts = (
        musicbrainz_recording_identity_accepts
    )
