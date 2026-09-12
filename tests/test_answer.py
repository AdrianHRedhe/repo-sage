from reposage.answer import _build_prompt


def _metadata(**overrides) -> dict:
    base = {
        "repo": "csv2md",
        "file_path": "main.go",
        "symbol": "Convert",
        "parent_symbol": "",
        "start_line": 10,
        "end_line": 20,
    }
    return {**base, **overrides}


def test_prompt_includes_question_and_numbered_context() -> None:
    prompt = _build_prompt("how does X work?", ["func body"], [_metadata()])

    assert "Question: how does X work?" in prompt
    assert "[1] csv2md/main.go:10-20 (Convert)" in prompt
    assert "func body" in prompt


def test_prompt_labels_nested_symbol_with_its_parent() -> None:
    prompt = _build_prompt(
        "q", ["body"], [_metadata(symbol="method", parent_symbol="MyClass")]
    )

    assert "(MyClass.method)" in prompt


def test_prompt_numbers_multiple_chunks_in_order() -> None:
    prompt = _build_prompt(
        "q",
        ["first body", "second body"],
        [_metadata(file_path="a.go"), _metadata(file_path="b.go", start_line=1, end_line=5)],
    )

    assert prompt.index("[1] csv2md/a.go") < prompt.index("[2] csv2md/b.go")
