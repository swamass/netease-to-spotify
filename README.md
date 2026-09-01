# NetEase Daily → Spotify

Automatically sync NetEase Cloud Music daily recommendations to a dedicated Spotify playlist.

## What it does

```
NetEase Daily Recommendations
        ↓
Spotify Search
        ↓
Conservative matcher
        ↓
Spotify playlist refresh
```

The matcher prioritizes precision over raw match rate. Title, artist, album, duration, and version metadata are evaluated together. Uncertain tracks may be skipped instead of forcing an incorrect match.

⚠️ Use a dedicated Spotify playlist. The formal sync replaces the configured playlist contents with the successfully matched tracks.

## Requirements

- Python 3.12+
- A Spotify Developer application
- A Spotify playlist you own or can modify
- A logged-in NetEase Cloud Music session
- GitHub Actions enabled for scheduled runs

## Quick Start

1. Fork this repository, then clone your fork.
2. Create a Spotify Developer application at the Spotify Developer Dashboard.
3. Add `http://127.0.0.1:8888/callback` as a redirect URI in that application.
4. Run `python setup.py` locally to generate an authorization URL and obtain a refresh token.
5. Obtain your own NetEase cookie from a logged-in NetEase Music browser session.
6. Add the required values as GitHub Repository Secrets.
7. Run **NetEase Spotify Match Dry Run** manually and review its report.
8. Only after the dry run looks correct, run **Sync NetEase Daily Recommendations** manually or wait for its schedule.

The setup helper never uploads credentials or writes them into tracked files.

## Spotify setup

Run:

```bash
python -m pip install -r requirements.txt
python setup.py
```

The helper asks for your Spotify Client ID, Client Secret, and playlist URL or ID. It requests only the current required scope:

```
playlist-modify-private
```

Paste the callback URL returned by Spotify when prompted. The helper validates the OAuth state before exchanging the code for a refresh token. It does not save or print the full client secret or refresh token.

## Required GitHub Secrets

| Secret | Purpose |
| --- | --- |
| `SPOTIFY_CLIENT_ID` | Spotify app Client ID |
| `SPOTIFY_CLIENT_SECRET` | Spotify app Client Secret |
| `SPOTIFY_REFRESH_TOKEN` | Spotify OAuth refresh token |
| `SPOTIFY_PLAYLIST_ID` | Target Spotify playlist ID |
| `NETEASE_COOKIE` | Authentication cookie from your own NetEase session |

Add them under **Repository → Settings → Secrets and variables → Actions**. Forked users must use their own Spotify and NetEase credentials.

## NetEase cookie

The project does not automate NetEase login. Obtain the cookie from your own logged-in NetEase Music session and add it directly as the `NETEASE_COOKIE` repository secret. Do not commit it, paste it into issues, or include it in logs. Cookies can expire and may need to be replaced.

## Dry Run

Use the manual **NetEase Spotify Match Dry Run** workflow before formal syncing. It fetches the current recommendations, searches Spotify, applies the matcher, prints statistics, and uploads a report artifact.

Dry Run does **not** clear the playlist and does **not** add tracks.

## Daily Sync

The formal workflow supports both manual execution and a daily schedule:

```
0 22 * * *
```

GitHub Actions cron uses UTC, so this targets approximately 06:00 Beijing time on the following day. GitHub may introduce scheduling delays.

Before writing, the workflow completes matching. If no reliable tracks are found or Spotify rate limiting aborts the run, the existing playlist is preserved. On a successful run, the configured playlist is replaced with the matched daily tracks.

## Matching philosophy

- Artist identity has the highest importance.
- Core title matching tolerates safe metadata such as remasters, collaborations, and OST attribution.
- Album metadata helps rank candidates but is not an absolute requirement.
- Duration is supporting evidence, not a hard requirement.
- Live, Remix, Acoustic, Instrumental, Demo, Cover, Tribute, Karaoke, and similar conflicting versions can be rejected.
- Search is bounded to at most two Spotify queries per NetEase song.
- A low-confidence candidate is skipped rather than guessed.

## Known limitations

- Spotify Search may not return the correct recording.
- Regional availability and copyright restrictions can prevent a match.
- NetEase and Spotify may use different artist, title, album, or version metadata.
- Japanese, Chinese, and romanized metadata can still produce unmatched songs.
- Live, remix, and other version differences may be intentionally rejected.
- NetEase cookies expire.

## Security

- Never commit `.env`, Spotify credentials, or NetEase cookies.
- Store runtime credentials only in GitHub Actions Secrets or an equivalent secret manager.
- Rotate credentials immediately if they are exposed.
- Never print tokens, secrets, cookies, or OAuth callback codes in logs.
- Use a dedicated target playlist and review Dry Run output before enabling formal sync.

## Troubleshooting

**Missing required environment variable**  
A required GitHub Secret is missing or empty. Check all five names above.

**Spotify 401 or token error**  
Verify the Client ID, Client Secret, refresh token, redirect URI, and Spotify app configuration.

**No sufficiently reliable candidate**  
The matcher intentionally skipped the song because the available result was not reliable enough. Check the Dry Run candidate and rejection logs.

**NetEase authentication failed**  
The cookie may have expired. Obtain a fresh cookie from your own logged-in session.

**Dry Run works but the playlist does not change**  
That is expected: Dry Run is read-only. Use the formal sync workflow to write the playlist.

## Development and tests

Install dependencies and run:

```bash
python -m pip install -r requirements.txt
PYTHONPATH=. pytest -q
```

The tests cover normalization, artist aliases, version protection, candidate ranking, duration scoring, and setup helper behavior.
