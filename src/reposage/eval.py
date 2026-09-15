import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reposage.config import Config
from reposage.embedding.model import Embedder
from reposage.store.chroma_store import ChromaStore


@dataclass(frozen=True)
class GoldenCase:
    repo: str
    question: str
    expected_file: str
    # None means "any chunk from expected_file counts" (e.g. a whole-file
    # fallback chunk like README.md, which has no symbol).
    expected_symbol: str | None = None


@dataclass(frozen=True)
class CaseResult:
    case: GoldenCase
    # 1-indexed position of the first matching chunk among the retrieved
    # results, or None if it didn't appear at all.
    rank: int | None

    @property
    def hit(self) -> bool:
        return self.rank is not None


@dataclass(frozen=True)
class EvalSummary:
    results: list[CaseResult]

    @property
    def hit_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.hit) / len(self.results)

    @property
    def mean_reciprocal_rank(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 / r.rank if r.rank else 0.0 for r in self.results) / len(self.results)


def discover_golden_files(directory: Path) -> list[Path]:
    """Every golden_<label>.json file in a directory (e.g. golden_go.json,
    golden_python.json), sorted for stable output order."""
    return sorted(directory.glob("golden_*.json"))


def load_golden_cases(path: Path) -> list[GoldenCase]:
    raw = json.loads(path.read_text())
    return [
        GoldenCase(
            repo=item["repo"],
            question=item["question"],
            expected_file=item["expected_file"],
            expected_symbol=item.get("expected_symbol"),
        )
        for item in raw
    ]


def _matches(case: GoldenCase, metadata: dict[str, Any]) -> bool:
    if metadata["repo"] != case.repo or metadata["file_path"] != case.expected_file:
        return False
    if case.expected_symbol is None:
        return True
    return case.expected_symbol in (metadata["symbol"], metadata["parent_symbol"])


def _rank_of_first_match(case: GoldenCase, metadatas: list[dict[str, Any]]) -> int | None:
    for i, metadata in enumerate(metadatas, start=1):
        if _matches(case, metadata):
            return i
    return None


def run_eval(config: Config, cases: list[GoldenCase], limit: int) -> EvalSummary:
    """Retrieve the top-k chunks for each golden question and check whether
    the expected file/symbol shows up, and at what rank - a quick way to
    measure retrieval quality objectively instead of by feel, so changes
    to chunking/embedding/retrieval can be compared before/after."""
    embedder = Embedder(config.embedding_model)
    store = ChromaStore(config.chroma_dir)

    results = []
    for case in cases:
        result = store.query(embedder.embed_query(case.question), n_results=limit, repo=case.repo)
        rank = _rank_of_first_match(case, result["metadatas"][0])
        results.append(CaseResult(case=case, rank=rank))

    return EvalSummary(results=results)
