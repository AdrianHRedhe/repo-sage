from pathlib import Path

from reposage.jailbreak_eval import JailbreakCase, JailbreakCaseResult, JailbreakEvalSummary, load_jailbreak_cases

CASES_FILE = Path(__file__).parent.parent / "eval" / "jailbreak_cases.json"


def _result(jailbreak: bool, probability: float) -> JailbreakCaseResult:
    return JailbreakCaseResult(case=JailbreakCase(question="q", jailbreak=jailbreak, note=""), probability=probability)


def test_counts_refused_legitimate_questions_and_missed_jailbreaks() -> None:
    summary = JailbreakEvalSummary(
        results=[
            _result(jailbreak=False, probability=0.1),
            _result(jailbreak=False, probability=0.9),  # refused
            _result(jailbreak=True, probability=0.95),
            _result(jailbreak=True, probability=0.5),  # missed
        ],
        threshold=0.8,
    )

    assert [r.probability for r in summary.false_positives] == [0.9]
    assert [r.probability for r in summary.missed_jailbreaks] == [0.5]
    assert summary.highest_legitimate_probability == 0.9
    assert summary.lowest_jailbreak_probability == 0.5


def test_the_shipped_case_file_loads_with_both_labels() -> None:
    cases = load_jailbreak_cases(CASES_FILE)

    assert {case.jailbreak for case in cases} == {True, False}
    assert all(case.question and case.note for case in cases)
