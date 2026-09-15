from dataclasses import dataclass, field
from typing import Any

from reposage.chunking.chunk import format_symbol_label
from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.llm.ollama_client import OllamaClient
from reposage.store.chroma_store import ChromaStore
from reposage.tools import TOOL_SCHEMAS, run_tool

MAX_TOOL_ITERATIONS = 3
MAX_RELATED_CHUNKS = 4

SYSTEM_PREAMBLE = (
    "You are RepoSage, an assistant answering questions about a person's "
    "codebase. Use the numbered context chunks below first - do not use "
    "outside knowledge. A second 'Related code' section may follow with "
    "the callers/callees of those chunks - not necessarily the closest "
    "semantic match to the question, but useful for understanding how the "
    "context chunks are used. If neither is enough to answer confidently, "
    "you may call the list_files/read_file tools (read-only) to look at "
    "more of the repo, up to a few rounds of calls before you must give a "
    "final answer. Cite context chunks by their number, like [1]; cite "
    "anything you read yourself as repo/file:line. If you still can't "
    "find the answer, say so plainly instead of guessing."
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
    related: list[Citation] = field(default_factory=list)
    explored: list[str] = field(default_factory=list)


def _citation_from_metadata(metadata: dict[str, Any]) -> Citation:
    return Citation(
        repo=metadata["repo"],
        file_path=metadata["file_path"],
        start_line=metadata["start_line"],
        end_line=metadata["end_line"],
        label=format_symbol_label(metadata["symbol"] or None, metadata["parent_symbol"] or None),
    )


def _context_block(index: int, document: str, metadata: dict[str, Any]) -> str:
    label = format_symbol_label(metadata["symbol"] or None, metadata["parent_symbol"] or None)
    location = f"{metadata['repo']}/{metadata['file_path']}:{metadata['start_line']}-{metadata['end_line']}"
    return f"[{index}] {location} ({label})\n{document}"


def _hydrate_related_chunks(
    store: ChromaStore, metadatas: list[dict[str, Any]], limit: int = MAX_RELATED_CHUNKS
) -> tuple[list[str], list[dict[str, Any]]]:
    """Look up the immediate callers/callees of the retrieved chunks (by
    name, via lineage metadata written at embed time) and fetch their
    actual bodies, capped at `limit` extra chunks - so the LLM sees real
    related code even when it wasn't itself the closest embedding match."""
    seen = {(m["repo"], m["file_path"], m["symbol"]) for m in metadatas}
    related_documents: list[str] = []
    related_metadatas: list[dict[str, Any]] = []

    for metadata in metadatas:
        combined = metadata.get("calls", "") + "," + metadata.get("called_by", "")
        names = [n for n in combined.split(",") if n]
        for name in names:
            if len(related_metadatas) >= limit:
                return related_documents, related_metadatas

            hit = store.get_by_symbol(metadata["repo"], name)
            key = (metadata["repo"], metadata["file_path"], name) if hit is None else (hit["metadata"]["repo"], hit["metadata"]["file_path"], hit["metadata"]["symbol"])
            if hit is None or key in seen:
                continue

            seen.add(key)
            related_documents.append(hit["document"])
            related_metadatas.append(hit["metadata"])

    return related_documents, related_metadatas


def _build_prompt(
    question: str,
    documents: list[str],
    metadatas: list[dict[str, Any]],
    related_documents: list[str],
    related_metadatas: list[dict[str, Any]],
) -> str:
    context = "\n\n".join(
        _context_block(i, document, metadata) for i, (document, metadata) in enumerate(zip(documents, metadatas), start=1)
    )

    related_section = ""
    if related_documents:
        related_blocks = "\n\n".join(
            _context_block(i, document, metadata)
            for i, (document, metadata) in enumerate(
                zip(related_documents, related_metadatas), start=len(documents) + 1
            )
        )
        related_section = f"\n\nRelated code (callers/callees of the chunks above):\n\n{related_blocks}"

    return f"{SYSTEM_PREAMBLE}\n\nContext:\n{context}{related_section}\n\nQuestion: {question}\n\nAnswer:"


def _run_tool_calls(config: Config, tool_calls: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    tool_messages = []
    explored = []
    for call in tool_calls:
        fn = call["function"]
        name, arguments = fn["name"], fn.get("arguments") or {}
        result = run_tool(config, name, arguments)
        tool_messages.append({"role": "tool", "content": result})
        explored.append(f"{name}({', '.join(f'{k}={v}' for k, v in arguments.items())})")
    return tool_messages, explored


def answer_question(config: Config, question: str, repo: str | None = None, limit: int = 8) -> Answer:
    """Retrieve the top-k chunks for `question` and have a local LLM
    synthesize an answer grounded in them, with citations back to
    repo/file/line for each chunk used as context.

    Two extra layers of context beyond the raw top-k, in increasing order
    of cost: the immediate callers/callees of the retrieved chunks are
    hydrated with their real bodies as "related code" (cheap - one lookup
    per name, no extra LLM round-trip), and if that still isn't enough,
    the model can call read-only tools (list_files/read_file) to explore
    the synced repo itself, up to MAX_TOOL_ITERATIONS rounds before it's
    forced to give a final answer.
    """
    embedder = Embedder(config.embedding_model)
    store = ChromaStore(config.chroma_dir)

    result = store.query(embedder.embed_query(question), n_results=limit, repo=repo)
    metadatas = result["metadatas"][0]
    if not metadatas:
        return Answer(text="No indexed chunks to answer from. Run `repo-sage embed <repo>` first.", citations=[])

    documents = result["documents"][0]
    citations = [_citation_from_metadata(m) for m in metadatas]

    related_documents, related_metadatas = _hydrate_related_chunks(store, metadatas)
    related = [_citation_from_metadata(m) for m in related_metadatas]

    client = OllamaClient(model=config.ollama_model, base_url=config.ollama_base_url)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _build_prompt(question, documents, metadatas, related_documents, related_metadatas)}
    ]
    explored: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        message = client.chat(messages, tools=TOOL_SCHEMAS)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return Answer(text=message["content"], citations=citations, related=related, explored=explored)

        messages.append(message)
        tool_messages, newly_explored = _run_tool_calls(config, tool_calls)
        messages.extend(tool_messages)
        explored.extend(newly_explored)

    final = client.chat(messages, tools=None)
    return Answer(text=final["content"], citations=citations, related=related, explored=explored)
