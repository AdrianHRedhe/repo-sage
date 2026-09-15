from pathlib import Path

from reposage.chunking.chunk import Chunk
from reposage.chunking.chunk_file import chunk_file
from reposage.filters.include import list_included_files
from reposage.filters.languages import language_for


def chunk_repo(repo_name: str, repo_path: Path) -> dict[Path, list[Chunk]]:
    """Chunk every included, tree-sitter-supported file in a synced repo,
    keyed by path relative to the repo root. Used wherever chunks from the
    whole repo are needed at once (building a repo-wide call graph),
    rather than one file at a time."""
    chunks_by_file: dict[Path, list[Chunk]] = {}
    for rel_path in list_included_files(repo_path):
        language = language_for(rel_path.suffix)
        if language is None:
            continue
        chunks_by_file[rel_path] = chunk_file(repo_name, repo_path, rel_path, language)
    return chunks_by_file
