"""Generic, deliberately task-agnostic tool-calling reference runtime."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from agentgym.core.package import AgentPackage
from agentgym.core.rollout import RunStatus
from agentgym.core.trajectory import TrajectoryEventType
from agentgym.runner.budgets import BudgetExceeded, BudgetTracker, ExecutionBudget
from agentgym.runtime.base import (
    AgentTaskView,
    RuntimeResult,
    ToolDescription,
    ToolExecutor,
    ToolResult,
)
from agentgym.runtime.llm import LLMClient, LLMResponse


class ReferenceAgent:
    """Run a generic model loop over the tools exposed by an executor."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        *,
        llm: LLMClient | None = None,
        package_root: str | Path | None = None,
    ) -> None:
        client = llm_client or llm
        if client is None:
            raise ValueError("ReferenceAgent requires an llm_client")
        self.llm_client: LLMClient = client
        self.package_root = Path(package_root).resolve() if package_root is not None else None

    def build_system_prompt(
        self,
        task: AgentTaskView,
        package: AgentPackage,
        executor: ToolExecutor,
    ) -> str:
        """Concatenate declared package artifacts and the public tool surface."""

        package_root = self._resolve_package_root(package)
        sections = [
            "You are a general-purpose enterprise task agent.",
            f"Acting actor id: {task.actor_id}",
            "Complete the user's goal using only the tools listed below. "
            "Do not claim a state change unless a tool result supports it.",
            "",
            "# Package knowledge",
        ]
        for artifact in package.knowledge:
            sections.extend(
                [
                    f"\n## Knowledge: {artifact.path}",
                    _read_artifact(package_root, "knowledge", artifact.path),
                ]
            )
        if not package.knowledge:
            sections.append("(none)")

        sections.append("\n# Package skills")
        for artifact in package.skills:
            sections.extend(
                [
                    f"\n## Skill: {artifact.path}",
                    _read_artifact(package_root, "skills", artifact.path),
                ]
            )
        if not package.skills:
            sections.append("(none)")

        descriptions = _descriptions(executor)
        sections.append("\n# Available tools")
        for description in descriptions:
            sections.extend(
                [
                    f"\n## {description.name}",
                    description.description or "No description provided.",
                    f"Arguments JSON schema: {json.dumps(description.parameters, sort_keys=True)}",
                ]
            )
        if not descriptions:
            sections.append("(none)")
        return "\n".join(sections)

    async def run(
        self,
        task: AgentTaskView | str,
        package: AgentPackage,
        executor: ToolExecutor,
        event_sink: object | None = None,
        budget: ExecutionBudget | BudgetTracker | None = None,
        *,
        actor_id: str | None = None,
    ) -> RuntimeResult:
        """Run the model/tool loop without task-specific reasoning."""

        if isinstance(task, str):
            view = AgentTaskView.from_tools(
                goal=task,
                actor_id=actor_id or "",
                tools=_descriptions(executor),
            )
        else:
            view = task
        tracker = (
            budget
            if isinstance(budget, BudgetTracker)
            else BudgetTracker(budget or ExecutionBudget())
        )
        tools = [_openai_tool(description) for description in _descriptions(executor)]
        system_prompt = self.build_system_prompt(view, package, executor)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": view.goal},
        ]
        had_tool_error = False

        await _emit(
            event_sink, TrajectoryEventType.AGENT_STARTED, "agent", {"actor_id": view.actor_id}
        )
        try:
            while True:
                tracker.check_wall()
                tracker.check_and_bump("model_turns")
                await _emit(
                    event_sink,
                    TrajectoryEventType.MODEL_REQUEST,
                    "agent",
                    {"messages": messages, "tools": tools},
                )
                response = await self.llm_client.complete(messages, tools)
                if not isinstance(response, LLMResponse):
                    raise TypeError("LLM client returned an invalid response")
                tracker.check_wall()
                tracker.record_tokens(response.input_tokens, response.output_tokens)
                await _emit(
                    event_sink,
                    TrajectoryEventType.MODEL_RESPONSE,
                    "model",
                    {
                        "content": response.content,
                        "tool_calls": [
                            call.model_dump(mode="json") for call in response.tool_calls
                        ],
                    },
                )

                if not response.tool_calls:
                    final_answer = response.content
                    await _emit(
                        event_sink,
                        TrajectoryEventType.AGENT_COMPLETED,
                        "agent",
                        {"final_answer": final_answer},
                    )
                    status = RunStatus.TOOL_ERROR if had_tool_error else RunStatus.PASS
                    return RuntimeResult(
                        status=status,
                        final_answer=final_answer,
                        metrics=tracker.metrics(),
                    )

                messages.append(_assistant_tool_message(response))
                for tool_call in response.tool_calls:
                    tracker.check_wall()
                    tracker.check_and_bump("tool_calls")
                    arguments = dict(tool_call.arguments)
                    await _emit(
                        event_sink,
                        TrajectoryEventType.TOOL_CALL,
                        "agent",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": arguments,
                        },
                    )
                    try:
                        result = await executor.execute(tool_call.name, arguments)
                    except Exception as error:  # tool boundary: keep the loop observable
                        result = ToolResult(
                            payload={"error": str(error)}, error=True, message=str(error)
                        )
                    if result.error:
                        had_tool_error = True
                    await _emit(
                        event_sink,
                        TrajectoryEventType.TOOL_RESULT,
                        "tool",
                        {
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "payload": result.payload,
                            "error": result.error,
                            "message": result.message,
                        },
                    )
                    if result.error:
                        await _emit(
                            event_sink,
                            TrajectoryEventType.TOOL_ERROR,
                            "tool",
                            {
                                "id": tool_call.id,
                                "name": tool_call.name,
                                "message": result.message,
                            },
                        )
                    messages.append(_tool_message(tool_call.id, result))
        except BudgetExceeded as error:
            status = (
                RunStatus.TIMEOUT
                if error.dimension == "wall_seconds"
                else RunStatus.BUDGET_EXCEEDED
            )
            await _emit(
                event_sink,
                TrajectoryEventType.AGENT_ERROR,
                "agent",
                {"status": status.value, "error": str(error)},
            )
            return RuntimeResult(status=status, metrics=tracker.metrics(), error=str(error))
        except Exception as error:
            await _emit(
                event_sink,
                TrajectoryEventType.AGENT_ERROR,
                "agent",
                {"status": RunStatus.AGENT_ERROR.value, "error": str(error)},
            )
            return RuntimeResult(
                status=RunStatus.AGENT_ERROR,
                metrics=tracker.metrics(),
                error=str(error),
            )

    def _resolve_package_root(self, package: AgentPackage) -> Path | None:
        if self.package_root is not None:
            return self.package_root
        metadata_root = package.metadata.get("root")
        if isinstance(metadata_root, str):
            candidate = Path(metadata_root).expanduser().resolve()
            if candidate.is_dir():
                return candidate
        for candidate in (
            Path.cwd() / "packages" / package.id,
            Path(__file__).resolve().parents[3] / "packages" / package.id,
        ):
            if candidate.is_dir():
                return candidate
        return None


async def _emit(
    sink: object | None, event_type: TrajectoryEventType, actor: str, payload: dict[str, Any]
) -> None:
    if sink is None:
        return
    emit = getattr(sink, "emit", None)
    value: Any
    if callable(emit):
        value = emit(event_type, actor, payload)
    elif callable(sink):
        callback = cast(Callable[[TrajectoryEventType, str, dict[str, Any]], Any], sink)
        value = callback(event_type, actor, payload)
    else:
        return
    if inspect.isawaitable(value):
        await value


def _openai_tool(description: ToolDescription) -> dict[str, Any]:
    parameters = description.parameters or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": description.name,
            "description": description.description,
            "parameters": parameters,
        },
    }


def _descriptions(executor: ToolExecutor) -> list[ToolDescription]:
    return [
        description
        if isinstance(description, ToolDescription)
        else ToolDescription.model_validate(description)
        for description in executor.describe()
    ]


def _assistant_tool_message(response: LLMResponse) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": response.content,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, sort_keys=True),
                },
            }
            for call in response.tool_calls
        ],
    }


def _tool_message(tool_call_id: str, result: ToolResult) -> dict[str, Any]:
    content: object = result.payload
    if result.error:
        content = {"error": result.message, "payload": result.payload}
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
    }


def _read_artifact(root: Path | None, layer: str, relative_path: str) -> str:
    if root is None:
        return f"(artifact unavailable: {layer}/{relative_path})"
    path = (root / layer / relative_path).resolve()
    try:
        path.relative_to((root / layer).resolve())
    except ValueError as error:
        raise ValueError(f"package artifact escapes {layer}: {relative_path}") from error
    return path.read_text(encoding="utf-8")


__all__ = ["ReferenceAgent"]
