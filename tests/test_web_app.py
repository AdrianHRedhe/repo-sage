from pathlib import Path

import pytest
from conftest import make_config
from fastapi.testclient import TestClient

from reposage.answer import Answer, Citation, SymbolRef
from reposage.web import app as app_module
from reposage.web.budget import BudgetGuard


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


def test_api_config_reports_access_gate_state(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/config").json() == {"access_code_required": False}


def test_api_repos_lists_synced_repo_directories(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/repos").json() == {"repos": ["csv2md"]}


def test_api_sandbox_status_reports_unloaded_by_default(client) -> None:
    test_client, _ = client

    assert test_client.get("/api/sandbox/status").json() == {"loaded": False}


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
