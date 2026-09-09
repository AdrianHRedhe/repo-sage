import subprocess
from pathlib import Path

from reposage.filters.include import list_included_files


def _init_fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    (repo / ".gitignore").write_text("node_modules/\n")

    (repo / "main.py").write_text("print('hello')\n")

    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("module.exports = {};\n")

    (repo / "package-lock.json").write_text("{}\n")

    (repo / "bundle.min.js").write_text("!function(){}();\n")

    (repo / "logo.png").write_bytes(b"\x89PNG\r\n")

    return repo


def test_list_included_files_applies_all_filters(tmp_path: Path) -> None:
    repo = _init_fixture_repo(tmp_path)

    included = list_included_files(repo)

    assert included == [Path("main.py")]
