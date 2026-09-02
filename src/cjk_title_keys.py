"""Optional CJK title keys for conservative candidate comparison."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

EXACT = "EXACT"
CJK_EQUIVALENT = "CJK_EQUIVALENT"
NO_MATCH = "NO_MATCH"


def _basic_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _contains_cjk(value: str) -> bool:
    return any(
        "\u3040" <= char <= "\u30ff"
        or "\u3400" <= char <= "\u9fff"
        or "\uf900" <= char <= "\ufaff"
        for char in value
    )


def _han_skeleton(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKC", value).casefold()
        if not ("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff")
    )


def comparison_keys(value: str, converter: Callable[[str], str] | None = None) -> dict[str, str]:
    keys = {"original": _basic_key(value), "nfkc": _basic_key(value)}
    if converter is not None:
        try:
            keys["cjk"] = _basic_key(converter(value))
        except Exception:
            return keys
    return keys


def title_status(
    source: str,
    candidate: str,
    converter: Callable[[str], str] | None = None,
    version_conflict: Callable[[str, str], bool] | None = None,
) -> str:
    if _basic_key(source) == _basic_key(candidate):
        return EXACT
    if not converter or not (_contains_cjk(source) and _contains_cjk(candidate)):
        return NO_MATCH
    if version_conflict and version_conflict(source, candidate):
        return NO_MATCH
    source_keys = comparison_keys(source, converter)
    candidate_keys = comparison_keys(candidate, converter)
    if source_keys.get("nfkc") == candidate_keys.get("nfkc"):
        return NO_MATCH
    if "cjk" not in source_keys or "cjk" not in candidate_keys:
        return NO_MATCH
    if source_keys["cjk"] != candidate_keys["cjk"]:
        return NO_MATCH
    if _han_skeleton(source) != _han_skeleton(candidate):
        return NO_MATCH
    return CJK_EQUIVALENT
