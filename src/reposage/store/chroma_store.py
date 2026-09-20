from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from reposage.chunking.chunk import Chunk

COLLECTION_NAME = "chunks"


def chunk_id(chunk: Chunk) -> str:
    symbol = chunk.symbol or "window"
    return f"{chunk.repo}/{chunk.file_path}::{symbol}@{chunk.start_line}"


class ChromaStore:
    """Wraps a single local Chroma collection holding chunks from every
    synced repo together, so a query can search across a person's whole
    body of work (optionally narrowed with `repo` filters)."""

    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        # Chroma defaults to sending anonymized usage telemetry - opt out to
        # keep this tool's "everything stays local" promise honest.
        client = chromadb.PersistentClient(
            path=str(persist_dir), settings=Settings(anonymized_telemetry=False)
        )
        self._collection = client.get_or_create_collection(COLLECTION_NAME)

    def existing_hashes(self, repo: str, file_path: str) -> dict[str, str]:
        """id -> content_hash for everything currently stored for this file."""
        result = self._collection.get(
            where={"$and": [{"repo": repo}, {"file_path": file_path}]},
            include=["metadatas"],
        )
        return {id_: metadata["content_hash"] for id_, metadata in zip(result["ids"], result["metadatas"])}

    def delete(self, ids: list[str]) -> None:
        if ids:
            self._collection.delete(ids=ids)

    def repos(self) -> set[str]:
        """Every repo name that currently has chunks stored."""
        result = self._collection.get(include=["metadatas"])
        return {metadata["repo"] for metadata in result["metadatas"]}

    def delete_repo(self, repo: str) -> int:
        """Delete every chunk belonging to `repo`, returning how many went.

        index_repo only ever reconciles files it can still see, so a repo
        that stops being synced altogether leaves its chunks behind - still
        searchable, still cited, pointing at code no longer on disk.
        """
        existing = self._collection.get(where={"repo": repo})
        self.delete(existing["ids"])
        return len(existing["ids"])

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if not chunks:
            return

        self._collection.upsert(
            ids=[chunk_id(c) for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "repo": c.repo,
                    "file_path": c.file_path,
                    "language": c.language,
                    "node_type": c.node_type,
                    "symbol": c.symbol or "",
                    "parent_symbol": c.parent_symbol or "",
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "content_hash": c.content_hash,
                    "calls": ",".join(c.calls),
                    "called_by": ",".join(c.called_by),
                }
                for c in chunks
            ],
        )

    def query(self, query_embedding: list[float], n_results: int, repo: str | None = None) -> dict[str, Any]:
        return self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"repo": repo} if repo else None,
        )

    def get_by_symbol(self, repo: str, symbol: str) -> dict[str, Any] | None:
        """The first stored chunk defining `symbol` in `repo`, or None.

        Used to hydrate a retrieved chunk's callers/callees with their
        actual code for LLM context - lookup by name, not by embedding
        similarity, since we already know exactly which chunk we want."""
        result = self._collection.get(
            where={"$and": [{"repo": repo}, {"symbol": symbol}]},
            include=["documents", "metadatas"],
            limit=1,
        )
        if not result["ids"]:
            return None
        return {
            "id": result["ids"][0],
            "document": result["documents"][0],
            "metadata": result["metadatas"][0],
        }
