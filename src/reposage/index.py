from dataclasses import dataclass

from reposage.callgraph import attach_lineage
from reposage.chunking.repo_chunks import chunk_repo
from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.store.chroma_store import ChromaStore, chunk_id


@dataclass
class IndexStats:
    embedded: int = 0
    skipped: int = 0
    deleted: int = 0


def prune_missing_repos(config: Config, present_names: list[str]) -> dict[str, int]:
    """Drop stored chunks for repos that are no longer synced, returning
    {repo: chunks deleted}.

    The counterpart to sync's prune_removed_repos: that one reclaims the
    clone, this one reclaims the embeddings, which otherwise keep being
    retrieved and cited long after the code is gone. Only safe to call with
    the *complete* set of synced repos, which is why `embed --all` is the
    only caller - embedding a single repo says nothing about the rest.
    """
    store = ChromaStore(config.chroma_dir)

    deleted = {}
    for repo in sorted(store.repos() - set(present_names)):
        deleted[repo] = store.delete_repo(repo)

    return deleted


def index_repo(config: Config, repo_name: str, embedder: Embedder | None = None) -> IndexStats:
    """Chunk every included file in a synced repo and bring the Chroma
    collection in sync with it: unchanged chunks are skipped (no
    re-embedding), new/changed chunks are embedded and upserted, and chunks
    no longer produced (renamed/deleted functions or files) are deleted.

    Lineage (attach_lineage) is resolved across the whole repo up front,
    not per file, since a caller and callee are frequently in different
    files - each chunk's content_hash then reflects its lineage too, so a
    newly added/removed caller or callee invalidates the cached embedding
    even when the chunk's own text didn't change.

    `embedder` lets a caller that already holds a loaded model hand it over
    instead of paying for a second one. That matters for the web sandbox:
    the server keeps a warm Embedder for answering questions, and building
    another one here put two full copies of the model in a memory-capped
    container (measured 6.8GB of an 8GB limit, and OOM-killed outright on a
    larger repo). The CLI passes nothing and gets the old behaviour.
    """
    repo_path = config.repos_dir / repo_name
    store = ChromaStore(config.chroma_dir)
    if embedder is None:
        embedder = Embedder(config.embedding_model)

    chunks_by_file = chunk_repo(repo_name, repo_path)
    all_chunks = [c for chunks in chunks_by_file.values() for c in chunks]
    enriched_by_id = attach_lineage(all_chunks)

    stats = IndexStats()

    for rel_path, chunks in chunks_by_file.items():
        new_chunks = [enriched_by_id[chunk_id(c)] for c in chunks]
        new_by_id = {chunk_id(c): c for c in new_chunks}
        existing = store.existing_hashes(repo_name, rel_path.as_posix())

        stale_ids = [id_ for id_ in existing if id_ not in new_by_id]
        store.delete(stale_ids)
        stats.deleted += len(stale_ids)

        to_embed = [c for id_, c in new_by_id.items() if existing.get(id_) != c.content_hash]
        stats.skipped += len(new_by_id) - len(to_embed)

        if to_embed:
            embeddings = embedder.embed_documents([c.embedding_text for c in to_embed])
            store.upsert(to_embed, embeddings)
            stats.embedded += len(to_embed)

    return stats
