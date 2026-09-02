"""Conservative, standalone CJK title normalization experiment."""

from __future__ import annotations

import unicodedata
from typing import Callable


def original_key(value: str) -> str:
    """Return the existing-style comparison key without CJK conversion."""
    return "".join(
        character
        for character in unicodedata.normalize("NFKC", value).casefold()
        if character.isalnum()
    )


def nfkc_key(value: str) -> str:
    return original_key(value)


def opencc_converters() -> dict[str, Callable[[str], str]]:
    """Return optional OpenCC profiles without making OpenCC a dependency."""
    try:
        from opencc import OpenCC
    except ImportError:
        return {}
    return {profile: OpenCC(profile).convert for profile in ("s2t", "s2tw", "s2hk")}


def opencc_converter() -> Callable[[str], str] | None:
    return opencc_converters().get("s2t")


def comparison_keys(value: str, converter: Callable[[str], str] | None = None) -> dict[str, str]:
    keys = {"original": original_key(value), "nfkc": nfkc_key(value)}
    if converter:
        keys["opencc_s2t"] = original_key(converter(value))
    return keys


def all_comparison_keys(value: str) -> dict[str, str]:
    keys = comparison_keys(value)
    for profile, converter in opencc_converters().items():
        keys[f"opencc_{profile}"] = original_key(converter(value))
    return keys


def compare(left: str, right: str, converter: Callable[[str], str] | None = None) -> dict:
    left_keys = comparison_keys(left, converter)
    right_keys = comparison_keys(right, converter)
    shared = sorted(set(left_keys.values()) & set(right_keys.values()))
    return {
        "left": left,
        "right": right,
        "left_keys": left_keys,
        "right_keys": right_keys,
        "equivalent": bool(shared),
        "collision_keys": shared,
    }


def main() -> None:
    samples = [
        ("最後の言い訳", "最后の言い訳"),
        ("间", "間"),
        ("国", "國"),
        ("学", "學"),
        ("爱", "愛"),
        ("会", "會"),
        ("体", "體"),
        ("気", "氣"),
        ("後悔", "后悔"),
        ("神", "神"),
        ("皆既月食", "皆既月蝕"),
        ("東京 / Love", "东京 / Love"),
        ("春の歌", "春の夜"),
    ]
    print(f"OpenCC profiles: {', '.join(opencc_converters()) or 'none'}")
    for left, right in samples:
        print({"input": [left, right], "left_keys": all_comparison_keys(left),
               "right_keys": all_comparison_keys(right),
               "comparison": compare(left, right)})


if __name__ == "__main__":
    main()
