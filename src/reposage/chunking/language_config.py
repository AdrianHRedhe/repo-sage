from dataclasses import dataclass
from pathlib import Path

QUERIES_DIR = Path(__file__).parent / "queries"


@dataclass(frozen=True)
class LanguageConfig:
    ts_language: str  # name passed to tree-sitter-language-pack
    query_path: Path
    # Ancestor node types to walk up to for parent_symbol, for languages
    # where definitions nest lexically inside their container (e.g. a
    # Python method inside class_definition). Leave empty when the query
    # itself captures @parent_name instead (e.g. Go, where a method's
    # receiver type isn't an AST ancestor).
    container_node_types: frozenset[str] = frozenset()
    # If a matched node's parent is one of these, the chunk's span extends
    # to the parent instead (e.g. Python's decorated_definition, so
    # @decorators aren't dropped from the chunk).
    wrapper_node_types: frozenset[str] = frozenset()
    # Query that captures @call_name at every call site in a chunk's text,
    # used to build a heuristic caller/callee graph (reposage/callgraph.py).
    # None means "not supported yet" - a language can be chunked without
    # having had its call-site AST shape validated against a real repo.
    call_query_path: Path | None = None


# Keyed by the language names from filters/languages.py - only languages
# with a query file here get tree-sitter chunking; everything else in that
# map falls back to fallback.py's naive windowed chunking.
LANGUAGE_CONFIGS: dict[str, LanguageConfig] = {
    "Python": LanguageConfig(
        ts_language="python",
        query_path=QUERIES_DIR / "python.scm",
        container_node_types=frozenset({"class_definition"}),
        wrapper_node_types=frozenset({"decorated_definition"}),
        call_query_path=QUERIES_DIR / "python_calls.scm",
    ),
    "Go": LanguageConfig(
        ts_language="go",
        query_path=QUERIES_DIR / "go.scm",
        call_query_path=QUERIES_DIR / "go_calls.scm",
    ),
    "Scala": LanguageConfig(
        ts_language="scala",
        query_path=QUERIES_DIR / "scala.scm",
        container_node_types=frozenset({"class_definition", "object_definition", "trait_definition"}),
        call_query_path=QUERIES_DIR / "scala_calls.scm",
    ),
}
