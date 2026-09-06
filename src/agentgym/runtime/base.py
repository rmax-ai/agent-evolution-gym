"""Runtime adapter contracts and the agent-safe task projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentgym.core.json_safe import ensure_json_safe
from agentgym.core.package import AgentPackage
from agentgym.core.rollout import RolloutMetrics, RunStatus
from agentgym.core.task import Task
from agentgym.core.trajectory import TrajectoryEventType
from agentgym.runner.budgets import ExecutionBudget


class ToolDescription(BaseModel):
    """Agent-visible name, description, and JSON-schema argument surface."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def validate_parameters(cls, value: object) -> object:
        return ensure_json_safe(value)


class AgentTaskView(BaseModel):
    """The only task information made available to the reference runtime.

    In particular, this DTO intentionally has no metadata, verifier settings,
    split, or snapshot reference.  The private :class:`~agentgym.core.task.Task`
    remains in the runner for evaluation only.
    """

    model_config = ConfigDict(extra="forbid")

    goal: str
    actor_id: str
    tools: list[ToolDescription] = Field(default_factory=list)

    @field_validator("tools", mode="before")
    @classmethod
    def normalize_tools(cls, value: object) -> object:
        """Accept compact name-to-description mappings at API boundaries."""

        if isinstance(value, Mapping):
            return [
                {"name": name, "description": description} for name, description in value.items()
            ]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [{"name": item} if isinstance(item, str) else item for item in value]
        return value

    @classmethod
    def from_tools(
        cls,
        *,
        goal: str,
        actor_id: str,
        tools: Sequence[ToolDescription | Mapping[str, Any]],
    ) -> AgentTaskView:
        """Construct a view from an executor's public tool descriptions."""

        return cls(
            goal=goal,
            actor_id=actor_id,
            tools=[
                tool if isinstance(tool, ToolDescription) else ToolDescription.model_validate(tool)
                for tool in tools
            ],
        )

    @classmethod
    def from_task(
        cls,
        task: Task,
        tools: Sequence[ToolDescription | Mapping[str, Any]],
    ) -> AgentTaskView:
        """Project a private task into this DTO without copying its metadata."""

        return cls.from_tools(goal=task.goal, actor_id=task.actor_id, tools=tools)

    @property
    def tool_names(self) -> list[str]:
        """Return tool names without adding fields to the persisted DTO."""

        return [tool.name for tool in self.tools]

    @property
    def tool_descriptions(self) -> dict[str, str]:
        """Return a convenient name-to-description view of the tool surface."""

        return {tool.name: tool.description for tool in self.tools}


class ToolResult(BaseModel):
    """JSON-safe result returned by one tool execution."""

    model_config = ConfigDict(extra="forbid")

    payload: dict[str, Any] | str = Field(default_factory=dict)
    error: bool = False
    message: str = ""

    @field_validator("payload", mode="before")
    @classmethod
    def validate_payload(cls, value: object) -> object:
        return ensure_json_safe(value)


@runtime_checkable
class ToolExecutor(Protocol):
    """Async tool surface used by a runtime adapter."""

    def describe(self) -> list[ToolDescription]:
        """Return the public names, documentation, and argument schemas."""

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Execute one named tool with JSON-safe arguments."""


@runtime_checkable
class EventSink(Protocol):
    """Observable trajectory event sink used by runtime adapters."""

    async def emit(
        self,
        event_type: TrajectoryEventType | str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        """Append one event at a runtime boundary."""


class RuntimeResult(BaseModel):
    """Result returned by one runtime execution."""

    model_config = ConfigDict(extra="forbid")

    status: RunStatus
    final_answer: str | None = None
    metrics: RolloutMetrics = Field(
        default_factory=lambda: RolloutMetrics(
            wall_seconds=0.0,
            model_turns=0,
            tool_calls=0,
            input_tokens=None,
            output_tokens=None,
            estimated_cost=None,
        )
    )
    error: str | None = None


@runtime_checkable
class RuntimeAdapter(Protocol):
    """Thin runtime contract described by SPEC §23."""

    async def run(
        self,
        goal: str,
        package: AgentPackage,
        environment: ToolExecutor,
        event_sink: EventSink,
        budget: ExecutionBudget,
    ) -> RuntimeResult:
        """Run one agent against one task goal and execution environment."""


__all__ = [
    "AgentTaskView",
    "EventSink",
    "RuntimeAdapter",
    "RuntimeResult",
    "ToolDescription",
    "ToolExecutor",
    "ToolResult",
]
