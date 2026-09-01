#!/usr/bin/env python3
"""Interactive helper for creating a Spotify refresh token locally."""

import base64
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import requests


SPOTIFY_AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SCOPE = "playlist-modify-private"
REDIRECT_URI = "http://127.0.0.1:8888/callback"


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


def build_authorization_url(client_id: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SPOTIFY_SCOPE,
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


def main() -> None:
    client_id = input("Spotify Client ID: ").strip()
    client_secret = input("Spotify Client Secret: ").strip()
    playlist_input = input("Spotify playlist URL or ID: ")
    playlist_id = playlist_id_from_input(playlist_input)

    state = secrets.token_urlsafe(24)
    print("\nOpen this URL in your browser:")
    print(build_authorization_url(client_id, state))
    callback = input("\nPaste the full callback URL: ")
    refresh_token = exchange_code(client_id, client_secret, extract_callback_code(callback, state))

    print("\nSetup complete.")
    print("Add these values to GitHub Repository Secrets:")
    print("SPOTIFY_CLIENT_ID=<your value>")
    print("SPOTIFY_CLIENT_SECRET=[hidden]")
    print("SPOTIFY_REFRESH_TOKEN=[hidden]")
    print(f"SPOTIFY_PLAYLIST_ID={playlist_id}")
    print("NETEASE_COOKIE=<add manually from your logged-in NetEase session>")


if __name__ == "__main__":
    main()
