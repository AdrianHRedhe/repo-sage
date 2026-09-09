from pathlib import Path

from reposage.chunking.chunk import Chunk
from reposage.store.chroma_store import ChromaStore, chunk_id


def _chunk(symbol: str, text: str = "body") -> Chunk:
    return Chunk(
        repo="repo",
        file_path="main.py",
        language="Python",
        node_type="function",
        start_line=1,
        end_line=2,
        text=text,
        symbol=symbol,
    )


def test_upsert_and_query_roundtrip(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path / "chroma")
    chunk = _chunk("foo")

    store.upsert([chunk], [[1.0, 0.0]])
    result = store.query([1.0, 0.0], n_results=1)

    assert result["ids"][0] == [chunk_id(chunk)]
    assert result["metadatas"][0][0]["symbol"] == "foo"


def test_existing_hashes_reflects_only_that_file(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path / "chroma")
    in_file = _chunk("foo")
    other_file = Chunk(
        repo="repo", file_path="other.py", language="Python", node_type="function",
        start_line=1, end_line=2, text="body", symbol="bar",
    )

    store.upsert([in_file, other_file], [[1.0, 0.0], [0.0, 1.0]])

    hashes = store.existing_hashes("repo", "main.py")

    assert hashes == {chunk_id(in_file): in_file.content_hash}


def test_delete_removes_chunks(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path / "chroma")
    chunk = _chunk("foo")
    store.upsert([chunk], [[1.0, 0.0]])

    store.delete([chunk_id(chunk)])

    assert store.existing_hashes("repo", "main.py") == {}


def test_query_can_be_filtered_by_repo(tmp_path: Path) -> None:
    store = ChromaStore(tmp_path / "chroma")
    mine = _chunk("foo")
    other_repo = Chunk(
        repo="other-repo", file_path="main.py", language="Python", node_type="function",
        start_line=1, end_line=2, text="body", symbol="foo",
    )
    store.upsert([mine, other_repo], [[1.0, 0.0], [1.0, 0.0]])

    result = store.query([1.0, 0.0], n_results=10, repo="repo")

    assert result["ids"][0] == [chunk_id(mine)]
