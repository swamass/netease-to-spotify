import requests


def get_daily_recommendations(cookie: str) -> list[dict]:
    """获取网易云音乐「个性化推荐 → 每日歌曲推荐」并打印结果。"""
    response = requests.get(
        "https://music.163.com/api/v3/discovery/recommend/songs",
        headers={
            "Cookie": cookie,
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://music.163.com/",
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

    print("\n===== NetEase Daily Recommendations =====")

    for index, song in enumerate(songs, start=1):
        name = song.get("name", "")
        artists = ", ".join(
            artist.get("name", "")
            for artist in song.get("ar", [])
        )

        print(f"{index:02d}. {name} - {artists}")

    print("==========================================\n")

    return [
        {
            "name": song["name"],
            "artists": [
                artist["name"]
                for artist in song.get("ar", [])
            ],
        }
        for song in songs
    ]
