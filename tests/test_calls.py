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


def test_extract_call_names_empty_for_language_without_call_query() -> None:
    names = extract_call_names("object Foo { def bar() = baz() }", LANGUAGE_CONFIGS["Scala"])

    assert names == set()
