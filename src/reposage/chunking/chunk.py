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
    # Heuristic caller/callee lineage (reposage/callgraph.py), populated
    # after chunking by matching call-site identifier names elsewhere in
    # the repo - not part of the raw source, so kept separate from `text`.
    calls: tuple[str, ...] = ()
    called_by: tuple[str, ...] = ()

    @property
    def content_hash(self) -> str:
        """Short hash of everything that should trigger re-embedding when
        it changes: the chunk's own text, plus its resolved lineage (so a
        newly-added/removed caller or callee also invalidates the cached
        embedding, not just edits to this chunk's own body)."""
        payload = "\x00".join([self.text, ",".join(self.calls), ",".join(self.called_by)])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    @property
    def embedding_text(self) -> str:
        """Text actually handed to the embedding model: the chunk's source
        plus a short line naming its immediate callers/callees, if any.

        Deliberately just names, not their full bodies - blending several
        unrelated functions' text into one vector would dilute it and hurt
        retrieval precision for the chunk itself. Full caller/callee bodies
        are instead hydrated as extra LLM context after retrieval, in
        reposage/answer.py, once we already know which chunk mattered."""
        lines = [self.text]
        if self.calls:
            lines.append(f"Calls: {', '.join(self.calls)}")
        if self.called_by:
            lines.append(f"Called by: {', '.join(self.called_by)}")
        return "\n\n".join(lines)


def format_symbol_label(symbol: str | None, parent_symbol: str | None) -> str:
    """Human-readable label for a chunk, e.g. "MyClass.my_method" or
    "(file)" for whole-file fallback chunks."""
    label = symbol or "(file)"
    if parent_symbol:
        label = f"{parent_symbol}.{label}"
    return label
