"""Execution budgets and deterministic client-side accounting."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from time import monotonic

from pydantic import BaseModel, Field


class ExecutionBudget(BaseModel):
    """Limits for one model/tool execution, as defined by SPEC §24."""

    max_wall_seconds: int = Field(default=300, ge=0)
    max_model_turns: int = Field(default=50, ge=0)
    max_tool_calls: int = Field(default=100, ge=0)
    max_tokens: int | None = Field(default=None, ge=0)


class BudgetStatus(StrEnum):
    """Status returned after a budget check succeeds or is rejected."""

    OK = "ok"
    EXCEEDED = "exceeded"


class BudgetExceeded(RuntimeError):
    """Raised when one execution budget dimension would be exceeded."""

    def __init__(self, dimension: str, limit: int | float, observed: int | float) -> None:
        self.dimension = dimension
        self.limit = limit
        self.observed = observed
        super().__init__(f"execution budget exceeded for {dimension}: {observed} > {limit}")


class BudgetTracker:
    """Track model turns, tool calls, tokens, and wall-clock usage."""

    def __init__(self, budget: ExecutionBudget, *, clock: Callable[[], float] = monotonic) -> None:
        self.budget = budget
        self._clock = clock
        self._started_at = clock()
        self.model_turns = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.exceeded: BudgetExceeded | None = None

    @property
    def elapsed_seconds(self) -> float:
        """Return elapsed monotonic wall time for this tracker."""

        return max(0.0, self._clock() - self._started_at)

    @property
    def total_tokens(self) -> int:
        """Return observed input plus output tokens."""

        return self.input_tokens + self.output_tokens

    def check_and_bump(self, counter: str, amount: int = 1) -> BudgetStatus:
        """Check one counter, bump it, and return ``BudgetStatus.OK``.

        The exception retains the failed dimension and attempted value, while
        the successful return value makes call sites explicit about the check.
        Counter aliases ``turns``/``tools`` and singular forms are accepted for
        small adapters and tests.
        """

        if amount < 0:
            raise ValueError("budget increments must be non-negative")
        normalized = _normalize_counter(counter)
        if normalized == "model_turns":
            current = self.model_turns
            limit = self.budget.max_model_turns
        elif normalized == "tool_calls":
            current = self.tool_calls
            limit = self.budget.max_tool_calls
        elif normalized == "tokens":
            current = self.total_tokens
            limit = self.budget.max_tokens
            if limit is None:
                if amount:
                    self.output_tokens += amount
                return BudgetStatus.OK
        else:
            raise ValueError(f"unknown budget counter: {counter}")

        attempted = current + amount
        if attempted > limit:
            error = BudgetExceeded(normalized, limit, attempted)
            self.exceeded = error
            raise error

        if normalized == "model_turns":
            self.model_turns = attempted
        elif normalized == "tool_calls":
            self.tool_calls = attempted
        else:
            self.output_tokens = attempted - self.input_tokens
        return BudgetStatus.OK

    def check_wall(self) -> BudgetStatus:
        """Check the wall-clock limit and return the successful status."""

        elapsed = self.elapsed_seconds
        if elapsed >= self.budget.max_wall_seconds:
            error = BudgetExceeded("wall_seconds", self.budget.max_wall_seconds, elapsed)
            self.exceeded = error
            raise error
        return BudgetStatus.OK

    def record_tokens(self, input_tokens: int | None, output_tokens: int | None) -> BudgetStatus:
        """Record provider-reported token usage under ``max_tokens``."""

        input_amount = _nonnegative_token_count(input_tokens)
        output_amount = _nonnegative_token_count(output_tokens)
        attempted = self.total_tokens + input_amount + output_amount
        limit = self.budget.max_tokens
        if limit is not None and attempted > limit:
            error = BudgetExceeded("tokens", limit, attempted)
            self.exceeded = error
            raise error
        self.input_tokens += input_amount
        self.output_tokens += output_amount
        return BudgetStatus.OK

    def metrics(self, *, wall_seconds: float | None = None):
        """Build the core rollout metrics from the tracked counters."""

        from agentgym.core.rollout import RolloutMetrics

        return RolloutMetrics(
            wall_seconds=self.elapsed_seconds if wall_seconds is None else wall_seconds,
            model_turns=self.model_turns,
            tool_calls=self.tool_calls,
            input_tokens=self.input_tokens or None,
            output_tokens=self.output_tokens or None,
            estimated_cost=None,
        )


def _normalize_counter(counter: str) -> str:
    normalized = counter.strip().casefold().replace("-", "_")
    aliases = {
        "turn": "model_turns",
        "turns": "model_turns",
        "model_turn": "model_turns",
        "model_turns": "model_turns",
        "tool": "tool_calls",
        "tools": "tool_calls",
        "tool_call": "tool_calls",
        "tool_calls": "tool_calls",
        "token": "tokens",
        "tokens": "tokens",
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise ValueError(f"unknown budget counter: {counter}") from error


def _nonnegative_token_count(value: int | None) -> int:
    if value is None:
        return 0
    if value < 0:
        raise ValueError("token counts must be non-negative")
    return value


__all__ = ["BudgetExceeded", "BudgetStatus", "BudgetTracker", "ExecutionBudget"]
