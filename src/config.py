import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    spotify_client_secret: str
    spotify_refresh_token: str
    spotify_playlist_id: str
    netease_cookie: str


REQUIRED_ENV_VARS = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REFRESH_TOKEN",
    "SPOTIFY_PLAYLIST_ID",
    "NETEASE_COOKIE",
)


def load_settings() -> Settings:
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(f"Missing required environment variables: {joined}")

    return Settings(
        spotify_client_id=os.environ["SPOTIFY_CLIENT_ID"],
        spotify_client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        spotify_refresh_token=os.environ["SPOTIFY_REFRESH_TOKEN"],
        spotify_playlist_id=os.environ["SPOTIFY_PLAYLIST_ID"],
        netease_cookie=os.environ["NETEASE_COOKIE"],
    )
