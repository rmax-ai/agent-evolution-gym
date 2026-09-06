"""Task contracts."""

from typing import Any

from pydantic import BaseModel, field_validator

from agentgym.core.json_safe import ensure_json_safe


class Task(BaseModel):
    """One instantiated problem presented to an agent."""

    id: str
    scenario_id: str
    split: str
    goal: str
    actor_id: str
    initial_snapshot_ref: str
    verifier_id: str
    metadata: dict[str, Any]

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, value: object) -> object:
        """Reject task metadata that cannot be persisted as JSON."""

        return ensure_json_safe(value)
