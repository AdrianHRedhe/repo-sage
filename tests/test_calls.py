from dataclasses import replace

from reposage.chunking.calls import extract_call_names
from reposage.chunking.language_config import LANGUAGE_CONFIGS


def test_extract_call_names_finds_free_function_calls_in_python() -> None:
    source = "def outer():\n    helper()\n    another(1, 2)\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Python"])

    assert names == {"helper", "another"}


def test_extract_call_names_finds_attribute_calls_in_python() -> None:
    source = "def outer(self):\n    self.helper()\n    obj.method()\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Python"])

    assert names == {"helper", "method"}


def test_extract_call_names_finds_free_function_and_selector_calls_in_go() -> None:
    source = """
func Outer() {
	helper()
	obj.Method()
}
"""

    names = extract_call_names(source, LANGUAGE_CONFIGS["Go"])

    assert names == {"helper", "Method"}


def test_extract_call_names_finds_free_function_and_method_calls_in_scala() -> None:
    source = "object Foo:\n  def bar(): Int =\n    baz()\n    input.map(parseSingle)\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Scala"])

    assert names == {"baz", "map"}


def test_extract_call_names_finds_curried_and_generic_calls_in_scala() -> None:
    """Curried application needs no pattern of its own - the outer node's
    function is the inner call_expression, so the name is captured once by
    recursion rather than twice or not at all."""
    source = "def outer() =\n  input.scanLeft(initPos)(updatePosition)\n  Queue[String]()\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Scala"])

    assert names == {"scanLeft", "Queue"}


def test_extract_call_names_finds_constructor_calls_in_scala() -> None:
    """`new Foo(...)` is Scala's constructor call, the counterpart of
    Python's `Foo()`, so the constructed type resolves like any other name."""
    source = "def outer() = throw new NoSolutionError(\"nope\")\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Scala"])

    assert names == {"NoSolutionError"}


def test_extract_call_names_ignores_symbolic_operators_in_scala() -> None:
    """Scala parses `a + b` as an infix_expression, i.e. a method call on
    `a`. Capturing those would add `+`/`%`/`&&` to every chunk's lineage as
    noise, so scala_calls.scm matches explicit call syntax only - the same
    rule the Python and Go queries follow."""
    source = "def outer(pos: Int, action: Int) = (pos + action) % 100 == 0 && go()\n"

    names = extract_call_names(source, LANGUAGE_CONFIGS["Scala"])

    assert names == {"go"}


def test_extract_call_names_empty_for_language_without_call_query() -> None:
    without_calls = replace(LANGUAGE_CONFIGS["Scala"], call_query_path=None)

    names = extract_call_names("object Foo { def bar() = baz() }", without_calls)

    assert names == set()
