import base64
import json
import os
import random
import string
import subprocess

import requests


WEAPI_URL = "https://music.163.com/weapi/v2/discovery/recommend/songs"

NONCE = "0CoJUm6Qyw8W8jud"
IV = b"0102030405060708"
PUBLIC_EXPONENT = "010001"

# NetEase Cloud Music weapi RSA modulus
RSA_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3ece0462db0a22b8e7"
)


def _get_csrf_token(cookie: str) -> str:
    """从 Cookie 中提取 __csrf。"""
    for item in cookie.split(";"):
        item = item.strip()

        if item.startswith("__csrf="):
            return item.split("=", 1)[1]

    raise RuntimeError(
        "NETEASE_COOKIE does not contain __csrf. "
        "Please update the NetEase cookie in GitHub Secrets."
    )


def _random_key(length: int = 16) -> str:
    """生成 16 位随机 AES key。"""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def _aes_encrypt(text: str, key: str) -> str:
    """
    AES-128-CBC + PKCS7。
    使用 GitHub Actions Ubuntu 自带的 openssl，
    不需要额外安装 Python 加密库。
    """
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-128-cbc",
            "-K",
            key.encode("utf-8").hex(),
            "-iv",
            IV.hex(),
            "-nosalt",
        ],
        input=text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    return base64.b64encode(result.stdout).decode("utf-8")


def _rsa_encrypt(text: str) -> str:
    """
    NetEase weapi RSA：
    1. 反转字符串
    2. 转成十六进制整数
    3. 使用 e=65537
    4. 对 RSA modulus 求幂取模
    5. 左侧补零到 256 位
    """
    reversed_text = text[::-1]
    text_hex = reversed_text.encode("utf-8").hex()

    value = pow(
        int(text_hex, 16),
        int(PUBLIC_EXPONENT, 16),
        int(RSA_MODULUS, 16),
    )

    return format(value, "x").zfill(256)


def _encrypt_request(payload: dict) -> dict:
    """
    生成网易云 weapi 所需要的：
    params
    encSecKey
    """
    text = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    secret_key = _random_key(16)

    first_encrypt = _aes_encrypt(text, NONCE)
    params = _aes_encrypt(first_encrypt, secret_key)

    enc_sec_key = _rsa_encrypt(secret_key)

    return {
        "params": params,
        "encSecKey": enc_sec_key,
    }


def _get_artist_names(song: dict) -> list[str]:
    """Read artist names across NetEase response field variants."""
    raw_artists = song.get("ar") or song.get("artists") or song.get("artist") or []

    if isinstance(raw_artists, dict):
        raw_artists = [raw_artists]

    return [
        artist.get("name", "")
        for artist in raw_artists
        if isinstance(artist, dict) and artist.get("name")
    ]


def get_daily_recommendations(cookie: str) -> list[dict]:
    """
    获取网易云音乐：
    个性化推荐 → 每日歌曲推荐
    """
    csrf_token = _get_csrf_token(cookie)

    payload = {
        "csrf_token": csrf_token,
    }

    encrypted = _encrypt_request(payload)

    headers = {
        "Cookie": cookie,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Referer": "https://music.163.com/",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    response = requests.post(
        WEAPI_URL,
        params={"csrf_token": csrf_token},
        data=encrypted,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"NetEase returned non-JSON response: {response.text[:500]}"
        ) from exc

    if data.get("code") != 200:
        raise RuntimeError(
            f"NetEase API returned code {data.get('code')}: "
            f"{data.get('message', data.get('msg', 'unknown error'))}"
        )

    songs = data.get("data", {}).get("dailySongs", [])

    if not songs:
        raise RuntimeError(
            "NetEase returned 0 daily recommendations. "
            "The cookie may be expired or invalid."
        )

    print("\n===== NetEase Daily Recommendations =====")

    for index, song in enumerate(songs, start=1):
        name = song.get("name", "")

        artists = ", ".join(_get_artist_names(song))

        print(f"{index:02d}. {name} - {artists}")

    print("==========================================")
    print(f"Found {len(songs)} NetEase daily recommendations.\n")

    return [
        {
            "name": song.get("name", ""),
            "artists": _get_artist_names(song),
            "album": song.get("al", {}).get("name", "") or song.get("album", {}).get("name", ""),
        }
        for song in songs
    ]
