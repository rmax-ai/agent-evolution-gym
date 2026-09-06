"""Trajectory event contracts."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class TrajectoryEventType(StrEnum):
    """Observable trajectory event types defined by SPEC section 25."""

    RUN_STARTED = "run.started"
    AGENT_STARTED = "agent.started"
    MODEL_REQUEST = "model.request"
    MODEL_RESPONSE = "model.response"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    TOOL_ERROR = "tool.error"
    WORLD_API_REQUEST = "world.api.request"
    WORLD_API_RESPONSE = "world.api.response"
    ARTIFACT_CREATED = "artifact.created"
    AGENT_ERROR = "agent.error"
    AGENT_COMPLETED = "agent.completed"
    VERIFICATION_ASSERTION = "verification.assertion"
    VERIFICATION_COMPLETED = "verification.completed"
    RUN_COMPLETED = "run.completed"


class TrajectoryEvent(BaseModel):
    """One interaction recorded at an observable execution boundary."""

    sequence: int
    timestamp: str
    type: TrajectoryEventType
    actor: str
    payload: dict[str, Any]
