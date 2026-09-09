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
