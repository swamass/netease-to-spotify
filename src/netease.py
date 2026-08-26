import requests


def get_daily_recommendations(cookie: str) -> list[dict]:
    """获取网易云音乐每日推荐歌曲。"""
    response = requests.get(
        "https://music.163.com/api/v3/discovery/recommend/songs",
        headers={
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0",
        },
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("code") != 200:
        raise RuntimeError(
            f"NetEase API returned code {data.get('code')}: "
            f"{data.get('message', 'unknown error')}"
        )

    songs = data.get("data", {}).get("dailySongs", [])

    return [
        {
            "name": song["name"],
            "artists": [artist["name"] for artist in song.get("ar", [])],
        }
        for song in songs
    ]
