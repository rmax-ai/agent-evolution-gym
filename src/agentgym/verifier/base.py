"""Protocols and result assembly for deterministic verification."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from agentgym.core.task import Task
from agentgym.core.verification import AssertionResult, VerificationResult
from agentgym.world.snapshot import WorldSnapshot


class Verifier(Protocol):
    """Verify a task from external world state and observable trajectory data.

    A verifier deliberately has no argument for an agent's natural-language
    final answer.  Task success is established from the snapshots and any
    trajectory facts that are independently observable by the framework.
    """

    async def verify(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        trajectory: object,
    ) -> VerificationResult:
        """Return deterministic assertions for one rollout."""

        ...


def build_result(
    assertions: Iterable[AssertionResult],
    metadata: Mapping[str, Any] | None = None,
) -> VerificationResult:
    """Assemble a :class:`VerificationResult` from assertion outcomes.

    The category flags are vacuously true when a category has no assertions;
    the overall score is ``0.0`` for an empty assertion collection because no
    verification evidence was produced.  A fresh metadata dictionary is
    created so callers cannot mutate a result through their input mapping.
    """

    assertion_list = list(assertions)
    passed_count = sum(assertion.passed for assertion in assertion_list)
    score = passed_count / len(assertion_list) if assertion_list else 0.0

    def category_passed(category: str) -> bool:
        return all(
            assertion.passed for assertion in assertion_list if assertion.category == category
        )

    return VerificationResult(
        passed=all(assertion.passed for assertion in assertion_list),
        score=score,
        assertions=assertion_list,
        required_changes_passed=category_passed("required"),
        forbidden_changes_passed=category_passed("forbidden"),
        invariants_passed=category_passed("invariant"),
        metadata=dict(metadata) if metadata is not None else {},
    )


__all__ = ["Verifier", "build_result"]
