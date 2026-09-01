import json
import re

from src.config import load_settings
from src.netease import get_daily_recommendations
from src.spotify import SpotifyRateLimitError, get_access_token, search_track


def _is_japanese(value: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value))


def main() -> None:
    settings = load_settings()
    songs = get_daily_recommendations(settings.netease_cookie)
    if not songs:
        raise RuntimeError("NetEase returned no recommendations.")

    access_token = get_access_token(
        settings.spotify_client_id,
        settings.spotify_client_secret,
        settings.spotify_refresh_token,
    )

    results = []
    matched = 0
    japanese_total = 0
    japanese_matched = 0

    for song in songs:
        japanese = _is_japanese(song["name"]) or any(
            _is_japanese(artist) for artist in song["artists"]
        )
        japanese_total += int(japanese)
        try:
            track_id = search_track(
                access_token,
                song["name"],
                song["artists"],
                song.get("album", ""),
                duration_ms=song.get("duration_ms"),
            )
        except SpotifyRateLimitError:
            raise

        if track_id:
            matched += 1
            japanese_matched += int(japanese)

        results.append({
            "netease": song,
            "matched": bool(track_id),
            "spotify_track_id": track_id,
        })

    total = len(songs)
    report = {
        "total": total,
        "matched": matched,
        "unmatched": total - matched,
        "match_rate": matched / total if total else 0,
        "japanese_total": japanese_total,
        "japanese_matched": japanese_matched,
        "japanese_unmatched": japanese_total - japanese_matched,
        "japanese_match_rate": (
            japanese_matched / japanese_total if japanese_total else 0
        ),
        "results": results,
    }
    with open("match_report.json", "w", encoding="utf-8") as report_file:
        json.dump(report, report_file, ensure_ascii=False, indent=2)

    print("\n===== DRY RUN SUMMARY =====")
    print(json.dumps({key: report[key] for key in (
        "total", "matched", "unmatched", "match_rate",
        "japanese_total", "japanese_matched", "japanese_unmatched",
        "japanese_match_rate",
    )}, ensure_ascii=False, indent=2))
    print("Playlist writes: SKIPPED")


if __name__ == "__main__":
    main()
