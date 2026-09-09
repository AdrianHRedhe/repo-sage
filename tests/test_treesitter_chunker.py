from reposage.chunking.treesitter_chunker import chunk_with_treesitter

PYTHON_SRC = b'''class Foo:
    """Docstring."""

    def bar(self, x):
        return x

    @staticmethod
    def baz():
        pass

@decorator
def top_level():
    pass
'''

GO_SRC = b'''package main

// Point is a 2D point.
type Point struct {
\tX, Y int
}

type Shape interface {
\tArea() float64
}

// Area computes something.
func (p Point) Area() float64 {
\treturn 0
}

func main() {}
'''

SCALA_SRC = b'''package foo

trait Shape {
  def area: Double
}

class Point(val x: Int, val y: Int) {
  def distanceTo(other: Point): Double = {
    0.0
  }
}

object Point {
  def apply(x: Int, y: Int): Point = new Point(x, y)
}
'''


def test_python_captures_functions_methods_and_class_with_parent_symbol() -> None:
    chunks = chunk_with_treesitter("repo", "foo.py", "Python", PYTHON_SRC)
    by_symbol = {c.symbol: c for c in chunks}

    assert by_symbol["Foo"].node_type == "class"
    assert by_symbol["Foo"].parent_symbol is None

    assert by_symbol["bar"].parent_symbol == "Foo"

    baz = by_symbol["baz"]
    assert baz.parent_symbol == "Foo"
    assert baz.text.startswith("@staticmethod")

    top_level = by_symbol["top_level"]
    assert top_level.parent_symbol is None
    assert top_level.text.startswith("@decorator")


def test_go_captures_functions_methods_and_types_with_receiver_as_parent() -> None:
    chunks = chunk_with_treesitter("repo", "main.go", "Go", GO_SRC)
    by_symbol = {c.symbol: c for c in chunks}

    assert by_symbol["Point"].node_type == "type"
    assert by_symbol["Shape"].node_type == "type"

    area = by_symbol["Area"]
    assert area.node_type == "method"
    assert area.parent_symbol == "Point"

    main = by_symbol["main"]
    assert main.node_type == "function"
    assert main.parent_symbol is None


def test_scala_captures_defs_with_enclosing_class_object_or_trait() -> None:
    chunks = chunk_with_treesitter("repo", "Foo.scala", "Scala", SCALA_SRC)
    by_symbol_and_parent = {(c.symbol, c.parent_symbol): c for c in chunks}

    assert ("Shape", None) in by_symbol_and_parent
    assert ("area", "Shape") in by_symbol_and_parent
    assert ("Point", None) in by_symbol_and_parent  # both class and object are named Point
    assert ("distanceTo", "Point") in by_symbol_and_parent
    assert ("apply", "Point") in by_symbol_and_parent
