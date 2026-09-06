"""Task contracts."""

from typing import Any

from pydantic import BaseModel


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
