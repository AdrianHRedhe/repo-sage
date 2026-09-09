from reposage.chunking.fallback import OVERLAP_LINES, WINDOW_LINES, chunk_with_fallback


def test_small_file_produces_a_single_chunk() -> None:
    source = b"line one\nline two\nline three\n"

    chunks = chunk_with_fallback("repo", "notes.md", "Markdown", source)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.node_type == "window"
    assert chunk.start_line == 1
    assert chunk.end_line == 3
    assert chunk.text == "line one\nline two\nline three"


def test_large_file_splits_into_overlapping_windows() -> None:
    line_count = WINDOW_LINES + 50
    source = "\n".join(f"line {i}" for i in range(line_count)).encode("utf-8")

    chunks = chunk_with_fallback("repo", "big.md", "Markdown", source)

    assert len(chunks) == 2
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == WINDOW_LINES
    assert chunks[1].start_line == WINDOW_LINES - OVERLAP_LINES + 1
    assert chunks[1].end_line == line_count


def test_empty_file_produces_no_chunks() -> None:
    assert chunk_with_fallback("repo", "empty.md", "Markdown", b"") == []
