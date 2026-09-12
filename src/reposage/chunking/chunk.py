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


def format_symbol_label(symbol: str | None, parent_symbol: str | None) -> str:
    """Human-readable label for a chunk, e.g. "MyClass.my_method" or
    "(file)" for whole-file fallback chunks."""
    label = symbol or "(file)"
    if parent_symbol:
        label = f"{parent_symbol}.{label}"
    return label
