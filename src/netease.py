import base64
import binascii
import json
import os
import random
import string

import requests
from Crypto.Cipher import AES


WEAPI_URL = (
    "https://music.163.com/weapi/v2/discovery/recommend/songs"
)

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
}


def _pkcs7_pad(data: bytes) -> bytes:
    padding = 16 - len(data) % 16
    return data + bytes([padding]) * padding


def _aes_encrypt(data: bytes, key: bytes) -> str:
    cipher = AES.new(key, AES.MODE_CBC, IV)
    encrypted = cipher.encrypt(_pkcs7_pad(data))
    return base64.b64encode(encrypted).decode("utf-8")


def _random_secret_key() -> bytes:
    """
    NetEase WeAPI 使用 16 字符的随机字符串作为第二层 AES key。
    """
    chars = string.ascii_letters + string.digits
    return "".join(
        random.choice(chars) for _ in range(16)
    ).encode("utf-8")


def _rsa_encrypt(secret_key: bytes) -> str:
    """
    NetEase WeAPI RSA:
    1. 反转 AES secret key
    2. 转换为大整数
    3. RSA modular exponentiation
    """

    reversed_key = secret_key[::-1]

    text = int(
        binascii.hexlify(reversed_key),
        16,
    )

    modulus = int(MODULUS, 16)

    encrypted = pow(
        text,
        PUB_KEY,
        modulus,
    )

    return format(encrypted, "x").zfill(256)


def _weapi_encrypt(payload: dict) -> dict:
    """
    生成网易云 WeAPI 所需的 params 和 encSecKey。
    """

    text = json.dumps(
        payload,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    secret_key = _random_secret_key()

    # 第一层 AES
    first = _aes_encrypt(
        text,
        PRESET_KEY,
    )

    # 第二层 AES
    params = _aes_encrypt(
        first.encode("utf-8"),
        secret_key,
    )

    # RSA
    enc_sec_key = _rsa_encrypt(secret_key)

    return {
        "params": params,
        "encSecKey": enc_sec_key,
    }


def _get_csrf_token() -> str:
    """
    从 GitHub Actions Secret 获取 CSRF Token。
    """

    csrf_token = os.getenv(
        "NETEASE_CSRF_TOKEN",
        "",
    ).strip()

    if not csrf_token:
        raise RuntimeError(
            "NETEASE_CSRF_TOKEN is missing."
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
    }

    encrypted = _weapi_encrypt(payload)

    headers = {
        **HEADERS,
        "Cookie": cookie,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    print(
        "Getting NetEase daily recommendations..."
    )

    response = requests.post(
        f"{WEAPI_URL}?csrf_token={csrf_token}",
        headers=headers,
        data=encrypted,
        timeout=30,
    )

    response.raise_for_status()

    data =
