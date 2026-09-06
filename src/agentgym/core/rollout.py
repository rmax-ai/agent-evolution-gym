"""Rollout and rollout-metrics contracts."""

from enum import StrEnum

from pydantic import BaseModel

from agentgym.core.verification import VerificationResult


class RunStatus(StrEnum):
    """Execution outcome taxonomy defined by SPEC section 31."""

    PASS = "pass"
    TASK_FAIL = "task_fail"
    PARTIAL = "partial"
    AGENT_ERROR = "agent_error"
    TOOL_ERROR = "tool_error"
    ENVIRONMENT_ERROR = "environment_error"
    VERIFIER_ERROR = "verifier_error"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"
    POLICY_VIOLATION = "policy_violation"


class RolloutMetrics(BaseModel):
    """Execution measurements captured for one rollout."""

    wall_seconds: float
    model_turns: int
    tool_calls: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: float | None


class Rollout(BaseModel):
    """One execution of one task using one Agent Package."""

    id: str
    task_id: str
    package_id: str
    initial_state_ref: str
    final_state_ref: str
    trajectory_ref: str
    verification: VerificationResult
    metrics: RolloutMetrics
