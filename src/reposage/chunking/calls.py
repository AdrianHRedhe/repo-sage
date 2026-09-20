from pathlib import Path

from tree_sitter import Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from reposage.chunking.language_config import LanguageConfig

# Keyed by query file, not by language: two configs can share a
# ts_language while pointing at different queries.
_call_query_cache: dict[Path, Query] = {}


def _get_call_query(config: LanguageConfig) -> Query:
    cached = _call_query_cache.get(config.call_query_path)
    if cached is not None:
        return cached

    language = get_language(config.ts_language)
    query = Query(language, config.call_query_path.read_text())
    _call_query_cache[config.call_query_path] = query
    return query


def extract_call_names(text: str, config: LanguageConfig) -> set[str]:
    """Every identifier called within `text` (free-function calls like
    `foo()` and method/attribute calls like `obj.foo()`), used to build a
    heuristic caller/callee graph by matching these names against symbols
    defined elsewhere in the repo.

    This is name-only matching, not real call resolution: `obj.Close()`
    matches every `Close` defined anywhere in the repo regardless of
    `obj`'s actual type. Good enough to surface likely-related context,
    not for exact call-graph analysis.
    """
    if config.call_query_path is None:
        return set()

    tree = get_parser(config.ts_language).parse(text.encode("utf-8"))
    cursor = QueryCursor(_get_call_query(config))

    names: set[str] = set()
    for _pattern_index, captures in cursor.matches(tree.root_node):
        for node in captures.get("call_name", []):
            names.add(node.text.decode("utf-8"))
    return names
