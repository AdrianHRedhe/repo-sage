from dataclasses import dataclass, field
from typing import Any

from reposage.chunking.chunk import format_symbol_label
from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.llm.ollama_client import OllamaClient
from reposage.store.chroma_store import ChromaStore
from reposage.tools import TOOL_SCHEMAS, run_tool

MAX_TOOL_ITERATIONS = 3

SYSTEM_PREAMBLE = (
    "You are RepoSage, an assistant answering questions about a person's "
    "codebase. Use the numbered context chunks below first - do not use "
    "outside knowledge. If they aren't enough to answer confidently, you "
    "may call the list_files/read_file tools (read-only) to look at more "
    "of the repo, up to a few rounds of calls before you must give a final "
    "answer. Cite context chunks by their number, like [1]; cite anything "
    "you read yourself as repo/file:line. If you still can't find the "
    "answer, say so plainly instead of guessing."
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
    explored: list[str] = field(default_factory=list)


def _build_prompt(question: str, documents: list[str], metadatas: list[dict[str, Any]]) -> str:
    context_blocks = []
    for i, (document, metadata) in enumerate(zip(documents, metadatas), start=1):
        label = format_symbol_label(metadata["symbol"] or None, metadata["parent_symbol"] or None)
        location = f"{metadata['repo']}/{metadata['file_path']}:{metadata['start_line']}-{metadata['end_line']}"
        context_blocks.append(f"[{i}] {location} ({label})\n{document}")

    context = "\n\n".join(context_blocks)
    return f"{SYSTEM_PREAMBLE}\n\nContext:\n{context}\n\nQuestion: {question}\n\nAnswer:"


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

    If the retrieved chunks aren't enough, the model can call read-only
    tools (list_files/read_file) to explore the synced repo further, up to
    MAX_TOOL_ITERATIONS rounds before it's forced to give a final answer.
    """
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
    messages: list[dict[str, Any]] = [{"role": "user", "content": _build_prompt(question, documents, metadatas)}]
    explored: list[str] = []

    for _ in range(MAX_TOOL_ITERATIONS):
        message = client.chat(messages, tools=TOOL_SCHEMAS)
        tool_calls = message.get("tool_calls")
        if not tool_calls:
            return Answer(text=message["content"], citations=citations, explored=explored)

        messages.append(message)
        tool_messages, newly_explored = _run_tool_calls(config, tool_calls)
        messages.extend(tool_messages)
        explored.extend(newly_explored)

    final = client.chat(messages, tools=None)
    return Answer(text=final["content"], citations=citations, explored=explored)
