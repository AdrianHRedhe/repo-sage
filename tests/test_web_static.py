from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "reposage" / "web" / "static"


def test_index_html_contains_no_nul_bytes() -> None:
    """The page is served as text and has to stay greppable.

    renderAnswerMarkdown wraps extracted code blocks in a NUL sentinel,
    which is the right choice (NUL cannot occur in the model's answer, so
    it can't collide with real content) - but written as a literal byte it
    made `file` report the whole page as `data` and made grep silently
    match nothing in it. Writing it as the escape `\\u0000` keeps the
    runtime value identical while leaving the source plain text; this
    guards against someone pasting the literal byte back in.
    """
    raw = (STATIC_DIR / "index.html").read_bytes()

    assert b"\x00" not in raw


def test_index_html_decodes_as_utf8() -> None:
    (STATIC_DIR / "index.html").read_bytes().decode("utf-8")
