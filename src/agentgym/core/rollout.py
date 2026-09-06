"""Rollout and rollout-metrics contracts."""

from pydantic import BaseModel

from agentgym.core.verification import VerificationResult


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
