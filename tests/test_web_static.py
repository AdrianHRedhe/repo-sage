from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "reposage" / "web" / "static"

STATIC_FILES = sorted(p for p in STATIC_DIR.rglob("*") if p.is_file())


def _ids(paths: list[Path]) -> list[str]:
    return [str(p.relative_to(STATIC_DIR)) for p in paths]


def test_static_dir_is_not_empty() -> None:
    """Guards the sweeps below: an empty glob would pass them vacuously."""
    assert STATIC_FILES


@pytest.mark.parametrize("path", STATIC_FILES, ids=_ids(STATIC_FILES))
def test_static_file_contains_no_nul_bytes(path: Path) -> None:
    """These files are served as text and have to stay greppable.

    Guards the escaped-NUL sentinel in index.html's renderAnswerMarkdown -
    see the comment there for why it must stay escaped.
    """
    assert b"\x00" not in path.read_bytes()


@pytest.mark.parametrize("path", STATIC_FILES, ids=_ids(STATIC_FILES))
def test_static_file_decodes_as_utf8(path: Path) -> None:
    path.read_bytes().decode("utf-8")
