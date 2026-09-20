from pathlib import Path

from conftest import make_config

from reposage.chunking.chunk import Chunk
from reposage.index import prune_missing_repos
from reposage.store.chroma_store import ChromaStore


def _chunk(repo: str, symbol: str) -> Chunk:
    return Chunk(
        repo=repo,
        file_path="main.py",
        language="Python",
        node_type="function",
        start_line=1,
        end_line=2,
        text="body",
        symbol=symbol,
    )


def test_prune_drops_chunks_for_repos_no_longer_synced(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    store = ChromaStore(config.chroma_dir)
    store.upsert(
        [_chunk("still-here", "one"), _chunk("gone", "two")],
        [[1.0, 0.0], [0.0, 1.0]],
    )

    assert prune_missing_repos(config, ["still-here"]) == {"gone": 1}

    assert ChromaStore(config.chroma_dir).repos() == {"still-here"}


def test_prune_leaves_a_fully_synced_store_alone(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    store = ChromaStore(config.chroma_dir)
    store.upsert([_chunk("alpha", "one")], [[1.0, 0.0]])

    assert prune_missing_repos(config, ["alpha"]) == {}

    assert ChromaStore(config.chroma_dir).repos() == {"alpha"}
