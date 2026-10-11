"""Measure the jailbreak guard against labelled questions
(eval/jailbreak_cases.json), so changes to its question, threshold or
model are judged by numbers rather than by feel. Calls the live TypeSafe
API, one request per case."""

import json
from dataclasses import dataclass
from pathlib import Path

from reposage.jailbreak_guard import JailbreakGuard


@dataclass(frozen=True)
class JailbreakCase:
    question: str
    jailbreak: bool
    # Why the case is in the set, e.g. "mentions jailbreaks while asking
    # about code" - the thing a wrong verdict on it would mean.
    note: str


@dataclass(frozen=True)
class JailbreakCaseResult:
    case: JailbreakCase
    probability: float

    def blocked_at(self, threshold: float) -> bool:
        return self.probability >= threshold


@dataclass(frozen=True)
class JailbreakEvalSummary:
    results: list[JailbreakCaseResult]
    threshold: float

    @property
    def false_positives(self) -> list[JailbreakCaseResult]:
        """Legitimate questions that would be refused."""
        return [r for r in self.results if not r.case.jailbreak and r.blocked_at(self.threshold)]

    @property
    def missed_jailbreaks(self) -> list[JailbreakCaseResult]:
        return [r for r in self.results if r.case.jailbreak and not r.blocked_at(self.threshold)]

    @property
    def highest_legitimate_probability(self) -> float | None:
        """With lowest_jailbreak_probability, the gap a threshold can sit in
        without a mistake on this set - a wider gap means more room for
        questions the set does not cover."""
        legitimate = [r.probability for r in self.results if not r.case.jailbreak]
        return max(legitimate) if legitimate else None

    @property
    def lowest_jailbreak_probability(self) -> float | None:
        jailbreaks = [r.probability for r in self.results if r.case.jailbreak]
        return min(jailbreaks) if jailbreaks else None


def load_jailbreak_cases(path: Path) -> list[JailbreakCase]:
    return [
        JailbreakCase(question=item["question"], jailbreak=item["jailbreak"], note=item["note"])
        for item in json.loads(path.read_text())
    ]


def run_jailbreak_eval(guard: JailbreakGuard, cases: list[JailbreakCase], threshold: float) -> JailbreakEvalSummary:
    results = [JailbreakCaseResult(case=case, probability=guard.jailbreak_probability(case.question)) for case in cases]
    return JailbreakEvalSummary(results=results, threshold=threshold)
