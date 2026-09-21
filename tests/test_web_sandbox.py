from pathlib import Path

import pytest
from conftest import make_config

import reposage.web.sandbox as sandbox_module
from reposage.web.sandbox import (
    MAX_SANDBOX_REPOS_PER_DAY,
    SandboxError,
    SandboxState,
    cleanup_sandbox,
    find_slot,
    parse_github_repo_url,
    read_sandbox_slots,
    sandbox_config_for,
    submit_sandbox_repo,
    todays_slots,
)


def _state(name: str, *, owner: str = "octocat", date: str = "2026-01-01", suffix: str = "aaaaaaaa") -> SandboxState:
    return SandboxState(
        repo_owner=owner, repo_name=name, loaded_at=date, slot_id=f"{date}-{suffix}", status="ready"
    )


def _accept_every_submission(monkeypatch: pytest.MonkeyPatch, today: str = "2026-01-01") -> None:
    """Stubs out the expensive half of submit_sandbox_repo (clone, file
    scan, embed) so a test can exercise the slot bookkeeping alone."""
    monkeypatch.setattr(sandbox_module, "clone_or_update", lambda *a, **k: None)
    monkeypatch.setattr(sandbox_module, "index_repo", lambda *a, **k: None)
    monkeypatch.setattr(sandbox_module, "list_included_files", lambda repo_path: [None] * 5)
    monkeypatch.setattr(sandbox_module, "_today", lambda: today)


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
        "https://github.com/octocat/..",
        "https://github.com/../octocat",
        "https://github.com/./hello-world",
    ],
)
def test_parse_github_repo_url_rejects_everything_else(url: str) -> None:
    with pytest.raises(SandboxError):
        parse_github_repo_url(url)


def test_read_sandbox_slots_is_empty_when_absent(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert read_sandbox_slots(config) == []


def test_cleanup_sandbox_is_safe_when_nothing_exists(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    cleanup_sandbox(config)  # should not raise

    assert read_sandbox_slots(config) == []


def test_write_then_read_slots_round_trip(tmp_path: Path) -> None:
    from reposage.web.sandbox import _write_slots

    config = make_config(tmp_path)
    slots = [_state("hello-world", suffix="aaaaaaaa"), _state("goodbye-world", suffix="bbbbbbbb")]

    _write_slots(config, slots)

    assert read_sandbox_slots(config) == slots


def test_read_slots_accepts_the_legacy_single_object_state_file(tmp_path: Path) -> None:
    """The state file lives in a named volume that survives rebuilds, so
    the first read after upgrading a running deployment sees the old
    one-object-per-file shape rather than a list."""
    import json
    from dataclasses import asdict

    config = make_config(tmp_path)
    legacy = _state("hello-world")
    path = config.data_dir / "sandbox" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(legacy)))

    assert read_sandbox_slots(config) == [legacy]


def test_sandbox_config_for_gives_each_slot_a_distinct_data_dir(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    slot_one = sandbox_config_for(config, "2026-01-01-aaaaaaaa")
    slot_two = sandbox_config_for(config, "2026-01-01-bbbbbbbb")

    assert slot_one.chroma_dir != slot_two.chroma_dir
    assert slot_one.repos_dir != slot_two.repos_dir


def test_cleanup_removes_every_recorded_slot_directory(tmp_path: Path) -> None:
    from reposage.web.sandbox import _write_slots

    config = make_config(tmp_path)
    slots = [_state("hello-world", suffix="aaaaaaaa"), _state("goodbye-world", suffix="bbbbbbbb")]
    _write_slots(config, slots)
    slot_configs = [sandbox_config_for(config, slot.slot_id) for slot in slots]
    for slot_config in slot_configs:
        slot_config.repos_dir.mkdir(parents=True)
        (slot_config.repos_dir / "marker.txt").write_text("x")

    cleanup_sandbox(config)

    assert not any(slot_config.repos_dir.exists() for slot_config in slot_configs)
    assert read_sandbox_slots(config) == []


def test_several_repos_load_into_separate_slots_on_the_same_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    _accept_every_submission(monkeypatch)

    for name in ("one", "two", "three"):
        submit_sandbox_repo(config, f"https://github.com/octocat/{name}")

    loaded = todays_slots(config)
    assert [slot.repo_name for slot in loaded] == ["one", "two", "three"]
    assert len({slot.slot_id for slot in loaded}) == MAX_SANDBOX_REPOS_PER_DAY


def test_submission_past_the_daily_limit_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path)
    _accept_every_submission(monkeypatch)
    for i in range(MAX_SANDBOX_REPOS_PER_DAY):
        submit_sandbox_repo(config, f"https://github.com/octocat/repo{i}")

    with pytest.raises(SandboxError, match="slots for today are taken"):
        submit_sandbox_repo(config, "https://github.com/octocat/one-too-many")

    assert len(todays_slots(config)) == MAX_SANDBOX_REPOS_PER_DAY


def test_resubmitting_a_loaded_repo_returns_it_without_taking_a_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    _accept_every_submission(monkeypatch)
    first = submit_sandbox_repo(config, "https://github.com/octocat/one")

    again = submit_sandbox_repo(config, "https://github.com/octocat/one")

    assert again == first
    assert len(todays_slots(config)) == 1


def test_same_name_from_a_different_owner_is_a_separate_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slots are keyed by owner *and* name: two different people's `utils`
    are two different repos, and the visitor picks between them by
    slot_id, not by name."""
    config = make_config(tmp_path)
    _accept_every_submission(monkeypatch)

    submit_sandbox_repo(config, "https://github.com/octocat/utils")
    submit_sandbox_repo(config, "https://github.com/hubot/utils")

    loaded = todays_slots(config)
    assert [(slot.repo_owner, slot.repo_name) for slot in loaded] == [("octocat", "utils"), ("hubot", "utils")]
    assert loaded[0].slot_id != loaded[1].slot_id


def test_first_submission_of_a_new_day_clears_every_previous_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = make_config(tmp_path)
    _accept_every_submission(monkeypatch, today="2026-01-01")
    for name in ("one", "two"):
        submit_sandbox_repo(config, f"https://github.com/octocat/{name}")
    yesterdays = [sandbox_config_for(config, slot.slot_id) for slot in todays_slots(config)]

    monkeypatch.setattr(sandbox_module, "_today", lambda: "2026-01-02")
    submit_sandbox_repo(config, "https://github.com/octocat/fresh")

    assert [slot.repo_name for slot in todays_slots(config)] == ["fresh"]
    assert not any(slot_config.repos_dir.exists() for slot_config in yesterdays)


def test_yesterdays_slots_are_not_askable_even_before_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expiry only runs on the next submission, so a stale slot is still
    on disk the morning after. `todays_slots`/`find_slot` are what stop
    /api/ask offering it."""
    from reposage.web.sandbox import _write_slots

    config = make_config(tmp_path)
    stale = _state("hello-world", date="2026-01-01")
    _write_slots(config, [stale])
    monkeypatch.setattr(sandbox_module, "_today", lambda: "2026-01-02")

    assert read_sandbox_slots(config) == [stale]
    assert todays_slots(config) == []
    assert find_slot(config, stale.slot_id) is None


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


def test_submit_rejects_a_repo_name_that_escapes_the_sandbox_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defense-in-depth: even if parse_github_repo_url's regex ever let a
    dangerous name (e.g. "..") through, submit_sandbox_repo independently
    verifies the resulting clone path stays inside repos_dir before
    touching the filesystem - the same belt-and-suspenders pattern
    reposage/tools.py uses for read_file/list_files."""
    config = make_config(tmp_path)
    monkeypatch.setattr(sandbox_module, "parse_github_repo_url", lambda url: ("octocat", ".."))
    monkeypatch.setattr(sandbox_module, "clone_or_update", lambda *a, **k: pytest.fail("should never clone"))

    with pytest.raises(SandboxError, match="Invalid repo name"):
        submit_sandbox_repo(config, "https://github.com/octocat/whatever")
