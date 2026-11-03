#!/usr/bin/env python3
"""Encrypt and atomically persist synthetic authentication state."""

import base64
import fcntl
import hashlib
import json
import os
import secrets
import stat
import tempfile
from pathlib import Path

from Crypto.Cipher import AES


STATE_FILES = (
    ".netease_mcp_device.json",
    ".config/ncm-cli/credentials.enc.json",
    ".config/ncm-cli/tokens.enc.json",
)
FORMAT_VERSION = 1


class StateCorruptError(RuntimeError):
    pass


class StateMissingError(RuntimeError):
    pass


class ConcurrentUpdateError(RuntimeError):
    pass


def _payload(source_home: Path) -> dict[str, object]:
    files: dict[str, str] = {}
    for relative_path in STATE_FILES:
        path = source_home / relative_path
        files[relative_path] = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"version": FORMAT_VERSION, "files": files}


def _encrypt(payload: dict[str, object], key: bytes) -> bytes:
    cipher = AES.new(key, AES.MODE_GCM, nonce=secrets.token_bytes(12))
    ciphertext, tag = cipher.encrypt_and_digest(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return b"NCM1" + cipher.nonce + tag + ciphertext


def _decrypt(blob: bytes, key: bytes) -> dict[str, object]:
    if len(blob) < 32 or blob[:4] != b"NCM1":
        raise ValueError("invalid authentication state envelope")
    nonce, tag, ciphertext = blob[4:16], blob[16:32], blob[32:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    payload = json.loads(cipher.decrypt_and_verify(ciphertext, tag))
    if payload.get("version") != FORMAT_VERSION or not isinstance(payload.get("files"), dict):
        raise ValueError("unsupported authentication state envelope")
    return payload


def state_digest(encrypted_path: Path) -> str:
    return hashlib.sha256(encrypted_path.read_bytes()).hexdigest()


def _read_payload(encrypted_path: Path, key: bytes) -> dict[str, object]:
    try:
        return _decrypt(encrypted_path.read_bytes(), key)
    except FileNotFoundError as error:
        raise StateMissingError("encrypted authentication state is missing") from error
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise StateCorruptError("encrypted authentication state is unreadable") from error


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


def save_if_changed(
    source_home: Path,
    encrypted_path: Path,
    key: bytes,
    expected_digest: str | None = None,
) -> bool:
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    lock_path = encrypted_path.with_name(f".{encrypted_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open("a+b") as lock_file:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        payload = _payload(source_home)
        if encrypted_path.exists():
            current_digest = state_digest(encrypted_path)
            if expected_digest is not None and current_digest != expected_digest:
                raise ConcurrentUpdateError("encrypted authentication state changed")
            if _read_payload(encrypted_path, key) == payload:
                return False
        elif expected_digest is not None:
            raise ConcurrentUpdateError("encrypted authentication state disappeared")
        _atomic_write(encrypted_path, _encrypt(payload, key))
        return True


def restore(encrypted_path: Path, target_home: Path, key: bytes) -> None:
    if len(key) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    payload = _read_payload(encrypted_path, key)
    files = payload["files"]
    assert isinstance(files, dict)
    for relative_path, encoded in files.items():
        if relative_path not in STATE_FILES or not isinstance(encoded, str):
            raise ValueError("invalid authentication state file list")
        target = target_home / relative_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.parent.chmod(0o700)
        _atomic_write(target, base64.b64decode(encoded, validate=True))
