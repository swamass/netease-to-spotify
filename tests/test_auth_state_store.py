from pathlib import Path
from types import SimpleNamespace

from Crypto.Random import get_random_bytes

import pytest

import scripts.auth_state_store as store
import scripts.fake_auth_state_remote as remote_state
from scripts.auth_state_store import (
    ConcurrentUpdateError,
    StateCorruptError,
    StateMissingError,
    restore,
    save_if_changed,
    state_digest,
)


def _write_fake_state(home: Path, token: str = "fake-token") -> None:
    (home / ".config/ncm-cli").mkdir(parents=True)
    (home / ".netease_mcp_device.json").write_text('{"device":"fake"}')
    (home / ".config/ncm-cli/credentials.enc.json").write_text('{"credentials":"fake"}')
    (home / ".config/ncm-cli/tokens.enc.json").write_text(
        f'{{"token":"{token}"}}'
    )


def test_unchanged_state_is_not_rewritten(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source)
    encrypted = tmp_path / "store" / "auth-state.enc"
    key = get_random_bytes(32)

    assert save_if_changed(source, encrypted, key) is True
    first_mtime = encrypted.stat().st_mtime_ns
    first_bytes = encrypted.read_bytes()
    assert save_if_changed(source, encrypted, key) is False
    assert encrypted.stat().st_mtime_ns == first_mtime
    assert encrypted.read_bytes() == first_bytes


def test_changed_state_is_encrypted_and_restorable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source, token="first")
    encrypted = tmp_path / "store" / "auth-state.enc"
    restored = tmp_path / "restored"
    key = get_random_bytes(32)

    assert save_if_changed(source, encrypted, key) is True
    source.joinpath(".config/ncm-cli/tokens.enc.json").write_text(
        '{"token":"second"}'
    )
    assert save_if_changed(source, encrypted, key) is True
    restore(encrypted, restored, key)
    assert restored.joinpath(".config/ncm-cli/tokens.enc.json").read_text() == '{"token":"second"}'
    assert stat_mode(restored.joinpath(".netease_mcp_device.json")) == 0o600


def test_wrong_key_does_not_restore(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source)
    encrypted = tmp_path / "store" / "auth-state.enc"
    save_if_changed(source, encrypted, get_random_bytes(32))

    with pytest.raises(StateCorruptError):
        restore(encrypted, tmp_path / "restored", get_random_bytes(32))


def test_state_branch_simulation_preserves_latest_writer(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source, token="first")
    branch_state = tmp_path / "state-branch" / "auth-state.enc"
    key = get_random_bytes(32)
    assert save_if_changed(source, branch_state, key) is True
    assert b"second" not in branch_state.read_bytes()
    initial_digest = state_digest(branch_state)

    source.joinpath(".config/ncm-cli/tokens.enc.json").write_text(
        '{"token":"newer"}'
    )
    assert save_if_changed(source, branch_state, key, initial_digest) is True
    source.joinpath(".config/ncm-cli/tokens.enc.json").write_text(
        '{"token":"stale"}'
    )
    with pytest.raises(ConcurrentUpdateError):
        save_if_changed(source, branch_state, key, initial_digest)

    restored = tmp_path / "restored"
    restore(branch_state, restored, key)
    assert restored.joinpath(".config/ncm-cli/tokens.enc.json").read_text() == '{"token":"newer"}'


def test_corrupt_state_fails_without_overwriting(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source)
    branch_state = tmp_path / "state-branch" / "auth-state.enc"
    branch_state.parent.mkdir()
    branch_state.write_bytes(b"not encrypted state")

    with pytest.raises(StateCorruptError):
        save_if_changed(source, branch_state, get_random_bytes(32))
    assert branch_state.read_bytes() == b"not encrypted state"


def test_missing_state_does_not_fallback_to_source(tmp_path: Path) -> None:
    with pytest.raises(StateMissingError):
        restore(tmp_path / "missing.enc", tmp_path / "restored", get_random_bytes(32))


def test_save_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _write_fake_state(source)

    def fail_write(path: Path, data: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(store, "_atomic_write", fail_write)
    with pytest.raises(OSError, match="synthetic write failure"):
        save_if_changed(source, tmp_path / "state-branch/auth-state.enc", get_random_bytes(32))


def test_remote_branch_lookup_distinguishes_missing_from_transport_failure() -> None:
    assert remote_state._classify_branch_lookup(0) is True
    assert remote_state._classify_branch_lookup(2) is False
    with pytest.raises(RuntimeError, match="authentication_or_permission"):
        remote_state._classify_branch_lookup(128, "fatal: authentication failed")
    with pytest.raises(RuntimeError, match="network_or_proxy"):
        remote_state._classify_branch_lookup(128, "fatal: could not connect")


def test_git_environment_does_not_log_header() -> None:
    header = "AUTHORIZATION: basic fake-header"
    git_environment = remote_state._build_git_env({"PATH": "/bin"}, header)
    assert git_environment["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert git_environment["GIT_CONFIG_VALUE_0"] == header
    assert "fake-header" not in " ".join(["git", "ls-remote"])


def test_unknown_branch_probe_failure_is_not_reported_as_missing() -> None:
    with pytest.raises(RuntimeError, match="git_command_error"):
        remote_state._classify_branch_lookup(128)


def test_remote_branch_probe_passes_git_environment_without_header_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=2, stderr="")

    git_environment = {"GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic fake"}
    monkeypatch.setattr(remote_state.subprocess, "run", fake_run)
    probe_dir = Path("/tmp/fake-state-probe")
    assert remote_state._branch_exists("https://example.invalid/repo.git", git_environment, probe_dir) is False
    assert captured["env"] is git_environment
    assert captured["cwd"] is probe_dir
    assert "AUTHORIZATION: basic fake" not in captured["command"]


def test_git_header_is_github_domain_scoped() -> None:
    header = "AUTHORIZATION: basic fake-header"
    git_environment = remote_state._build_git_env({"PATH": "/bin"}, header)
    assert git_environment["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert git_environment["GIT_CONFIG_VALUE_0"] == header


def test_remote_validation_rejects_other_hosts() -> None:
    remote_state._validate_remote("https://github.com/swamass/netease-to-spotify.git")
    remote_state._validate_remote("https://github.com/swamass/netease-to-spotify")
    with pytest.raises(RuntimeError, match="unexpected GitHub remote"):
        remote_state._validate_remote("https://example.invalid/other/repo.git")


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
