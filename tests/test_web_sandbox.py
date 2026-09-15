from pathlib import Path

import pytest
from conftest import make_config

import reposage.web.sandbox as sandbox_module
from reposage.web.sandbox import (
    SandboxError,
    SandboxState,
    cleanup_sandbox,
    parse_github_repo_url,
    read_sandbox_state,
    sandbox_config_for,
    submit_sandbox_repo,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/octocat/hello-world", ("octocat", "hello-world")),
        ("https://github.com/octocat/hello-world.git", ("octocat", "hello-world")),
        ("https://github.com/octocat/hello-world/", ("octocat", "hello-world")),
    ],
)
def test_parse_github_repo_url_accepts_valid_shapes(url: str, expected: tuple[str, str]) -> None:
    assert parse_github_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:octocat/hello-world.git",
        "https://gitlab.com/octocat/hello-world",
        "https://github.com/octocat",
        "not a url",
        "https://github.com/../../etc",
    ],
)
def test_parse_github_repo_url_rejects_everything_else(url: str) -> None:
    with pytest.raises(SandboxError):
        parse_github_repo_url(url)


def test_read_sandbox_state_returns_none_when_absent(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert read_sandbox_state(config) is None


def test_cleanup_sandbox_is_safe_when_nothing_exists(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    cleanup_sandbox(config)  # should not raise

    assert read_sandbox_state(config) is None


def test_write_then_read_state_round_trip(tmp_path: Path) -> None:
    from reposage.web.sandbox import _write_state

    config = make_config(tmp_path)
    state = SandboxState(
        repo_owner="octocat", repo_name="hello-world", loaded_at="2026-01-01", slot_id="2026-01-01-aaaaaaaa", status="ready"
    )

    _write_state(config, state)

    assert read_sandbox_state(config) == state


def test_sandbox_config_for_gives_each_slot_a_distinct_data_dir(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    slot_one = sandbox_config_for(config, "2026-01-01-aaaaaaaa")
    slot_two = sandbox_config_for(config, "2026-01-01-bbbbbbbb")

    assert slot_one.chroma_dir != slot_two.chroma_dir
    assert slot_one.repos_dir != slot_two.repos_dir


def test_cleanup_removes_only_the_recorded_slot_directory(tmp_path: Path) -> None:
    from reposage.web.sandbox import _write_state

    config = make_config(tmp_path)
    state = SandboxState(
        repo_owner="octocat", repo_name="hello-world", loaded_at="2026-01-01", slot_id="2026-01-01-aaaaaaaa", status="ready"
    )
    _write_state(config, state)
    slot_config = sandbox_config_for(config, state.slot_id)
    slot_config.repos_dir.mkdir(parents=True)
    (slot_config.repos_dir / "marker.txt").write_text("x")

    cleanup_sandbox(config)

    assert not slot_config.repos_dir.exists()
    assert read_sandbox_state(config) is None


def test_retry_after_a_same_day_failure_gets_a_fresh_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression test: a failed attempt (e.g. too-large repo) must not
    leave behind a slot that a same-day retry then reopens - reopening a
    deleted chromadb persist path within one process previously caused a
    'readonly database' error (found via live testing, not by inspection)."""
    config = make_config(tmp_path)
    monkeypatch.setattr(sandbox_module, "clone_or_update", lambda *a, **k: None)
    monkeypatch.setattr(sandbox_module, "index_repo", lambda *a, **k: None)

    file_counts = iter([sandbox_module.MAX_SANDBOX_FILES + 1, 5])
    monkeypatch.setattr(sandbox_module, "list_included_files", lambda repo_path: [None] * next(file_counts))

    with pytest.raises(SandboxError, match="too large"):
        submit_sandbox_repo(config, "https://github.com/octocat/big-repo")

    failed_slots = list((config.data_dir / "sandbox").glob("*")) if (config.data_dir / "sandbox").exists() else []
    assert not any(p.is_dir() and p.name != "state.json" for p in failed_slots)

    state = submit_sandbox_repo(config, "https://github.com/octocat/small-repo")

    assert state.repo_name == "small-repo"
    assert sandbox_config_for(config, state.slot_id).repos_dir.parent.exists()
