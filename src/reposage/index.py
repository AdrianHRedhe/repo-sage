from dataclasses import dataclass

from reposage.chunking.chunk_file import chunk_file
from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.filters.include import list_included_files
from reposage.filters.languages import language_for
from reposage.store.chroma_store import ChromaStore, chunk_id


@dataclass
class IndexStats:
    embedded: int = 0
    skipped: int = 0
    deleted: int = 0


def index_repo(config: Config, repo_name: str) -> IndexStats:
    """Chunk every included file in a synced repo and bring the Chroma
    collection in sync with it: unchanged chunks are skipped (no
    re-embedding), new/changed chunks are embedded and upserted, and chunks
    no longer produced (renamed/deleted functions or files) are deleted."""
    repo_path = config.repos_dir / repo_name
    store = ChromaStore(config.chroma_dir)
    embedder = Embedder(config.embedding_model)

    stats = IndexStats()

    for rel_path in list_included_files(repo_path):
        language = language_for(rel_path.suffix)
        if language is None:
            continue

        new_chunks = chunk_file(repo_name, repo_path, rel_path, language)
        new_by_id = {chunk_id(c): c for c in new_chunks}
        existing = store.existing_hashes(repo_name, rel_path.as_posix())

        stale_ids = [id_ for id_ in existing if id_ not in new_by_id]
        store.delete(stale_ids)
        stats.deleted += len(stale_ids)

        to_embed = [c for id_, c in new_by_id.items() if existing.get(id_) != c.content_hash]
        stats.skipped += len(new_by_id) - len(to_embed)

        if to_embed:
            embeddings = embedder.embed_documents([c.text for c in to_embed])
            store.upsert(to_embed, embeddings)
            stats.embedded += len(to_embed)

    return stats
