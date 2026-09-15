from dataclasses import replace

from reposage.chunking.calls import extract_call_names
from reposage.chunking.chunk import Chunk
from reposage.chunking.language_config import LANGUAGE_CONFIGS
from reposage.store.chroma_store import chunk_id

# Cap on how many callers/callees get attached to a single chunk, so one
# heavily-called helper (or a name collision blowing up matches) can't turn
# into an unbounded metadata/embedding-text field.
MAX_LINEAGE_NAMES = 8


def _build_symbol_index(chunks: list[Chunk]) -> dict[str, list[Chunk]]:
    index: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        if chunk.symbol:
            index.setdefault(chunk.symbol, []).append(chunk)
    return index


def attach_lineage(chunks: list[Chunk]) -> dict[str, Chunk]:
    """Resolve a heuristic caller/callee graph across every chunk in a
    repo, keyed by chunk_id.

    For each function/method chunk, extracts the names it calls (via
    tree-sitter, reposage/chunking/calls.py) and matches them against every
    other chunk's symbol name in the repo - across files, since a caller
    and callee are frequently in different files. This is 1-hop and
    name-only: it doesn't do type or scope resolution, so it can produce
    false-positive edges when two unrelated definitions share a name (e.g.
    two types both defining `Close`). Accepted as a known limitation - see
    ROADMAP.md.
    """
    symbol_index = _build_symbol_index(chunks)
    calls_by_id: dict[str, set[str]] = {chunk_id(c): set() for c in chunks}
    called_by_by_id: dict[str, set[str]] = {chunk_id(c): set() for c in chunks}

    for chunk in chunks:
        config = LANGUAGE_CONFIGS.get(chunk.language)
        if config is None or config.call_query_path is None:
            continue

        this_id = chunk_id(chunk)
        for name in extract_call_names(chunk.text, config):
            for callee in symbol_index.get(name, []):
                callee_id = chunk_id(callee)
                if callee_id == this_id:
                    continue
                calls_by_id[this_id].add(callee.symbol)
                called_by_by_id[callee_id].add(chunk.symbol)

    return {
        chunk_id(c): replace(
            c,
            calls=tuple(sorted(calls_by_id[chunk_id(c)]))[:MAX_LINEAGE_NAMES],
            called_by=tuple(sorted(called_by_by_id[chunk_id(c)]))[:MAX_LINEAGE_NAMES],
        )
        for c in chunks
    }
