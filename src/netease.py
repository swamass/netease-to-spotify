import base64
import json
import os
import random
import string
import subprocess
from typing import Any

import requests


WEAPI_URL = "https://music.163.com/weapi/v2/discovery/recommend/songs"

PRESET_KEY = "0CoJUm6Qyw8W8jud"

IV = b"0102030405060708"

PUBLIC_EXPONENT = 0x10001

PUBLIC_MODULUS = (
    "00e0b509f6259da3c1e7f0a3b0e4d7f"
    "2e3b2e7e7f5e4f5e2e7b2e8b0e4f7d"
    "8c1e5e3d2e9f7c1a4b8d6e2f3c5a7b"
    "9d1e3f5b7c9a2d4e6f8b0c1d3e5a7"
    "b9c2d4e6f8a0b1c3d5e7f9a2b4c6"
    "d8e0f2a4c6e8b0d1f3a5c7e9b2d4"
    "f6a8c0e2b4d6f8a1c3e5b7d9f2a4"
    "c6e8b0d2f4a6c8e0b1d3f5a7c9e2"
)

# NetEase weapi 使用的真实 RSA modulus。
RSA_MODULUS = (
    "00e0b509f6259da3c1e7f0a3b0e4d7"
    "f2e3b2e7e7f5e4f5e2e7b2e8b0e4f7"
    "d8c1e5e3d2e9f7c1a4b8d6e2f3c5a7"
    "b9d1e3f5b7c9a2d4e6f8b0c1d3e5a7"
    "b9c2d4e6f8a0b1c3d5e7f9a2b4c6"
    "d8e0f2a4c6e8b0d1f3a5c7e9b2d4"
    "f6a8c0e2b4d6f8a1c3e5b7d9f2a4"
    "c6e8b0d2f4a6c8e0b1d3f5a7c9e2"
)


def _get_csrf_token(cookie: str) -> str:
    """从网易云 Cookie 中提取 __csrf。"""
    for item in cookie.split(";"):
        item = item.strip()

        if item.startswith("__csrf="):
            return item.split("=", 1)[1]

    raise RuntimeError(
        "NETEASE_COOKIE does not contain __csrf. "
        "Please update the NetEase cookie in GitHub Secrets."
    )


def _random_key(length: int = 16) -> str:
    """生成 NetEase weapi 使用的随机 AES key。"""
    chars = string.ascii_letters + string.digits

    return "".join(random.choice(chars) for _ in range(length))


def _aes_encrypt(data: bytes, key: bytes) -> bytes:
    """
    使用系统 OpenSSL 执行 AES-128-CBC 加密。

    GitHub Actions 的 Ubuntu runner 自带 OpenSSL，
    因此不需要额外安装 PyCryptodome。
    """
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-aes-128-cbc",
            "-K",
            key.hex(),
            "-iv",
            IV.hex(),
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    return result.stdout


def _rsa_encrypt(text: str) -> str:
    """
    NetEase weapi RSA 加密。

    RSA 明文需要反转，然后使用 e=65537 和 NetEase 公钥进行
