#!/usr/bin/env python3
"""Refresh the GitHub Actions NetEase cookie from the local browser profile."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_DIR = Path.home() / ".local" / "share" / "netease-to-spotify-browser"
GITHUB_REPO = "swamass/netease-to-spotify"


def _ensure_repo_import_path() -> None:
    repo_root = str(REPO_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _set_github_secret(cookie: str, repository: str = GITHUB_REPO) -> None:
    if not shutil.which("gh"):
        raise RuntimeError("未找到 gh；请安装 GitHub CLI 后先运行 gh auth login。")
    result = subprocess.run(
        ["gh", "secret", "set", "NETEASE_COOKIE", "--repo", repository],
        input=cookie.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=30,
    )
    if result.returncode:
        raise RuntimeError("GitHub Secret 更新失败；请确认 gh auth login 已完成且对仓库有权限。")


def update_cookie_secret(profile_dir: Path, repository: str = GITHUB_REPO) -> None:
    _ensure_repo_import_path()
    from scripts.local_sync import _read_browser_cookie
    from src.netease import NetEaseAuthenticationError, get_daily_recommendations

    cookie = _read_browser_cookie(profile_dir)
    try:
        get_daily_recommendations(cookie, verbose=False)
    except NetEaseAuthenticationError:
        cookie = _read_browser_cookie(profile_dir, clear_login=True)
        get_daily_recommendations(cookie, verbose=False)
    _set_github_secret(cookie, repository)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate local NetEase login and update GitHub Secret.")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--repo", default=GITHUB_REPO)
    args = parser.parse_args(argv)
    try:
        update_cookie_secret(args.profile.expanduser(), args.repo)
    except Exception as exc:
        print(f"未更新 NETEASE_COOKIE：{type(exc).__name__}。请检查本地登录、网络和 gh 权限。", file=sys.stderr)
        return 1
    print(f"已验证网易云登录状态并更新 {args.repo} 的 NETEASE_COOKIE。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
