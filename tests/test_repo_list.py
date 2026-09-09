from pathlib import Path

from reposage.repo_list import load_repo_names


def test_parses_names_and_ignores_comments_and_blanks(tmp_path: Path) -> None:
    repos_file = tmp_path / "repos.txt"
    repos_file.write_text(
        "# a comment\n"
        "\n"
        "repo-one\n"
        "repo-two  # inline comment\n"
        "   \n"
    )

    assert load_repo_names(repos_file) == ["repo-one", "repo-two"]


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert load_repo_names(tmp_path / "does-not-exist.txt") == []


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    repos_file = tmp_path / "repos.txt"
    repos_file.write_text("# just comments\n")

    assert load_repo_names(repos_file) == []
