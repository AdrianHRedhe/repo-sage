import subprocess
from pathlib import Path

from reposage.filters.languages import EXTENSION_LANGUAGE
from reposage.sync import SPARSE_CHECKOUT_PATTERNS, clone_or_update


def _url(origin: Path) -> str:
    """git ignores --filter for plain local-path clones ("use file://
    instead"), so the tests have to speak the same transport shape the
    real https remote does."""
    return f"file://{origin}"


def _run(command: list[str], cwd: Path) -> str:
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout


def _make_origin(path: Path) -> Path:
    """A real local repo holding one source file and one 'image', so the
    sparse/blobless behaviour is exercised against git itself rather than a
    mock - the whole feature is which flags git gets, which a mock of
    subprocess.run would assert without proving anything."""
    path.mkdir(parents=True)
    _run(["git", "init", "-b", "main"], path)
    _run(["git", "config", "user.email", "test@example.com"], path)
    _run(["git", "config", "user.name", "Test"], path)
    # Partial clone over the local transport is silently ignored unless the
    # origin opts in. github.com has this enabled.
    _run(["git", "config", "uploadpack.allowFilter", "true"], path)

    (path / "keep.py").write_text("def hello():\n    return 1\n")
    (path / "photo.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 50_000)
    _run(["git", "add", "-A"], path)
    _run(["git", "commit", "-m", "initial"], path)
    return path


def _missing_object_count(repo: Path) -> int:
    """How many objects the clone knows about but has not downloaded."""
    output = _run(
        ["git", "rev-list", "--objects", "--all", "--missing=print"],
        repo,
    )
    return sum(1 for line in output.splitlines() if line.startswith("?"))


def test_sparse_patterns_cover_every_known_extension() -> None:
    for extension in EXTENSION_LANGUAGE:
        assert f"*{extension}" in SPARSE_CHECKOUT_PATTERNS


def test_sparse_clone_materialises_only_chunkable_files(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path / "origin")
    dest = tmp_path / "clone"

    clone_or_update("demo", _url(origin), dest, sparse_patterns=SPARSE_CHECKOUT_PATTERNS)

    assert (dest / "keep.py").exists()
    assert not (dest / "photo.jpg").exists()


def test_sparse_clone_never_downloads_the_excluded_blob(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path / "origin")
    dest = tmp_path / "clone"

    clone_or_update("demo", _url(origin), dest, sparse_patterns=SPARSE_CHECKOUT_PATTERNS)

    # The point of --filter=blob:none: the excluded file is absent from the
    # working tree *and* was never fetched. Leaving it out of the checkout
    # alone would still have paid for the download.
    assert _missing_object_count(dest) == 1


def test_plain_clone_still_downloads_everything(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path / "origin")
    dest = tmp_path / "clone"

    clone_or_update("demo", _url(origin), dest)

    assert (dest / "photo.jpg").exists()
    assert _missing_object_count(dest) == 0


def test_existing_sparse_clone_is_fast_forwarded_not_recloned(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path / "origin")
    dest = tmp_path / "clone"
    clone_or_update("demo", _url(origin), dest, sparse_patterns=SPARSE_CHECKOUT_PATTERNS)

    marker = dest / ".git" / "reposage-marker"
    marker.write_text("survives an update")
    (origin / "added.py").write_text("def added():\n    return 2\n")
    _run(["git", "add", "-A"], origin)
    _run(["git", "commit", "-m", "second"], origin)

    clone_or_update("demo", _url(origin), dest, sparse_patterns=SPARSE_CHECKOUT_PATTERNS)

    assert (dest / "added.py").exists()
    assert marker.exists()


def test_legacy_full_clone_is_replaced_with_a_sparse_one(tmp_path: Path) -> None:
    origin = _make_origin(tmp_path / "origin")
    dest = tmp_path / "clone"
    clone_or_update("demo", _url(origin), dest)
    assert (dest / "photo.jpg").exists()

    clone_or_update("demo", _url(origin), dest, sparse_patterns=SPARSE_CHECKOUT_PATTERNS)

    # A pull would have left the already-downloaded blobs on disk forever,
    # so an existing full clone has to be thrown away to benefit at all.
    assert not (dest / "photo.jpg").exists()
    assert (dest / "keep.py").exists()
