import subprocess
from pathlib import Path

from reposage.config import Config
from reposage.tools import list_files_tool, read_file_tool, run_tool


def _config(tmp_path: Path) -> Config:
    return Config(
        github_user="octocat",
        github_token="",
        data_dir=tmp_path,
        repos_file=tmp_path / "repos.txt",
        embedding_model="unused",
        ollama_model="unused",
        ollama_base_url="http://unused",
    )


def _init_repo(tmp_path: Path, name: str) -> Path:
    repo_path = tmp_path / "repos" / name
    repo_path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo_path)], check=True)
    return repo_path


def test_list_files_tool_lists_chunkable_files(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path, "myrepo")
    (repo_path / "main.py").write_text("print(1)\n")
    (repo_path / "notes.txt").write_text("not a source extension\n")

    assert list_files_tool(_config(tmp_path), "myrepo") == "main.py"


def test_list_files_tool_rejects_unknown_repo(tmp_path: Path) -> None:
    (tmp_path / "repos").mkdir()

    assert list_files_tool(_config(tmp_path), "missing") == "Error: unknown repo 'missing'"


def test_read_file_tool_returns_requested_line_range(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path, "myrepo")
    (repo_path / "main.py").write_text("one\ntwo\nthree\nfour\n")

    result = read_file_tool(_config(tmp_path), "myrepo", "main.py", start_line=2, end_line=3)

    assert result == "myrepo/main.py:2-3\ntwo\nthree"


def test_read_file_tool_defaults_to_whole_file(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path, "myrepo")
    (repo_path / "main.py").write_text("one\ntwo\n")

    result = read_file_tool(_config(tmp_path), "myrepo", "main.py")

    assert result == "myrepo/main.py:1-2\none\ntwo"


def test_read_file_tool_rejects_missing_file(tmp_path: Path) -> None:
    _init_repo(tmp_path, "myrepo")

    result = read_file_tool(_config(tmp_path), "myrepo", "missing.py")

    assert result == "Error: 'missing.py' not found in repo 'myrepo'."


def test_read_file_tool_rejects_path_traversal(tmp_path: Path) -> None:
    _init_repo(tmp_path, "myrepo")
    (tmp_path / "secret.txt").write_text("outside the repo\n")

    result = read_file_tool(_config(tmp_path), "myrepo", "../secret.txt")

    assert result == "Error: path '../secret.txt' escapes the repo"


def test_run_tool_dispatches_by_name(tmp_path: Path) -> None:
    repo_path = _init_repo(tmp_path, "myrepo")
    (repo_path / "main.py").write_text("print(1)\n")

    assert run_tool(_config(tmp_path), "list_files", {"repo": "myrepo"}) == "main.py"


def test_run_tool_rejects_unknown_tool_name(tmp_path: Path) -> None:
    assert run_tool(_config(tmp_path), "delete_repo", {}) == "Error: unknown tool 'delete_repo'"
