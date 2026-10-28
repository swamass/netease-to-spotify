#!/usr/bin/env python3
"""Safely install and remove this project's LaunchAgent."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path


LABEL = "com.swamass.netease-to-spotify"


def _check_directory(path: Path, private: bool) -> None:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Unsafe directory: {path}")
    details = path.lstat()
    if details.st_uid != os.getuid() or (private and details.st_mode & 0o077):
        raise RuntimeError(f"Unsafe directory ownership or permissions: {path}")


def _check_parent_chain(path: Path) -> None:
    home = Path.home()
    current = path
    while True:
        if current.is_symlink():
            raise RuntimeError(f"Unsafe directory path: {current}")
        if current.exists():
            details = current.lstat()
            if not current.is_dir():
                raise RuntimeError(f"Unsafe directory path: {current}")
            if current == home or home in current.parents:
                if details.st_uid != os.getuid():
                    raise RuntimeError(f"Unsafe directory path: {current}")
        if current == current.parent or current == Path.home():
            return
        current = current.parent


def _ensure_directory(path: Path, private: bool) -> None:
    _check_parent_chain(path.parent)
    if path.exists() or path.is_symlink():
        _check_directory(path, private)
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)
    _check_directory(path, private)


def build_plist(python_path: str, script_path: str, repo_dir: str, log_dir: str) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [python_path, script_path, "--scheduled"],
        "WorkingDirectory": repo_dir,
        "StartInterval": 300,
        "StandardOutPath": str(Path(log_dir) / "sync.log"),
        "StandardErrorPath": str(Path(log_dir) / "sync.error.log"),
    }


def _validate_existing_plist(path: Path) -> bytes | None:
    _check_parent_chain(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe LaunchAgent plist: {path}")
    if not path.exists():
        return None
    details = path.lstat()
    if not path.is_file() or details.st_uid != os.getuid() or details.st_mode & 0o077:
        raise RuntimeError(f"Unsafe LaunchAgent plist: {path}")
    original = path.read_bytes()
    parsed = plistlib.loads(original)
    if parsed.get("Label") != LABEL:
        raise RuntimeError(f"Refusing unrelated LaunchAgent plist: {path}")
    return original


def _write_plist(path: Path, payload: dict) -> None:
    _ensure_directory(path.parent, private=False)
    encoded = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)
    plistlib.loads(encoded)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _restore_plist(path: Path, encoded: bytes) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.restore.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        path.chmod(0o600)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _ensure_log_file(path: Path) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Unsafe log file: {path}")
    if path.exists():
        details = path.lstat()
        if not path.is_file() or details.st_uid != os.getuid() or details.st_mode & 0o077:
            raise RuntimeError(f"Unsafe log file: {path}")
        return
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(f"Unable to create log file: {path}") from exc
    os.close(descriptor)


def install(plist_path: Path, python_path: str, script_path: str, repo_dir: str, log_dir: Path) -> None:
    _ensure_directory(log_dir, private=True)
    _ensure_log_file(log_dir / "sync.log")
    _ensure_log_file(log_dir / "sync.error.log")
    original = _validate_existing_plist(plist_path)
    payload = build_plist(python_path, script_path, repo_dir, str(log_dir))
    _write_plist(plist_path, payload)
    domain = f"gui/{os.getuid()}"
    try:
        subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False)
        result = subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=False)
        if result.returncode != 0:
            raise RuntimeError("launchctl bootstrap returned a non-zero status")
    except Exception as exc:
        try:
            subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False)
        except Exception:
            pass
        try:
            if original is None:
                plist_path.unlink(missing_ok=True)
            else:
                _restore_plist(plist_path, original)
                try:
                    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=False)
                except Exception:
                    pass
        except Exception as restore_error:
            raise RuntimeError("launchctl failed and previous configuration could not be restored") from restore_error
        raise RuntimeError("launchctl bootstrap failed; previous configuration was restored") from exc


def uninstall(plist_path: Path) -> None:
    original = _validate_existing_plist(plist_path)
    if original is None:
        return
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False)
    plist_path.unlink()


def main(argv: list[str] | None = None) -> None:
    command, *values = argv or sys.argv[1:]
    if command == "install" and len(values) == 5:
        install(Path(values[0]), values[1], values[2], values[3], Path(values[4]))
        return
    if command == "uninstall" and len(values) == 1:
        uninstall(Path(values[0]))
        return
    raise SystemExit("usage: local_launchd.py install PLIST PYTHON SCRIPT REPO LOG_DIR | uninstall PLIST")


if __name__ == "__main__":
    main()
