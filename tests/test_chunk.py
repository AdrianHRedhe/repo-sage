from reposage.chunking.chunk import Chunk


def _chunk(**overrides) -> Chunk:
    base = dict(
        repo="repo",
        file_path="main.py",
        language="Python",
        node_type="function",
        start_line=1,
        end_line=2,
        text="def foo(): pass",
        symbol="foo",
    )
    return Chunk(**{**base, **overrides})


def test_embedding_text_is_plain_text_without_lineage() -> None:
    chunk = _chunk()

    assert chunk.embedding_text == chunk.text


def test_embedding_text_appends_calls_and_called_by() -> None:
    chunk = _chunk(calls=("bar", "baz"), called_by=("main",))

    assert chunk.embedding_text == "def foo(): pass\n\nCalls: bar, baz\n\nCalled by: main"


def test_content_hash_changes_when_lineage_changes_but_text_does_not() -> None:
    without_lineage = _chunk()
    with_lineage = _chunk(calls=("bar",))

    assert without_lineage.content_hash != with_lineage.content_hash


def test_content_hash_stable_for_identical_chunks() -> None:
    assert _chunk().content_hash == _chunk().content_hash
