python
import base64
import json
import os
import random
import string

import requests
from Crypto.Cipher import AES


WEAPI_URL = "https://music.163.com/weapi/v2/discovery/recommend/songs"

IV = b"0102030405060708"
PRESET_KEY = b"0CoJUm6Qyw8W8jud"

PUB_KEY = 0x10001

MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb"
    "7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf69528"
    "0104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee25593"
    "2575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935"
    "b3ece0462db0a22b8e7"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
    "Content-Type": "application/x-www-form-urlencoded",
}


def _pkcs7_pad(data: bytes) -> bytes:
    padding = 16 - len(data) % 16
    return data + bytes([padding]) * padding


def _aes_encrypt(data: bytes, key: bytes) -> str:
    cipher = AES.new(key, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(_pkcs7_pad(data))
    return base64.b64encode(encrypted).decode("utf-8")


def _random_secret_key() -> bytes:
    chars = string.ascii_letters + string.digits
    return "".join(
        random.choice(chars)
        for _ in range(16)
    ).encode("utf-8")


def _rsa_encrypt(secret_key: bytes) -> str:
    text = int.from_bytes(
        secret_key[::-1],
        byteorder="big",
    )

    modulus = int(MODULUS, 16)

    encrypted = pow(
        text,
        PUB_KEY,
        modulus,
    )

    return format(
        encrypted,
        "x",
    ).zfill(256)


def _weapi_encrypt(payload: dict) -> dict:
    text = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    secret_key = _random_secret_key()

    first_encrypt = _aes_encrypt(
        text,
        PRESET_KEY,
    )

    params = _aes_encrypt(
        first_encrypt.encode("utf-8"),
        secret_key,
    )

    enc_sec_key = _rsa_encrypt(secret_key)

    return {
        "params": params,
        "encSecKey": enc_sec_key,
    }


def _get_csrf_token() -> str:
    csrf_token = os.getenv(
        "NETEASE_CSRF_TOKEN",
        "",
    ).strip()

    if not csrf_token:
        raise RuntimeError(
            "NETEASE_CSRF_TOKEN is missing. "
            "Please add it to GitHub Secrets."
        )

    return csrf_token


def get_daily_recommendations(cookie: str) -> list[dict]:
    """
    获取网易云音乐：
    个性化推荐 → 每日歌曲推荐
    """

    csrf_token = _get_csrf_token()

    payload = {
        "offset": "0",
        "total": "true",
        "limit": "30",
        "csrf_token": csrf_token,
    }

    encrypted = _weapi_encrypt(payload)

    headers = {
        **HEADERS,
        "Cookie": cookie,
    }

    print("Getting NetEase daily recommendations...")

    try:
        response = requests.post(
            f"{WEAPI_URL}?csrf_token={csrf_token}",
            headers=headers,
            data=encrypted,
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

    songs = (
        data.get("data", {})
        .get("dailySongs", [])
    )

    if not songs:
        raise RuntimeError(
            "NetEase returned 0 daily recommendations. "
            "The NetEase cookie or CSRF token may be expired."
        )

    print(
        f"Found {len(songs)} NetEase daily recommendations."
    )

    print("\n===== NetEase Daily Recommendations =====")

    results = []

    for index, song in enumerate(
        songs,
        start=1,
    ):
        name = song.get(
            "name",
            "",
        )

        artists = [
            artist.get(
                "name",
                "",
            )
            for artist in song.get(
                "ar",
                [],
            )
            if artist.get("name")
        ]

        artist_text = ", ".join(artists)

        print(
            f"{index:02d}. "
            f"{name} - "
            f"{artist_text}"
        )

        results.append(
            {
                "name": name,
                "artists": artists,
            }
        )

    print(
        "==========================================\n"
    )

    return results

