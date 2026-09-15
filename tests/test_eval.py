import json
from pathlib import Path

from reposage.eval import (
    CaseResult,
    EvalSummary,
    GoldenCase,
    _matches,
    _rank_of_first_match,
    discover_golden_files,
    load_golden_cases,
)


def _metadata(**overrides) -> dict:
    base = {"repo": "csv2md", "file_path": "main.go", "symbol": "getSrc", "parent_symbol": ""}
    return {**base, **overrides}


def test_load_golden_cases_parses_json(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps(
            [
                {"repo": "csv2md", "question": "q1", "expected_file": "main.go", "expected_symbol": "getSrc"},
                {"repo": "csv2md", "question": "q2", "expected_file": "README.md"},
            ]
        )
    )

    cases = load_golden_cases(path)

    assert cases == [
        GoldenCase(repo="csv2md", question="q1", expected_file="main.go", expected_symbol="getSrc"),
        GoldenCase(repo="csv2md", question="q2", expected_file="README.md", expected_symbol=None),
    ]


def test_matches_requires_repo_and_file() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="main.go", expected_symbol="getSrc")

    assert _matches(case, _metadata()) is True
    assert _matches(case, _metadata(repo="other")) is False
    assert _matches(case, _metadata(file_path="other.go")) is False


def test_matches_checks_symbol_or_parent_symbol() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="main.go", expected_symbol="MyClass")

    assert _matches(case, _metadata(symbol="other", parent_symbol="MyClass")) is True
    assert _matches(case, _metadata(symbol="other", parent_symbol="other")) is False


def test_matches_with_no_expected_symbol_matches_any_chunk_in_file() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="README.md", expected_symbol=None)

    assert _matches(case, _metadata(file_path="README.md", symbol="", parent_symbol="")) is True


def test_rank_of_first_match_is_1_indexed() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="main.go", expected_symbol="getWidths")
    metadatas = [_metadata(symbol="getSrc"), _metadata(symbol="getWidths"), _metadata(symbol="getDest")]

    assert _rank_of_first_match(case, metadatas) == 2


def test_rank_of_first_match_returns_none_when_absent() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="main.go", expected_symbol="missing")

    assert _rank_of_first_match(case, [_metadata()]) is None


def test_summary_hit_rate_and_mrr() -> None:
    case = GoldenCase(repo="csv2md", question="q", expected_file="main.go", expected_symbol="x")
    summary = EvalSummary(results=[CaseResult(case=case, rank=1), CaseResult(case=case, rank=None)])

    assert summary.hit_rate == 0.5
    assert summary.mean_reciprocal_rank == 0.5


def test_summary_with_no_results_is_zero() -> None:
    summary = EvalSummary(results=[])

    assert summary.hit_rate == 0.0
    assert summary.mean_reciprocal_rank == 0.0


def test_discover_golden_files_finds_only_golden_prefixed_json(tmp_path: Path) -> None:
    (tmp_path / "golden_go.json").write_text("[]")
    (tmp_path / "golden_python.json").write_text("[]")
    (tmp_path / "other.json").write_text("[]")

    files = discover_golden_files(tmp_path)

    assert [f.name for f in files] == ["golden_go.json", "golden_python.json"]
