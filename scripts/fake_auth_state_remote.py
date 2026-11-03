#!/usr/bin/env python3
"""Exercise encrypted state persistence against a dedicated Git branch."""

import argparse
import base64
import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.auth_state_store import restore, save_if_changed, state_digest


BRANCH = "ncm-auth-state-fake"
STATE_NAME = "auth-state.enc"
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _git(cwd: Path, *args: str, git_env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=git_env,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError("git operation failed") from error
    return result.stdout.strip()


def _branch_exists(remote: str, git_env: dict[str, str]) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", remote, f"refs/heads/{BRANCH}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=git_env,
    )
    return result.returncode == 0


def _write_fake_home(path: Path, token: str) -> None:
    config = path / ".config/ncm-cli"
    config.mkdir(parents=True, mode=0o700)
    (path / ".netease_mcp_device.json").write_text('{"device":"fake"}')
    (config / "credentials.enc.json").write_text('{"credentials":"fake"}')
    (config / "tokens.enc.json").write_text(f'{{"token":"{token}"}}')


def _validate_branch(path: Path) -> None:
    if _git(path, "ls-files") != STATE_NAME:
        raise RuntimeError("state branch contains unexpected files")


def _remove_lock(path: Path) -> None:
    path.with_name(f".{path.name}.lock").unlink(missing_ok=True)


def _clone(remote: str, path: Path, git_env: dict[str, str]) -> None:
    _git(
        path.parent,
        "clone",
        "--branch",
        BRANCH,
        "--single-branch",
        remote,
        str(path),
        git_env=git_env,
    )
    _validate_branch(path)


def _commit_and_push(path: Path, remote: str, message: str, git_env: dict[str, str]) -> None:
    _git(path, "add", STATE_NAME, git_env=git_env)
    if not _git(path, "status", "--porcelain", git_env=git_env):
        return
    _git(path, "config", "user.name", "NCM fake state test", git_env=git_env)
    _git(path, "config", "user.email", "ncm-fake-state@example.invalid", git_env=git_env)
    _git(path, "commit", "-m", message, git_env=git_env)
    _git(path, "push", remote, f"HEAD:refs/heads/{BRANCH}", git_env=git_env)


def run(
    repo: Path,
    remote: str,
    key: bytes,
    initialize: bool,
    git_env: dict[str, str],
) -> None:
    if len(key) != 32:
        raise ValueError("NCM_AUTH_FAKE_STATE_KEY must decode to 32 bytes")
    if not BRANCH_RE.fullmatch(BRANCH):
        raise ValueError("invalid state branch")
    exists = _branch_exists(remote, git_env)
    if not exists and not initialize:
        raise RuntimeError("state branch is missing; explicit initialization required")
    if exists and initialize:
        raise RuntimeError("state branch already exists; refusing reinitialization")

    with tempfile.TemporaryDirectory(prefix="ncm-auth-state-") as temporary:
        root = Path(temporary)
        branch_path = root / "branch"
        if exists:
            _clone(remote, branch_path, git_env)
        else:
            branch_path.mkdir()
            _git(branch_path, "init", "-q", git_env=git_env)
            _git(branch_path, "checkout", "--orphan", BRANCH, "-q", git_env=git_env)
            _git(branch_path, "remote", "add", "origin", remote, git_env=git_env)

        source = root / "source"
        source.mkdir()
        _write_fake_home(source, "initial")
        encrypted = branch_path / STATE_NAME
        if not exists:
            save_if_changed(source, encrypted, key)
            _remove_lock(encrypted)
            _commit_and_push(branch_path, "origin", "Initialize fake NCM auth state", git_env)
            exists = True
            _clone(remote, root / "initial-check", git_env)
        else:
            restore(encrypted, root / "restored-initial", key)

        no_change_path = root / "no-change"
        _clone(remote, no_change_path, git_env)
        no_change_state = no_change_path / STATE_NAME
        no_change_digest = state_digest(no_change_state)
        restore(no_change_state, root / "restored-no-change", key)
        if save_if_changed(root / "restored-no-change", no_change_state, key, no_change_digest):
            raise RuntimeError("unchanged fake state was written")
        _remove_lock(no_change_state)
        if _git(no_change_path, "status", "--porcelain", git_env=git_env):
            raise RuntimeError("unchanged fake state created a Git change")

        update_path = root / "update"
        _clone(remote, update_path, git_env)
        update_state = update_path / STATE_NAME
        update_digest = state_digest(update_state)
        update_source = root / "updated-source"
        update_source.mkdir()
        _write_fake_home(update_source, "updated")
        if not save_if_changed(update_source, update_state, key, update_digest):
            raise RuntimeError("changed fake state was not written")
        _remove_lock(update_state)
        _commit_and_push(update_path, "origin", "Update fake NCM auth state", git_env)

        latest_path = root / "latest"
        _clone(remote, latest_path, git_env)
        latest_home = root / "restored-latest"
        restore(latest_path / STATE_NAME, latest_home, key)
        if (latest_home / ".config/ncm-cli/tokens.enc.json").read_text() != '{"token":"updated"}':
            raise RuntimeError("latest fake state was not restored")

    print("fake_state_remote_test=success")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    git_env = os.environ.copy()
    header_result = subprocess.run(
        ["git", "config", "--local", "--get", "http.https://github.com/.extraheader"],
        cwd=args.repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=git_env,
    )
    header = header_result.stdout.strip() if header_result.returncode == 0 else ""
    if header:
        git_env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": header,
            }
        )
    git_env["GIT_TERMINAL_PROMPT"] = "0"
    remote = _git(args.repo, "config", "--get", "remote.origin.url", git_env=git_env)
    encoded_key = os.environ.get("NCM_AUTH_FAKE_STATE_KEY", "")
    key = base64.b64decode(encoded_key, validate=True)
    run(args.repo, remote, key, args.initialize, git_env)


if __name__ == "__main__":
    main()
