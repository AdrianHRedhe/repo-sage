from dataclasses import dataclass
from typing import Any

from reposage.chunking.chunk import format_symbol_label
from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.llm.ollama_client import OllamaClient
from reposage.store.chroma_store import ChromaStore

SYSTEM_PREAMBLE = (
    "You are RepoSage, an assistant answering questions about a person's "
    "codebase using only the numbered context chunks below - do not use "
    "outside knowledge. Cite the chunk number for every claim, like [1]. "
    "If the context doesn't contain the answer, say so plainly instead of "
    "guessing."
)


@dataclass(frozen=True)
class Citation:
    repo: str
    file_path: str
    start_line: int
    end_line: int
    label: str


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]


def _build_prompt(question: str, documents: list[str], metadatas: list[dict[str, Any]]) -> str:
    context_blocks = []
    for i, (document, metadata) in enumerate(zip(documents, metadatas), start=1):
        label = format_symbol_label(metadata["symbol"] or None, metadata["parent_symbol"] or None)
        location = f"{metadata['repo']}/{metadata['file_path']}:{metadata['start_line']}-{metadata['end_line']}"
        context_blocks.append(f"[{i}] {location} ({label})\n{document}")

    context = "\n\n".join(context_blocks)
    return f"{SYSTEM_PREAMBLE}\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"


def answer_question(config: Config, question: str, repo: str | None = None, limit: int = 8) -> Answer:
    """Retrieve the top-k chunks for `question` and have a local LLM
    synthesize an answer grounded in them, with citations back to
    repo/file/line for each chunk used as context."""
    embedder = Embedder(config.embedding_model)
    store = ChromaStore(config.chroma_dir)

    result = store.query(embedder.embed_query(question), n_results=limit, repo=repo)
    metadatas = result["metadatas"][0]
    if not metadatas:
        return Answer(text="No indexed chunks to answer from. Run `repo-sage embed <repo>` first.", citations=[])

    documents = result["documents"][0]
    citations = [
        Citation(
            repo=m["repo"],
            file_path=m["file_path"],
            start_line=m["start_line"],
            end_line=m["end_line"],
            label=format_symbol_label(m["symbol"] or None, m["parent_symbol"] or None),
        )
        for m in metadatas
    ]

    client = OllamaClient(model=config.ollama_model, base_url=config.ollama_base_url)
    text = client.generate(_build_prompt(question, documents, metadatas))

    return Answer(text=text, citations=citations)
