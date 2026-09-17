import subprocess
from pathlib import Path

from reposage.web.links import github_blob_url


def _init_git_repo(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--quiet"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "main.go").write_text("package main\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "init"], cwd=path, check=True
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    ).stdout.strip()
    return sha


def test_github_blob_url_anchors_a_single_line(tmp_path: Path) -> None:
    sha = _init_git_repo(tmp_path / "csv2md")

    url = github_blob_url(tmp_path, "octocat", "csv2md", "main.go", 3, 3)

    assert url == f"https://github.com/octocat/csv2md/blob/{sha}/main.go#L3"


def test_github_blob_url_anchors_a_line_range(tmp_path: Path) -> None:
    sha = _init_git_repo(tmp_path / "csv2md")

    url = github_blob_url(tmp_path, "octocat", "csv2md", "main.go", 3, 7)

    assert url == f"https://github.com/octocat/csv2md/blob/{sha}/main.go#L3-L7"


def test_github_blob_url_is_none_when_not_a_git_checkout(tmp_path: Path) -> None:
    (tmp_path / "csv2md").mkdir()

    assert github_blob_url(tmp_path, "octocat", "csv2md", "main.go", 1, 1) is None


def test_github_blob_url_is_none_when_repo_dir_is_missing(tmp_path: Path) -> None:
    assert github_blob_url(tmp_path, "octocat", "missing-repo", "main.go", 1, 1) is None
