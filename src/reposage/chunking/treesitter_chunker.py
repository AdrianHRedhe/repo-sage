from tree_sitter import Node, Query, QueryCursor
from tree_sitter_language_pack import get_language, get_parser

from reposage.chunking.chunk import Chunk
from reposage.chunking.language_config import LANGUAGE_CONFIGS, LanguageConfig

_query_cache: dict[str, Query] = {}


def _get_query(config: LanguageConfig) -> Query:
    cached = _query_cache.get(config.ts_language)
    if cached is not None:
        return cached

    language = get_language(config.ts_language)
    query = Query(language, config.query_path.read_text())
    _query_cache[config.ts_language] = query
    return query


def _line_range(node: Node) -> tuple[int, int]:
    return node.start_point[0] + 1, node.end_point[0] + 1


def _find_container_parent_symbol(node: Node, container_types: frozenset[str]) -> str | None:
    """Walk up ancestors for languages where a definition nests lexically
    inside its container (e.g. a Python method inside a class body)."""
    current = node.parent
    while current is not None:
        if current.type in container_types:
            name_node = current.child_by_field_name("name")
            return name_node.text.decode("utf-8") if name_node is not None else None
        current = current.parent
    return None


def is_treesitter_supported(language: str) -> bool:
    return language in LANGUAGE_CONFIGS


def chunk_with_treesitter(repo: str, file_path: str, language: str, source: bytes) -> list[Chunk]:
    config = LANGUAGE_CONFIGS[language]
    tree = get_parser(config.ts_language).parse(source)
    cursor = QueryCursor(_get_query(config))

    chunks: list[Chunk] = []
    for _pattern_index, captures in cursor.matches(tree.root_node):
        definition_node = None
        node_type = None
        for capture_name, nodes in captures.items():
            if capture_name.startswith("definition."):
                definition_node = nodes[0]
                node_type = capture_name.removeprefix("definition.")

        if definition_node is None or node_type is None:
            continue

        name_nodes = captures.get("name")
        symbol = name_nodes[0].text.decode("utf-8") if name_nodes else None

        parent_name_nodes = captures.get("parent_name")
        if parent_name_nodes:
            parent_symbol = parent_name_nodes[0].text.decode("utf-8")
        else:
            parent_symbol = _find_container_parent_symbol(definition_node, config.container_node_types)

        # Extend the chunk span to cover a wrapping node (e.g. Python's
        # decorated_definition) so decorators aren't dropped from the text.
        span_node = definition_node
        if span_node.parent is not None and span_node.parent.type in config.wrapper_node_types:
            span_node = span_node.parent

        start_line, end_line = _line_range(span_node)
        text = source[span_node.start_byte : span_node.end_byte].decode("utf-8", errors="replace")

        chunks.append(
            Chunk(
                repo=repo,
                file_path=file_path,
                language=language,
                node_type=node_type,
                start_line=start_line,
                end_line=end_line,
                text=text,
                symbol=symbol,
                parent_symbol=parent_symbol,
            )
        )

    return chunks
