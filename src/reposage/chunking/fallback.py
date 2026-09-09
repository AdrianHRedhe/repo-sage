from reposage.chunking.chunk import Chunk

WINDOW_LINES = 200
OVERLAP_LINES = 20


def chunk_with_fallback(repo: str, file_path: str, language: str, source: bytes) -> list[Chunk]:
    """Naive fixed-line-window chunking with overlap, for languages without
    a tree-sitter query yet (and non-code files like Markdown). Guarantees
    every included file produces at least one chunk regardless of query
    coverage."""
    lines = source.decode("utf-8", errors="replace").splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + WINDOW_LINES, len(lines))
        chunks.append(
            Chunk(
                repo=repo,
                file_path=file_path,
                language=language,
                node_type="window",
                start_line=start + 1,
                end_line=end,
                text="\n".join(lines[start:end]),
            )
        )
        if end == len(lines):
            break
        start = end - OVERLAP_LINES

    return chunks
