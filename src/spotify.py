import base64
import difflib
import re
import time
import unicodedata
from typing import Any

import requests

from . import cjk_title_keys


def _load_cjk_converter():
    try:
        from opencc import OpenCC

        return OpenCC("s2t").convert
    except Exception:
        return None


_cjk_converter = _load_cjk_converter()


SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_URL = "https://api.spotify.com/v1"

MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 10]
MAX_RETRY_AFTER_SECONDS = 15
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_USER_AGENT = "netease-to-spotify/identity-fallback-v1"
MUSICBRAINZ_REQUEST_INTERVAL = 1.1

_musicbrainz_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
_musicbrainz_last_request = 0.0


class SpotifyRateLimitError(RuntimeError):
    """Raised when Spotify asks the whole sync to stop waiting."""


def get_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    """Use the refresh token to get a new Spotify access token."""
    credentials = f"{client_id}:{client_secret}".encode()
    encoded_credentials = base64.b64encode(credentials).decode()

    response = requests.post(
        SPOTIFY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {encoded_credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    print("Spotify token scopes:", data.get("scope"))

    if "access_token" not in data:
        raise RuntimeError("Spotify did not return an access token.")

    return data["access_token"]


def _spotify_get(
    url: str,
    access_token: str,
    params: dict,
) -> requests.Response | None:
    """Make a Spotify GET request with retries for temporary errors."""
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                },
                params=params,
                timeout=30,
            )

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "5")

                try:
                    wait_seconds = int(retry_after)
                except ValueError:
                    wait_seconds = 5

                print(
                    f"Spotify rate limit reached. Retry-After={wait_seconds}s."
                )
                if wait_seconds > MAX_RETRY_AFTER_SECONDS:
                    print(
                        f"Retry-After exceeds {MAX_RETRY_AFTER_SECONDS}s; "
                        "aborting all Spotify searches."
                    )
                    raise SpotifyRateLimitError(
                        "Spotify rate limit detected; aborting sync to protect "
                        "existing playlist."
                    )

                time.sleep(wait_seconds)
                continue

            if response.status_code in (502, 503, 504):
                if attempt < MAX_RETRIES - 1:
                    wait_seconds = RETRY_DELAYS[attempt]
                    print(
                        f"Spotify returned {response.status_code}. "
                        f"Retrying in {wait_seconds} seconds..."
                    )
                    time.sleep(wait_seconds)
                    continue

                print(
                    f"Spotify returned {response.status_code} "
                    f"after {MAX_RETRIES} attempts."
                )
                return None

            response.raise_for_status()
            return response

        except requests.RequestException as error:
            if attempt < MAX_RETRIES - 1:
                wait_seconds = RETRY_DELAYS[attempt]
                print(
                    f"Spotify request failed: {error}. "
                    f"Retrying in {wait_seconds} seconds..."
                )
                time.sleep(wait_seconds)
                continue

            print(
                f"Spotify request failed after "
                f"{MAX_RETRIES} attempts: {error}"
            )
            return None

    return None


def _normalize_text(value: str) -> str:
    """Normalize text while ignoring punctuation and presentation differences."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.replace("&", "and")
    normalized = normalized.translate(str.maketrans({"间": "間"}))
    return "".join(character for character in normalized if character.isalnum())


ARTIST_ALIASES = {
    "久石譲": ["Joe Hisaishi"],
    "山下達郎": ["Tatsuro Yamashita"],
    "竹内まりや": ["Mariya Takeuchi"],
    "清塚信也": ["Shinya Kiyozuka"],
    "NAOTO": ["Naoto"],
    "CAGNET": ["Cagnet"],
    "藤井風": ["Fujii Kaze"],
    "吉田美奈子": ["Minako Yoshida"],
    "ブレッド&バター": ["Bread And Butter"],
    "林ゆうき": ["Yuki Hayashi"],
    "宇多田ヒカル": ["Hikaru Utada"],
    "ラ・ムー": ["RA MU"],
    "村田和人": ["Kazuhito Murata"],
    "中原めいこ": ["Meiko Nakahara"],
    "松下誠": ["Makoto Matsushita"],
    "福原美穂": ["Miho Fukuhara"],
}

TITLE_ALIASES = {
    "マイ・ベイビー・クイーン": ["My Baby Queen"],
    "トゥルー・トゥ・ユア・ハート(キャグネット)": [
        "True to Your Heart",
        "True to Your Heart (From Mulan)",
    ],
    "Just My Imagination": ["Just My Imagination (Running Away with Me)"],
}

SAFE_VERSION_TERMS = {
    "remaster", "remastered", "reissue", "rerelease", "deluxeedition",
    "expandededition", "anniversaryedition", "specialedition",
}
HARD_VERSION_TERMS = {
    "live", "remix", "remixed", "acoustic", "instrumental", "demo",
    "radioedit", "extendedmix", "djversion", "djmixed", "speedup", "slowed",
}
INVALID_RELEASE_TERMS = {"tribute", "cover", "karaoke"}


def _version_terms(value: str) -> set[str]:
    normalized = _normalize_text(value)
    terms = set()
    for term in SAFE_VERSION_TERMS | HARD_VERSION_TERMS | INVALID_RELEASE_TERMS:
        if term in normalized:
            terms.add(term)
    return terms


def _title_core(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(
        r"\s*\((?:with|feat\.?|featuring)\b[^)]*\)",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*-?\s*\[(?:from)\s+[^\]]+\]\s*$",
        "",
        normalized,
    )
    normalized = re.sub(
        r'\s*-\s*from\s+["“”][^"“”]+["“”]\s*$',
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*-\s*(?:\d{4}\s+)?remaster(?:ed)?\s*$",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\s*\((?:\d{4}\s+)?remaster(?:ed)?\)\s*$",
        "",
        normalized,
    )
    return normalized.strip()

def _title_keys(value: str) -> set[str]:
    core = _title_core(value)
    keys = {_normalize_text(core)}
    subtitle_removed = re.sub(r"\s*\([^)]*\)\s*$", "", core).strip()
    if subtitle_removed != core:
        keys.add(_normalize_text(subtitle_removed))
    return {key for key in keys if key}


def _title_match(source: str, candidate: str) -> bool:
    source_keys = set()
    for variant in _title_variants(source):
        source_keys.update(_title_keys(variant))
    candidate_keys = _title_keys(candidate)
    for source_key in source_keys:
        for candidate_key in candidate_keys:
            if source_key == candidate_key:
                return True
            distance = abs(len(source_key) - len(candidate_key))
            ratio = difflib.SequenceMatcher(None, source_key, candidate_key).ratio()
            if distance <= 3 and ratio >= 0.92:
                return True
    return False


def _cjk_title_status(source: str, candidate: str) -> str:
    return cjk_title_keys.title_status(source, candidate, _cjk_converter)


def _title_variants(name: str) -> list[str]:
    return list(dict.fromkeys([name, *TITLE_ALIASES.get(name, [])]))


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in value)


def _contains_kana(value: str) -> bool:
    return any(
        "\u3040" <= character <= "\u30ff"
        for character in value
    )


def _artist_match_score(
    source_artists: list[str],
    spotify_artists: list[dict],
) -> tuple[float, int, bool]:
    source_names = set()
    for source_artist in source_artists:
        source_names.add(_normalize_text(source_artist))
        source_names.update(
            _normalize_text(alias)
            for alias in ARTIST_ALIASES.get(source_artist, [])
        )

    spotify_values = [
        artist.get("name", "")
        for artist in spotify_artists
        if artist.get("name")
    ]
    spotify_names = {_normalize_text(value) for value in spotify_values}
    exact_matches = source_names & spotify_names
    if exact_matches:
        return 1.0, len(exact_matches), True

    for source_artist in source_artists:
        source_key = _normalize_text(source_artist)
        for spotify_name in spotify_names:
            if source_key and (
                source_key in spotify_name or spotify_name in source_key
            ):
                return 0.8, 1, True

    source_has_asian = any(
        _contains_cjk(value) or _contains_kana(value)
        for value in source_artists
    )
    spotify_has_asian = any(
        _contains_cjk(value) or _contains_kana(value)
        for value in spotify_values
    )
    if source_has_asian != spotify_has_asian or (
        source_has_asian and spotify_has_asian
    ):
        return 0.35, 0, False

    return 0.0, 0, False


def _artist_matches(
    source_artists: list[str],
    spotify_artists: list[dict],
) -> tuple[bool, int]:
    score, count, reliable = _artist_match_score(
        source_artists, spotify_artists
    )
    return score > 0, count


def _musicbrainz_get(path: str, params: dict[str, str]) -> dict[str, Any] | None:
    """Read MusicBrainz conservatively; failures never affect the sync."""
    global _musicbrainz_last_request
    cache_key = (path, "&".join(f"{key}={params[key]}" for key in sorted(params)))
    if cache_key in _musicbrainz_cache:
        print(f"MusicBrainz lookup: path={path} cache_hit=yes")
        return _musicbrainz_cache[cache_key]
    wait = MUSICBRAINZ_REQUEST_INTERVAL - (time.monotonic() - _musicbrainz_last_request)
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        try:
            response = requests.get(
                f"{MUSICBRAINZ_URL}/{path.lstrip('/')}",
                params=params,
                headers={"User-Agent": MUSICBRAINZ_USER_AGENT, "Accept": "application/json"},
                timeout=30,
            )
            _musicbrainz_last_request = time.monotonic()
            if response.status_code >= 500:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                _musicbrainz_cache[cache_key] = None
                print(f"MusicBrainz lookup: path={path} result=UNAVAILABLE cache_hit=no")
                return None
            if response.status_code == 404:
                _musicbrainz_cache[cache_key] = None
                print(f"MusicBrainz lookup: path={path} result=NOT_FOUND cache_hit=no")
                return None
            response.raise_for_status()
            result = response.json()
            _musicbrainz_cache[cache_key] = result
            print(f"MusicBrainz lookup: path={path} result=FOUND cache_hit=no")
            return result
        except (requests.RequestException, ValueError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            _musicbrainz_cache[cache_key] = None
            print(f"MusicBrainz lookup: path={path} result=UNAVAILABLE cache_hit=no")
            return None
    return None


def _musicbrainz_artist_ids(name: str) -> set[str]:
    if not name:
        return set()
    data = _musicbrainz_get(
        "artist",
        {"query": f'artist:"{name}"', "fmt": "json", "limit": "5"},
    )
    return {
        artist.get("id")
        for artist in (data or {}).get("artists", [])
        if artist.get("id")
    }


def _musicbrainz_artist_names(mbid: str) -> set[str]:
    data = _musicbrainz_get(
        f"artist/{mbid}",
        {"fmt": "json", "inc": "aliases"},
    )
    if not data:
        return set()
    names = {data.get("name", ""), data.get("sort-name", "")}
    names.update(alias.get("name", "") for alias in data.get("aliases", []))
    return {_normalize_text(name) for name in names if name}


def _musicbrainz_artist_identity(
    source_artists: list[str], spotify_artists: list[dict],
) -> set[str]:
    if not source_artists or not spotify_artists:
        return set()
    primary_source = source_artists[0]
    source_ids = _musicbrainz_artist_ids(primary_source)
    spotify_names = [artist.get("name", "") for artist in spotify_artists if artist.get("name")]
    spotify_ids_by_name = {name: _musicbrainz_artist_ids(name) for name in spotify_names}
    spotify_ids = set().union(*(ids for ids in spotify_ids_by_name.values()))
    direct_matches = source_ids & spotify_ids
    if direct_matches:
        return direct_matches

    source_name = _normalize_text(primary_source)
    confirmed = set()
    for mbid in source_ids:
        source_aliases = _musicbrainz_artist_names(mbid) or set()
        if any(_normalize_text(name) in source_aliases for name in spotify_names):
            confirmed.add(mbid)
    for spotify_name, candidate_ids in spotify_ids_by_name.items():
        for mbid in candidate_ids:
            candidate_aliases = _musicbrainz_artist_names(mbid) or set()
            if source_name in candidate_aliases:
                confirmed.add(mbid)
    return confirmed


def _musicbrainz_recordings_for_isrc(isrc: str) -> list[dict[str, Any]]:
    if not isrc:
        return []
    data = _musicbrainz_get(f"isrc/{isrc}", {"fmt": "json"})
    detailed = []
    for recording in (data or {}).get("recordings", []):
        mbid = recording.get("id")
        if not mbid:
            continue
        detail = _musicbrainz_get(
            f"recording/{mbid}",
            {"fmt": "json", "inc": "artist-credits+releases+isrcs"},
        )
        if detail:
            detailed.append(detail)
    return detailed


def _musicbrainz_artist_identity_supported(
    source_artists: list[str], candidate: dict,
) -> bool:
    candidate_artists = candidate.get("artists", [])
    if not candidate_artists:
        return False
    source_names = ", ".join(source_artists)
    candidate_names = ", ".join(
        artist.get("name", "") for artist in candidate_artists
    )
    matched_ids = _musicbrainz_artist_identity(source_artists, candidate_artists)
    print(
        "MB artist identity: "
        f"source_artist={source_names} spotify_artist={candidate_names} "
        f"identity={'CONFIRMED' if matched_ids else 'NOT_CONFIRMED'}"
    )
    return bool(matched_ids)


def _musicbrainz_recording_identity_accepts(
    source_name: str,
    source_artists: list[str],
    source_album: str,
    candidate: dict,
) -> bool:
    """Return true only for strong identity evidence; otherwise fail open."""
    isrc = (candidate.get("external_ids") or {}).get("isrc")
    if not isrc:
        return False
    if not _title_match(source_name, candidate.get("name", "")):
        return False
    if _version_conflicts(
        source_name, source_album, candidate.get("name", ""),
        candidate.get("album", {}).get("name", ""),
    ):
        return False
    artist_ids = _musicbrainz_artist_identity(
        source_artists, candidate.get("artists", [])
    )
    if not artist_ids:
        return False
    recordings = _musicbrainz_recordings_for_isrc(isrc)
    print(f"MB ISRC lookup: isrc={isrc} recording_count={len(recordings)}")
    if not recordings:
        return False
    candidate_duration = _coerce_duration_ms(candidate.get("duration_ms"))
    best_difference = None
    for recording in recordings:
        recording_artist_ids = {
            credit.get("artist", {}).get("id")
            for credit in recording.get("artist-credit", [])
            if credit.get("artist", {}).get("id")
        }
        if not artist_ids & recording_artist_ids:
            continue
        if not _title_match(source_name, recording.get("title", "")):
            continue
        if _version_conflicts(source_name, source_album, recording.get("disambiguation", ""), ""):
            continue
        duration = _coerce_duration_ms(recording.get("length"))
        difference = abs(duration - candidate_duration) if duration and candidate_duration else None
        if best_difference is None or (difference is not None and difference < best_difference):
            best_difference = difference
    confirmed = best_difference is None or best_difference <= 30000
    print(
        "MB ISRC verification: "
        f"isrc={isrc} duration_diff_ms={best_difference} "
        f"result={'CONFIRMED' if confirmed else 'NOT_CONFIRMED'}"
    )
    return confirmed


def _coerce_duration_ms(value) -> int | None:
    try:
        duration_ms = int(value)
    except (TypeError, ValueError):
        return None
    return duration_ms if duration_ms > 0 else None


def _duration_score(source_duration_ms: int | None, spotify_duration_ms: int | None) -> int:
    source_duration_ms = _coerce_duration_ms(source_duration_ms)
    spotify_duration_ms = _coerce_duration_ms(spotify_duration_ms)
    if not source_duration_ms or not spotify_duration_ms:
        return 0
    difference = abs(source_duration_ms - spotify_duration_ms)
    if difference <= 3000:
        return 50
    if difference <= 8000:
        return 40
    if difference <= 15000:
        return 25
    if difference <= 30000:
        return 10
    return 0


def _album_score(source_album: str, spotify_album: str) -> int:
    if not source_album or not spotify_album:
        return 0
    source = _normalize_text(source_album)
    candidate = _normalize_text(spotify_album)
    if source == candidate:
        return 60
    if source in candidate or candidate in source:
        return 45
    source_words = set(re.findall(r"[a-z0-9]+", source))
    candidate_words = set(re.findall(r"[a-z0-9]+", candidate))
    overlap = len(source_words & candidate_words)
    if overlap:
        return 30
    return 10


def _release_has_invalid_terms(name: str, album: str) -> bool:
    return bool(_version_terms(name) | _version_terms(album) & INVALID_RELEASE_TERMS)


def _version_conflicts(source_name: str, source_album: str,
                       candidate_name: str, candidate_album: str) -> list[str]:
    source_terms = _version_terms(source_name) | _version_terms(source_album)
    candidate_terms = _version_terms(candidate_name) | _version_terms(candidate_album)
    reasons = []
    if candidate_terms & INVALID_RELEASE_TERMS:
        reasons.append("tribute/cover/karaoke release")
    for term in HARD_VERSION_TERMS:
        if (term in source_terms) != (term in candidate_terms):
            reasons.append(f"{term} version mismatch")
    return reasons


def _baseline_artist_acceptable(
    artist_score: float,
    artist_reliable: bool,
    title_exact: bool,
    album_points: int,
) -> bool:
    return artist_score > 0 and (
        artist_reliable or (title_exact and album_points >= 45)
    )


def _musicbrainz_fallback_eligible(
    baseline_accept: bool,
    artist_score: float,
    artist_reliable: bool,
    title_matches: bool,
    version_reasons: list[str],
) -> bool:
    return (
        not baseline_accept
        and artist_score == 0.35
        and not artist_reliable
        and title_matches
        and not version_reasons
    )


def search_track(
    access_token: str,
    name: str,
    artists: list[str],
    album: str = "",
    duration_ms: int | None = None,
) -> str | None:
    """Find the most reliable candidate using two bounded searches."""
    if not name or not artists:
        print(f"Not found: {name} - missing artist metadata")
        return None

    artist = artists[0]
    queries = [
        f'track:"{name}" artist:"{artist}"'
        + (f' album:"{album}"' if album else ""),
        f"{name} {artist}".strip(),
    ]
    candidates = {}
    requests_sent = 0

    for query_index, query in enumerate(queries, start=1):
        print(f"Spotify search query {query_index}/2: {query}")
        requests_sent += 1
        response = _spotify_get(
            f"{SPOTIFY_API_URL}/search",
            access_token,
            {"q": query, "type": "track", "limit": 10},
        )
        if response is None:
            print(f"Search request {requests_sent} skipped or failed.")
            continue

        items = response.json().get("tracks", {}).get("items", [])
        print(f"Search result: {len(items)} candidates")
        for item in items:
            item_id = item.get("id")
            item_name = item.get("name", "")
            item_artists = item.get("artists", [])
            item_album_name = item.get("album", {}).get("name", "")
            reasons = []

            if not item_id:
                reasons.append("missing track ID")
            title_matches = _title_match(name, item_name)
            if not title_matches:
                source_release_terms = _version_terms(album)
                candidate_release_terms = _version_terms(item_album_name)
                live_is_confirmed = (
                    "live" in source_release_terms
                    and "live" in candidate_release_terms
                )
                if live_is_confirmed:
                    title_without_live = re.sub(
                        r"\s*-\s*live(?:\s+version)?\s*$",
                        "",
                        item_name,
                        flags=re.IGNORECASE,
                    )
                    title_matches = _title_match(name, title_without_live)
            if not title_matches:
                reasons.append("title mismatch")
            artist_score, artist_count, artist_reliable = _artist_match_score(
                artists, item_artists
            )
            album_points = _album_score(album, item_album_name)
            duration_points = _duration_score(
                duration_ms, item.get("duration_ms")
            )
            title_exact = _normalize_text(_title_core(name)) in _title_keys(item_name)
            version_reasons = _version_conflicts(
                name, album, item_name, item_album_name
            )
            cjk_status = cjk_title_keys.NO_MATCH
            if not title_matches and not version_reasons:
                cjk_status = _cjk_title_status(name, item_name)
                if cjk_status == cjk_title_keys.CJK_EQUIVALENT:
                    title_matches = True
                    reasons = [reason for reason in reasons if reason != "title mismatch"]
                    print("CJK auxiliary title status: CJK_EQUIVALENT")
            identity_verified = False
            baseline_artist_acceptable = _baseline_artist_acceptable(
                artist_score, artist_reliable, title_exact, album_points
            )
            baseline_accept = (
                title_matches and not version_reasons and baseline_artist_acceptable
            )
            spotify_isrc = (item.get("external_ids") or {}).get("isrc")
            print(
                "MusicBrainz fallback: "
                f"track={item_name} source_artist={', '.join(artists)} "
                f"spotify_artist={', '.join(value.get('name', '') for value in item_artists)} "
                f"baseline={'ACCEPT' if baseline_accept else 'REJECT'} "
                f"spotify_isrc={spotify_isrc or 'NONE'}"
            )
            if baseline_accept:
                print("SKIP: baseline already accepted")
            elif not title_matches:
                print("SKIP: title conflict")
            elif version_reasons:
                print("SKIP: version conflict")
            elif artist_score == 0:
                print("SKIP: artist mismatch is hard reject")
            elif artist_score != 0.35 or artist_reliable:
                print("SKIP: not a cross-language uncertainty")
            else:
                print(
                    "MusicBrainz fallback: fallback_eligible=yes "
                    f"reason=cross-language artist uncertainty "
                    f"spotify_isrc={spotify_isrc or 'NONE'}"
                )
            if _musicbrainz_fallback_eligible(
                baseline_accept,
                artist_score,
                artist_reliable,
                title_matches,
                version_reasons,
            ):
                artist_identity_supported = _musicbrainz_artist_identity_supported(
                    artists, item
                )
                if artist_identity_supported:
                    print(
                        "MusicBrainz artist identity supported candidate: "
                        f"{item_name} - {item_album_name}"
                    )
                    if (item.get("external_ids") or {}).get("isrc"):
                        identity_verified = _musicbrainz_recording_identity_accepts(
                            name, artists, album, item
                        )
                        print(
                            "MusicBrainz ISRC recording verification: "
                            f"{'passed' if identity_verified else 'not confirmed'}"
                        )
                    else:
                        identity_verified = title_exact and (
                            album_points >= 45 or duration_points >= 40
                        )
            if artist_score == 0:
                reasons.append("artist mismatch")
            elif not artist_reliable and not identity_verified and not (
                title_exact and album_points >= 45
            ):
                reasons.append("artist not sufficiently corroborated")
            reasons.extend(version_reasons)

            if reasons:
                print(
                    f"Rejected candidate: {item_name} - "
                    f"{', '.join(value.get('name', '') for value in item_artists)} - "
                    f"{item_album_name} ({', '.join(dict.fromkeys(reasons))})"
                )
                continue

            title_points = 300 if title_exact else 276
            version_points = 100
            additional_artist_penalty = 0
            if (
                len(artists) == 1
                and len(item_artists) > 1
                and album_points < 45
            ):
                additional_artist_penalty = 100
                print(
                    "Applied conservative additional-artist penalty: "
                    f"{additional_artist_penalty}"
                )

            score = (
                title_points
                + 500 * artist_score
                + album_points
                + duration_points
                + version_points
                - additional_artist_penalty
            )
            print(
                f"Candidate score: title={title_points}, "
                f"artist={artist_score:.2f}, album={album_points}, "
                f"duration={duration_points}, version={version_points}, "
                f"total={score}"
            )
            candidates[item_id] = max(
                candidates.get(item_id, (0, item)),
                (score, item),
                key=lambda value: value[0],
            )

        if candidates:
            break

    print(f"Spotify search requests sent: {requests_sent}")
    if not candidates:
        print(f"Not found: {name} - no sufficiently reliable candidate")
        return None

    score, item = max(candidates.values(), key=lambda value: value[0])
    item_artists = ", ".join(
        value.get("name", "") for value in item.get("artists", [])
    )
    album_points = _album_score(album, item.get("album", {}).get("name", ""))
    print(
        f"Matched candidate: {item.get('name', '')} - {item_artists} - "
        f"{item.get('album', {}).get('name', '')}; "
        f"Match reason: artist + title"
        + (" + album" if album_points >= 45 else "")
        + f"; score={score}"
    )
    return item.get("id")

def replace_playlist_tracks(
    access_token: str,
    playlist_id: str,
) -> None:
    """Remove all existing tracks using Spotify's playlist replace endpoint."""
    response = requests.put(
        f"{SPOTIFY_API_URL}/playlists/{playlist_id}/items",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json={"uris": []},
        timeout=30,
    )

    print("Spotify playlist clear status:", response.status_code)
    response.raise_for_status()

    print("Cleared existing Spotify playlist tracks.")

def add_tracks_to_playlist(
    access_token: str,
    playlist_id: str,
    track_ids: list[str],
) -> None:
    """Add all tracks to a Spotify playlist in batches of 100."""

    if not track_ids:
        print("No tracks to add.")
        return

    uris = [
        f"spotify:track:{track_id}"
        for track_id in track_ids
    ]

    for start in range(0, len(uris), 100):
        batch = uris[start : start + 100]

        print(
            f"Trying to add {len(batch)} tracks "
            f"to Spotify playlist..."
        )

        response = requests.post(
            f"{SPOTIFY_API_URL}/playlists/{playlist_id}/items",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "uris": batch,
            },
            timeout=30,
        )

        print("Spotify response status:", response.status_code)
        print("Spotify response body:", response.text)

        if response.status_code != 201:
            print("Spotify response headers:", dict(response.headers))

        response.raise_for_status()

        print(
            f"Successfully added {len(batch)} tracks."
        )
