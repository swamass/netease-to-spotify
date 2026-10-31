#!/usr/bin/env python3
"""Interactive helper for creating a Spotify refresh token locally."""

import base64
import getpass
import os
import stat
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests


SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SCOPE = "playlist-read-private playlist-modify-private"
SPOTIFY_PUBLIC_SCOPE = f"{SPOTIFY_SCOPE} playlist-modify-public"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
ENV_PATH = Path.home() / ".config" / "netease-to-spotify" / ".env"
CALLBACK_TIMEOUT_SECONDS = 300


def playlist_id_from_input(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 2 and parts[0] == "playlist":
            value = parts[1]
        else:
            raise ValueError("Enter a Spotify playlist URL or playlist ID.")
    if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789" for character in value):
        raise ValueError("Enter a valid Spotify playlist URL or playlist ID.")
    return value


def build_authorization_url(client_id: str, state: str, scope: str = SPOTIFY_SCOPE) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": scope,
        "state": state,
    }
    return f"{SPOTIFY_AUTHORIZE_URL}?{urlencode(params)}"


def extract_callback_code(callback: str, expected_state: str) -> str:
    parsed = urlparse(callback.strip())
    values = parse_qs(parsed.query)
    if values.get("state", [None])[0] != expected_state:
        raise ValueError("OAuth state mismatch.")
    if values.get("error", [None])[0]:
        raise ValueError(f"Spotify authorization failed: {values['error'][0]}")
    code = values.get("code", [None])[0]
    if not code:
        raise ValueError("Callback URL does not contain an authorization code.")
    return code


def exchange_code(client_id: str, client_secret: str, code: str) -> str:
    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode("utf-8")
    ).decode("ascii")
    response = requests.post(
        SPOTIFY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json().get("refresh_token")
    if not token:
        raise RuntimeError("Spotify did not return a refresh token.")
    return token


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if urlparse(self.path).path != urlparse(REDIRECT_URI).path:
            self.send_error(404)
            return
        self.server.callback = self.path
        body = b"Spotify authorization received. You may close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def receive_callback(timeout: int = CALLBACK_TIMEOUT_SECONDS) -> str:
    server = HTTPServer(("127.0.0.1", 8888), _CallbackHandler)
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while getattr(server, "callback", None) is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("Spotify authorization callback timed out.")
            server.handle_request()
        return server.callback
    finally:
        server.server_close()


def _check_private_file(path: Path) -> None:
    details = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(details.st_mode):
        raise RuntimeError(f"Unsafe environment file: {path}")
    # Ownership and POSIX mode bits are not available through os.getuid() on
    # Windows. Keep the regular-file and symlink checks there, while enforcing
    # the stronger owner/mode checks on POSIX systems.
    if hasattr(os, "getuid") and (
        details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077
    ):
        raise RuntimeError(f"Unsafe environment file permissions: {path}")


def _ensure_env_directory(path: Path) -> None:
    home = Path.home()
    parent = path.parent
    while parent != parent.parent:
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise RuntimeError(f"Unsafe environment directory path: {parent}")
        if (
            hasattr(os, "getuid")
            and parent.exists()
            and (parent == home or home in parent.parents)
        ):
            if parent.lstat().st_uid != os.getuid():
                raise RuntimeError(f"Unsafe environment directory path: {parent}")
        parent = parent.parent
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RuntimeError(f"Unsafe environment directory: {path}")
    if path.exists():
        details = path.lstat()
        if hasattr(os, "getuid") and (
            details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) & 0o077
        ):
            raise RuntimeError(f"Unsafe environment directory permissions: {path}")
        return
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _env_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    _check_private_file(path)
    return path.read_text(encoding="utf-8").splitlines()


def save_credentials(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    playlist_id: str | None = None,
    radar_playlist_id: str | None = None,
    path: Path = ENV_PATH,
) -> None:
    """Update OAuth values while preserving unrelated existing .env lines."""
    _ensure_env_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError(f"Unsafe environment file: {path}")
    lines = _env_lines(path)
    updates = {
        "SPOTIFY_CLIENT_ID": client_id,
        "SPOTIFY_CLIENT_SECRET": client_secret,
        "SPOTIFY_REFRESH_TOKEN": refresh_token,
    }
    if playlist_id is not None:
        updates["SPOTIFY_PLAYLIST_ID"] = playlist_id
    if radar_playlist_id is not None:
        updates["SPOTIFY_RADAR_PLAYLIST_ID"] = radar_playlist_id
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    encoded = ("\n".join(output) + "\n").encode("utf-8")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
        path.chmod(0o600)
        _check_private_file(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    client_id = input("Spotify Client ID: ").strip()
    client_secret = getpass.getpass("Spotify Client Secret: ").strip()
    existing_lines = _env_lines(ENV_PATH) if ENV_PATH.exists() else []
    existing_playlist = next(
        (line.split("=", 1)[1].strip() for line in existing_lines if line.startswith("SPOTIFY_PLAYLIST_ID=")),
        "",
    )
    existing_radar_playlist = next(
        (
            line.split("=", 1)[1].strip()
            for line in existing_lines
            if line.startswith("SPOTIFY_RADAR_PLAYLIST_ID=")
        ),
        "",
    )
    playlist_id = existing_playlist or playlist_id_from_input(input("Spotify playlist URL or ID: "))
    is_public = input("Is the target playlist public? [y/N]: ").strip().lower() in {"y", "yes"}
    radar_input = input(
        "Spotify Private Radar target playlist URL or ID (optional; Enter to skip): "
    ).strip()
    radar_playlist_id = (
        playlist_id_from_input(radar_input)
        if radar_input
        else existing_radar_playlist or None
    )
    radar_is_public = (
        input("Is the radar target playlist public? [y/N]: ").strip().lower()
        in {"y", "yes"}
        if radar_playlist_id
        else False
    )
    if radar_playlist_id == playlist_id:
        raise ValueError("Use a separate Spotify playlist for Private Radar.")
    scope = SPOTIFY_PUBLIC_SCOPE if is_public or radar_is_public else SPOTIFY_SCOPE

    state = secrets.token_urlsafe(24)
    authorization_url = build_authorization_url(client_id, state, scope)
    try:
        browser_opened = webbrowser.open(authorization_url)
    except Exception:
        browser_opened = False
    if not browser_opened:
        print("无法自动打开浏览器，请手动打开授权页面。")
        print(authorization_url)
    else:
        print("已打开 Spotify 授权页面，请在浏览器中完成授权。")
    callback = receive_callback()
    refresh_token = exchange_code(client_id, client_secret, extract_callback_code(callback, state))
    save_credentials(
        client_id,
        client_secret,
        refresh_token,
        playlist_id=None if existing_playlist else playlist_id,
        radar_playlist_id=radar_playlist_id,
    )
    print(f"Spotify credentials saved securely to {ENV_PATH}.")


if __name__ == "__main__":
    main()
