"""Execution budget enforcement tests."""

import pytest

from agentgym.runner.budgets import BudgetExceeded, BudgetStatus, BudgetTracker, ExecutionBudget


def test_execution_budget_defaults_match_spec() -> None:
    assert ExecutionBudget().model_dump(mode="json") == {
        "max_wall_seconds": 300,
        "max_model_turns": 50,
        "max_tool_calls": 100,
        "max_tokens": None,
    }


def test_model_turn_limit_is_enforced() -> None:
    tracker = BudgetTracker(ExecutionBudget(max_model_turns=2))

    assert tracker.check_and_bump("model_turns") is BudgetStatus.OK
    assert tracker.check_and_bump("turns") is BudgetStatus.OK
    with pytest.raises(BudgetExceeded, match="model_turns"):
        tracker.check_and_bump("model_turns")
    assert tracker.model_turns == 2


def test_tool_call_limit_is_enforced() -> None:
    tracker = BudgetTracker(ExecutionBudget(max_tool_calls=1))

    tracker.check_and_bump("tool_call")
    with pytest.raises(BudgetExceeded, match="tool_calls"):
        tracker.check_and_bump("tool_calls")
    assert tracker.tool_calls == 1
