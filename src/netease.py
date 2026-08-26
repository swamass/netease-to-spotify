import base64
import binascii
import json
import os
import re

import requests
from Crypto.Cipher import AES


WEAPI_URL = "https://music.163.com/weapi/v2/discovery/recommend/songs"

PRESET_KEY = b"0CoJUm6Qyw8W8jud"
IV = b"0102030405060708"
PUB_KEY = "010001"

MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
    "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
    "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
    "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
    "3ece0462db0a22b8e7"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Referer": "https://music.163.com/",
    "Origin": "https://music.163.com",
}


def _pad(data: bytes) -> bytes:
    """PKCS#7 padding."""
    padding = 16 - len(data) % 16
    return data + bytes([padding]) * padding


def _aes_encrypt(data: bytes, key: bytes) -> str:
    """AES-128-CBC + Base64."""
    cipher = AES.new(key, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(_pad(data))
    return base64.b64encode(encrypted).decode("utf-8")


def _create_secret_key() -> bytes:
    """
    Generate the 16-byte ASCII secret key used by NetEase WeAPI.
    """
    return binascii.hexlify(os.urandom(16))[:16]


def _rsa_encrypt(secret_key: bytes) -> str:
    """
    RSA encrypt the reversed secret key.
    """
    text = secret_key[::-1]

    number = int.from_bytes(text, byteorder="big")

    encrypted = pow(
        number,
        int(PUB_KEY, 16),
        int(MODULUS, 16),
    )

    return format(encrypted, "x").zfill(256)


def _weapi_encrypt(payload: dict) -> dict:
    """
    Generate NetEase WebAPI params and encSecKey.
    """
    text = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    secret_key = _create_secret_key()

    # First AES layer
    first = _aes_encrypt(text, PRESET_KEY)

    # Second AES layer
    params = _aes_encrypt(first.encode("utf-8"), secret_key)

    # RSA
    enc_sec_key = _rsa_encrypt(secret_key)

    return {
        "params": params,
        "encSecKey": enc_sec_key,
    }


def _get_csrf_token(cookie: str) -> str:
    """
    Extract __csrf / csrf_token from the supplied NetEase cookie.
    """
    match = re.search(r"(?:^|;\s*)__csrf=([^;]+)", cookie)

    if match:
        return match.group(1)

    match = re.search(r"(?:^|;\s*)csrf_token=([^;]+)", cookie)

    if match:
        return match.group(1)

    raise RuntimeError(
        "NETEASE_COOKIE does not contain __csrf. "
        "Please update the NetEase cookie in GitHub Secrets."
    )


def get_daily_recommendations(cookie: str) -> list[dict]:
    """
    获取网易云音乐「个性化推荐 → 每日歌曲推荐」。

    使用网易云网页实际使用的 WeAPI：
    POST /weapi/v2/discovery/recommend/songs
    """

    csrf_token = _get_csrf_token(cookie)

    # This matches the parameters used by the NetEase web page.
    payload = {
        "limit": "30",
        "offset": "0",
        "total": "true",
    }

    encrypted_data = _weapi_encrypt(payload)

    url = f"{WEAPI_URL}?csrf_token={csrf_token}"

    headers = {
        **HEADERS,
        "Cookie": cookie,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    print("Getting NetEase daily recommendations...")

    response = requests.post(
        url,
        headers=headers,
        data=encrypted_data,
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

    if not songs:
        raise RuntimeError(
            "NetEase returned no daily recommendations. "
            "The cookie may be expired or invalid."
        )

    print(f"Found {len(songs)} NetEase daily recommendations.")

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
            "name": song.get("name", ""),
            "artists": [
                artist.get("name", "")
                for artist in song.get("ar", [])
            ],
        }
        for song in songs
    ]
