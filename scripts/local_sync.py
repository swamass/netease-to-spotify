#!/usr/bin/env python3
"""Run the existing sync with a Cookie from a persistent local browser session."""

from __future__ import annotations

import os
import stat
import argparse
import fcntl
import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from dotenv import dotenv_values


REPO_ROOT = Path(__file__).resolve().parents[1]


DEFAULT_ENV_FILE = Path.home() / ".config" / "netease-to-spotify" / ".env"
DEFAULT_PROFILE_DIR = Path.home() / ".local" / "share" / "netease-to-spotify-browser"
DEFAULT_STATE_FILE = Path.home() / ".local" / "state" / "netease-to-spotify" / "last-run.json"
DEFAULT_LOCK_FILE = Path.home() / ".local" / "state" / "netease-to-spotify" / "run.lock"
NETEASE_URL = "https://music.163.com/"
BEIJING_ZONE = ZoneInfo("Asia/Shanghai")
REQUIRED_ENV = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REFRESH_TOKEN",
    "SPOTIFY_PLAYLIST_ID",
)


def _ensure_repo_import_path() -> None:
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _load_local_env(path: Path) -> None:
    _ensure_secure_directory(path.parent)
    if not path.exists():
        raise RuntimeError(f"Missing local environment file: {path}")
    _check_secure_file(path, "Local environment file")
    values = dotenv_values(path)
    missing = [name for name in REQUIRED_ENV if not values.get(name)]
    if missing:
        raise RuntimeError("Missing local environment values: " + ", ".join(missing))
    for name in REQUIRED_ENV:
        os.environ[name] = str(values[name])


def _cookie_header(cookies: list[dict]) -> str:
    names = {cookie.get("name") for cookie in cookies}
    missing = {"MUSIC_U", "__csrf"} - names
    if missing:
        raise RuntimeError("网易云浏览器会话未登录或已失效；缺少：" + ", ".join(sorted(missing)))
    return "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if cookie.get("name") and cookie.get("value")
    )


def _ensure_secure_directory(path: Path) -> None:
    _check_parent_chain(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe directory: {path}")
    if path.exists():
        details = path.lstat()
        if not stat.S_ISDIR(details.st_mode):
            raise RuntimeError(f"Unsafe directory: {path}")
        if details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077:
            raise RuntimeError(f"Unsafe directory ownership or permissions: {path}")
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _check_parent_chain(path: Path) -> None:
    home = Path.home()
    current = path
    while True:
        if current.is_symlink():
            raise RuntimeError(f"Unsafe directory path: {current}")
        if current.exists():
            details = current.lstat()
            if not stat.S_ISDIR(details.st_mode):
                raise RuntimeError(f"Unsafe directory path: {current}")
            if current == home or home in current.parents:
                if details.st_uid != os.getuid():
                    raise RuntimeError(f"Unsafe directory path: {current}")
        if current == current.parent or current == Path.home():
            return
        current = current.parent


def _check_secure_file(path: Path, label: str) -> None:
    details = path.lstat()
    if not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid():
        raise RuntimeError(f"Unsafe {label}: {path}")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise RuntimeError(f"Unsafe {label} permissions: {path}")


def _scheduled_time(now: datetime | None = None) -> datetime:
    current = now or datetime.now(BEIJING_ZONE)
    return current.astimezone(BEIJING_ZONE)


def _after_schedule(now: datetime | None = None) -> bool:
    current = _scheduled_time(now)
    target = current.replace(hour=6, minute=10, second=0, microsecond=0)
    return current >= target


def _read_state(path: Path) -> dict:
    if path.is_symlink():
        raise RuntimeError(f"Unsafe schedule state: {path}")
    if not path.exists():
        return {}
    _check_secure_file(path, "schedule state")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Unreadable schedule state: {path}") from exc


def _write_state(path: Path, value: dict) -> None:
    _ensure_secure_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe schedule state: {path}")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(value))
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        _check_secure_file(path, "schedule state")
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


@contextmanager
def _open_secure_lock(path: Path) -> Iterator[object]:
    if path.is_symlink():
        raise RuntimeError(f"Unsafe schedule lock: {path}")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(f"Unsafe schedule lock: {path}") from exc
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise RuntimeError(f"Unsafe schedule lock: {path}")
        with os.fdopen(descriptor, "r+") as lock:
            descriptor = None
            yield lock
    finally:
        if descriptor is not None:
            os.close(descriptor)


@contextmanager
def _scheduled_guard(
    now: datetime | None = None,
    state_path: Path = DEFAULT_STATE_FILE,
    lock_path: Path = DEFAULT_LOCK_FILE,
) -> Iterator[bool]:
    if not _after_schedule(now):
        yield False
        return
    _ensure_secure_directory(lock_path.parent)
    _ensure_secure_directory(state_path.parent)
    with _open_secure_lock(lock_path) as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        current = _scheduled_time(now)
        state = _read_state(state_path)
        if state.get("last_attempt_date") == current.date().isoformat():
            yield False
            return
        _write_state(state_path, {"last_attempt_date": current.date().isoformat()})
        try:
            yield True
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _read_browser_cookie(profile_dir: Path) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Install local browser support with: python -m pip install "
            "-r local-requirements.txt && python -m playwright install chromium"
        ) from exc
    _ensure_secure_directory(profile_dir)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(str(profile_dir), headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(NETEASE_URL, wait_until="domcontentloaded", timeout=30_000)
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                try:
                    return _cookie_header(context.cookies(NETEASE_URL))
                except RuntimeError:
                    page.wait_for_timeout(5_000)
            raise RuntimeError("网易云登录等待超时；请在打开的浏览器窗口中完成登录。")
        finally:
            context.close()


def _notify_failure() -> None:
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "查看错误日志；今天不会自动重试" with title "网易云 → Spotify 同步失败"',
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _run_sync() -> None:
    _ensure_repo_import_path()
    env_file = Path(os.environ.get("NETEASE_TO_SPOTIFY_ENV_FILE", DEFAULT_ENV_FILE)).expanduser()
    profile_dir = Path(os.environ.get("NETEASE_TO_SPOTIFY_BROWSER_PROFILE", DEFAULT_PROFILE_DIR)).expanduser()
    _load_local_env(env_file)
    cookie = _read_browser_cookie(profile_dir)
    os.environ["NETEASE_COOKIE"] = cookie

    from src.main import main as sync_main
    from src.netease import get_daily_recommendations

    songs = get_daily_recommendations(cookie)
    if not songs:
        raise RuntimeError("网易云每日推荐为空；已停止，不会修改 Spotify Playlist。")
    sync_main(songs=songs)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.scheduled:
            with _scheduled_guard() as should_run:
                if should_run:
                    _run_sync()
        else:
            _run_sync()
    except Exception:
        _notify_failure()
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Local sync failed: {exc}", file=sys.stderr)
        raise
