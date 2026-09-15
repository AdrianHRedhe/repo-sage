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
    prompt = _build_prompt("how does X work?", ["func body"], [_metadata()], [], [])

    assert "Question: how does X work?" in prompt
    assert "[1] csv2md/main.go:10-20 (Convert)" in prompt
    assert "func body" in prompt


def test_prompt_labels_nested_symbol_with_its_parent() -> None:
    prompt = _build_prompt(
        "q", ["body"], [_metadata(symbol="method", parent_symbol="MyClass")], [], []
    )

    assert "(MyClass.method)" in prompt


def test_prompt_numbers_multiple_chunks_in_order() -> None:
    prompt = _build_prompt(
        "q",
        ["first body", "second body"],
        [_metadata(file_path="a.go"), _metadata(file_path="b.go", start_line=1, end_line=5)],
        [],
        [],
    )

    assert prompt.index("[1] csv2md/a.go") < prompt.index("[2] csv2md/b.go")


def test_prompt_omits_related_section_when_empty() -> None:
    prompt = _build_prompt("q", ["body"], [_metadata()], [], [])

    assert "Related code (callers/callees of the chunks above):" not in prompt


def test_prompt_appends_related_section_continuing_the_numbering() -> None:
    prompt = _build_prompt(
        "q",
        ["primary body"],
        [_metadata()],
        ["related body"],
        [_metadata(file_path="helper.go", symbol="Helper", start_line=30, end_line=40)],
    )

    assert "Related code (callers/callees of the chunks above):" in prompt
    assert "[2] csv2md/helper.go:30-40 (Helper)" in prompt
    assert "related body" in prompt
    assert prompt.index("[1] csv2md/main.go") < prompt.index("[2] csv2md/helper.go")
