from pathlib import Path

from reposage.chunking.chunk import Chunk
from reposage.chunking.fallback import chunk_with_fallback
from reposage.chunking.language_config import LANGUAGE_CONFIGS
from reposage.chunking.treesitter_chunker import chunk_with_treesitter


def chunk_file(repo: str, repo_path: Path, relative_path: Path, language: str) -> list[Chunk]:
    source = (repo_path / relative_path).read_bytes()
    file_path = relative_path.as_posix()

    if language in LANGUAGE_CONFIGS:
        return chunk_with_treesitter(repo, file_path, language, source)

    return chunk_with_fallback(repo, file_path, language, source)
