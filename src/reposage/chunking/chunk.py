import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    repo: str
    file_path: str
    language: str
    node_type: str
    start_line: int
    end_line: int
    text: str
    symbol: str | None = None
    parent_symbol: str | None = None

    @property
    def content_hash(self) -> str:
        """Short hash of `text`, used later to skip re-embedding unchanged
        chunks on repeat syncs."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:12]
