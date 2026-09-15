from reposage.callgraph import MAX_LINEAGE_NAMES, attach_lineage
from reposage.chunking.chunk import Chunk
from reposage.store.chroma_store import chunk_id


def _go_chunk(symbol: str, text: str, file_path: str = "main.go", start_line: int = 1) -> Chunk:
    return Chunk(
        repo="repo",
        file_path=file_path,
        language="Go",
        node_type="function",
        start_line=start_line,
        end_line=start_line + text.count("\n"),
        text=text,
        symbol=symbol,
    )


def test_attach_lineage_resolves_caller_and_callee_across_files() -> None:
    caller = _go_chunk("main", "func main() {\n\thelper()\n}", file_path="main.go")
    callee = _go_chunk("helper", "func helper() {}", file_path="util.go")
    unrelated = _go_chunk("Unrelated", "func Unrelated() {}", file_path="util.go")

    enriched = attach_lineage([caller, callee, unrelated])

    assert enriched[chunk_id(caller)].calls == ("helper",)
    assert enriched[chunk_id(callee)].called_by == ("main",)
    assert enriched[chunk_id(unrelated)].calls == ()
    assert enriched[chunk_id(unrelated)].called_by == ()


def test_attach_lineage_excludes_self_recursion() -> None:
    recursive = _go_chunk("recurse", "func recurse() {\n\trecurse()\n}")

    enriched = attach_lineage([recursive])

    assert enriched[chunk_id(recursive)].calls == ()
    assert enriched[chunk_id(recursive)].called_by == ()


def test_attach_lineage_leaves_chunks_without_a_call_query_untouched() -> None:
    scala_chunk = Chunk(
        repo="repo",
        file_path="Main.scala",
        language="Scala",
        node_type="function",
        start_line=1,
        end_line=1,
        text="def foo() = bar()",
        symbol="foo",
    )

    enriched = attach_lineage([scala_chunk])

    assert enriched[chunk_id(scala_chunk)].calls == ()


def test_attach_lineage_caps_lineage_size() -> None:
    caller_body = "func main() {\n" + "\n".join(f"\thelper{i}()" for i in range(MAX_LINEAGE_NAMES + 5)) + "\n}"
    caller = _go_chunk("main", caller_body)
    callees = [_go_chunk(f"helper{i}", f"func helper{i}() {{}}", start_line=i + 2) for i in range(MAX_LINEAGE_NAMES + 5)]

    enriched = attach_lineage([caller, *callees])

    assert len(enriched[chunk_id(caller)].calls) == MAX_LINEAGE_NAMES
