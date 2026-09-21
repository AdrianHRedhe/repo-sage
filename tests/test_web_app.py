from pathlib import Path

import pytest
from conftest import make_config
from fastapi.testclient import TestClient

from reposage.answer import Answer, Citation, SymbolRef
from reposage.config import Config
from reposage.web import app as app_module
from reposage.web.budget import BudgetGuard
from reposage.web.sandbox import (
    MAX_SANDBOX_REPOS_PER_DAY,
    SandboxState,
    _today,
    _write_slots,
)


@pytest.fixture
def client(tmp_path: Path):
    config = make_config(tmp_path)
    (config.data_dir / "repos" / "csv2md").mkdir(parents=True)

    app_module.app.dependency_overrides[app_module.get_config] = lambda: config
    app_module.app.dependency_overrides[app_module.get_embedder] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_main_store] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_llm_client] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_budget_guard] = lambda: BudgetGuard(
        tmp_path / "usage.json", hourly_limit=100, daily_limit=100
    )

    yield TestClient(app_module.app), config

    app_module.app.dependency_overrides.clear()


def _load_slots(config: Config, names: list[str]) -> list[SandboxState]:
    """Records sandbox slots straight into the state file - the clone and
    embed that submit_sandbox_repo would do are covered in
    test_web_sandbox.py and are far too heavy for a route test."""
    slots = [
        SandboxState(
            repo_owner="octocat", repo_name=name, loaded_at=_today(),
            slot_id=f"{_today()}-{i:08x}", status="ready",
        )
        for i, name in enumerate(names)
    ]
    _write_slots(config, slots)
    return slots


def _fake_answer(*args, **kwargs) -> Answer:
    return Answer(
        text="the answer",
        citations=[
            Citation(
                repo="csv2md",
                file_path="main.go",
                start_line=1,
                end_line=2,
                label="main",
                code="func main() {}",
                language="Go",
                calls=(
                    SymbolRef(
                        name="csvToMarkdown", repo="csv2md", file_path="main.go", start_line=10, end_line=20,
                        code="func csvToMarkdown() {}", language="Go",
                    ),
                ),
                called_by=(
                    SymbolRef(
                        name="unresolved", repo=None, file_path=None, start_line=None, end_line=None,
                        code=None, language=None,
                    ),
                ),
            )
        ],
    )


def test_index_serves_static_page(client) -> None:
    test_client, _ = client

    response = test_client.get("/")

    assert response.status_code == 200
    assert "RepoSage" in response.text
    # The page carries the entire client inline, so a cached copy is a
    # cached app - a deploy would not reach anyone still holding one.
    assert response.headers["cache-control"] == "no-store"


def test_api_config_reports_access_gate_state(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/config").json() == {"access_code_required": False}


def test_api_repos_lists_synced_repo_directories(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/repos").json() == {"repos": ["csv2md"]}


def test_api_sandbox_status_reports_no_slots_used_by_default(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/sandbox/status").json() == {
        "repos": [],
        "slots_used": 0,
        "slots_per_day": MAX_SANDBOX_REPOS_PER_DAY,
    }


def test_api_sandbox_status_lists_todays_repos_oldest_first(client) -> None:
    test_client, config = client
    _load_slots(config, ["one", "two"])

    body = test_client.get("/api/sandbox/status").json()

    assert [repo["repo_name"] for repo in body["repos"]] == ["one", "two"]
    assert body["slots_used"] == 2


def test_api_ask_returns_answer_shape(client, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, _ = client
    monkeypatch.setattr(app_module, "answer_question", _fake_answer)

    response = test_client.post("/api/ask", json={"question": "how does X work?"})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "the answer"
    assert body["citations"] == [
        {
            "repo": "csv2md",
            "file_path": "main.go",
            "start_line": 1,
            "end_line": 2,
            "label": "main",
            "code": "func main() {}",
            "language": "Go",
            "calls": [
                {
                    "name": "csvToMarkdown",
                    "repo": "csv2md",
                    "file_path": "main.go",
                    "start_line": 10,
                    "end_line": 20,
                    "code": "func csvToMarkdown() {}",
                    "language": "Go",
                    "url": None,
                }
            ],
            "called_by": [
                {
                    "name": "unresolved",
                    "repo": None,
                    "file_path": None,
                    "start_line": None,
                    "end_line": None,
                    "code": None,
                    "language": None,
                    "url": None,
                }
            ],
            "url": None,
        }
    ]
    assert body["related"] == []
    assert body["explored"] == []


def test_api_ask_requires_access_code_when_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path, web_access_code="secret")
    app_module.app.dependency_overrides[app_module.get_config] = lambda: config
    app_module.app.dependency_overrides[app_module.get_embedder] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_main_store] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_llm_client] = lambda: object()
    app_module.app.dependency_overrides[app_module.get_budget_guard] = lambda: BudgetGuard(
        tmp_path / "usage.json", hourly_limit=100, daily_limit=100
    )
    monkeypatch.setattr(app_module, "answer_question", _fake_answer)
    test_client = TestClient(app_module.app)

    try:
        denied = test_client.post("/api/ask", json={"question": "q"})
        assert denied.status_code == 401

        allowed = test_client.post("/api/ask", json={"question": "q"}, headers={"X-Access-Code": "secret"})
        assert allowed.status_code == 200
    finally:
        app_module.app.dependency_overrides.clear()


def test_api_ask_returns_429_when_budget_exhausted(client, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, config = client
    monkeypatch.setattr(app_module, "answer_question", _fake_answer)
    exhausted_guard = BudgetGuard(config.data_dir / "usage.json", hourly_limit=1, daily_limit=1)
    exhausted_guard.record()
    app_module.app.dependency_overrides[app_module.get_budget_guard] = lambda: exhausted_guard

    response = test_client.post("/api/ask", json={"question": "q"})

    assert response.status_code == 429


def test_api_ask_sandbox_source_without_loaded_repo_is_400(client) -> None:
    test_client, _ = client

    response = test_client.post("/api/ask", json={"question": "q", "source": "sandbox"})

    assert response.status_code == 400


def test_api_ask_sandbox_uses_the_requested_slot(client, monkeypatch: pytest.MonkeyPatch) -> None:
    test_client, config = client
    slots = _load_slots(config, ["one", "two", "three"])
    asked: list[str] = []

    def _record(config_, question, **kwargs):
        asked.append(kwargs["repo"])
        return _fake_answer()

    monkeypatch.setattr(app_module, "answer_question", _record)

    response = test_client.post(
        "/api/ask", json={"question": "q", "source": "sandbox", "sandbox_slot": slots[0].slot_id}
    )

    assert response.status_code == 200
    assert asked == ["one"]


def test_api_ask_sandbox_without_a_slot_falls_back_to_the_newest(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A client that predates the picker - or a visitor who just loaded a
    repo - gets the most recently loaded one rather than an error."""
    test_client, config = client
    _load_slots(config, ["one", "two", "three"])
    asked: list[str] = []

    def _record(config_, question, **kwargs):
        asked.append(kwargs["repo"])
        return _fake_answer()

    monkeypatch.setattr(app_module, "answer_question", _record)

    response = test_client.post("/api/ask", json={"question": "q", "source": "sandbox"})

    assert response.status_code == 200
    assert asked == ["three"]


def test_api_ask_sandbox_with_an_unknown_slot_is_400(client) -> None:
    test_client, config = client
    _load_slots(config, ["one"])

    response = test_client.post(
        "/api/ask", json={"question": "q", "source": "sandbox", "sandbox_slot": "1999-01-01-deadbeef"}
    )

    assert response.status_code == 400
