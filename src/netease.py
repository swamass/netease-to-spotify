import os
from http.cookies import SimpleCookie

import requests


NETEASE_DAILY_URL = (
    "https://music.163.com/api/v3/discovery/recommend/songs"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
}


def _get_csrf_token(cookie: str) -> str:
    """
    从网易云 Cookie 中获取 CSRF Token。

    网易云常见的 Cookie 名称有：
    - __csrf
    - csrf_token

    如果 Cookie 中没有，则尝试读取 GitHub Actions
    中单独设置的 NETEASE_CSRF_TOKEN。
    """

    # 1. 优先从环境变量读取
    csrf_token = os.getenv("NETEASE_CSRF_TOKEN", "").strip()

    if csrf_token:
        return csrf_token

    # 2. 从 Cookie 中读取 __csrf / csrf_token
    parsed = SimpleCookie()
    parsed.load(cookie)

    for key in ("__csrf", "csrf_token"):
        if key in parsed:
            value = parsed[key].value.strip()
            if value:
                return value

    raise RuntimeError(
        "Could not find NetEase CSRF token. "
        "Please add NETEASE_CSRF_TOKEN to GitHub Secrets, "
        "or make sure your NETEASE_COOKIE contains __csrf."
    )


def get_daily_recommendations(cookie: str) -> list[dict]:
    """
    获取网易云音乐：

    个性化推荐 → 每日歌曲推荐

    返回：
    [
        {
            "name": "歌曲名",
            "artists": ["歌手1", "歌手2"]
        },
        ...
    ]
    """

    csrf_token = _get_csrf_token(cookie)

    headers = {
        **HEADERS,
        "Cookie": cookie,
    }

    params = {
        "csrf_token": csrf_token,
    }

    print("Getting NetEase daily recommendations...")

    try:
        response = requests.get(
            NETEASE_DAILY_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        response.raise_for_status()

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Failed to request NetEase daily recommendations: {exc}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "NetEase returned an invalid JSON response."
        ) from exc

    if data.get("code") != 200:
        raise RuntimeError(
            f"NetEase API returned code {data.get('code')}: "
            f"{data.get('message', 'unknown error')}"
        )

    songs = data.get("data", {}).get("dailySongs", [])

    if not songs:
        raise RuntimeError(
            "NetEase returned 0 daily recommendations. "
            "The cookie may have expired or the account session "
            "may no longer be valid."
        )

    print(f"Found {len(songs)} NetEase daily recommendations.")

    print("\n===== NetEase Daily Recommendations =====")

    results = []

    for index, song in enumerate(songs, start=1):
        name = song.get("name", "")

        artists = [
            artist.get("name", "")
            for artist in song.get("ar", [])
            if artist.get("name")
        ]

        artist_text = ", ".join(artists)

        print(f"{index:02d}. {name} - {artist_text}")

        results.append(
            {
                "name": name,
                "artists": artists,
            }
        )

    print("==========================================\n")

    return results
