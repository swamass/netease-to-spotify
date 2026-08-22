# netease-to-spotify

Automatically sync NetEase Cloud Music daily recommendations to a Spotify playlist.

This repository is initialized as a safe skeleton. It does not contain any real
Spotify or NetEase credentials.

## What it will do

1. Read NetEase Cloud Music daily recommended songs.
2. Search matching tracks on Spotify.
3. Add matched tracks to a Spotify playlist.
4. Keep a local sync record so the same songs are not added repeatedly.
5. Run automatically on a schedule through GitHub Actions.

## Current status

The project structure and GitHub Actions workflow are ready. The next step is to
add credentials through GitHub Secrets, then implement and test the real API
calls.

## Required GitHub Secrets

Create these secrets in GitHub repository settings:

| Secret name | Purpose |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify app client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify app client secret |
| `SPOTIFY_REFRESH_TOKEN` | Spotify OAuth refresh token |
| `SPOTIFY_PLAYLIST_ID` | Target Spotify playlist ID |
| `NETEASE_COOKIE` | NetEase Cloud Music login cookie |

Do not commit these values to the repository.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill `.env` locally for testing. `.env` is ignored by Git.

## Run locally

```bash
python -m src.main
```

At this stage, the command only validates that required environment variables
are present and prints a safe placeholder message.

## GitHub Actions

The workflow in `.github/workflows/sync.yml` is configured to run daily and can
also be started manually from the GitHub Actions page.

Before enabling real syncing, confirm the secrets above are configured.
