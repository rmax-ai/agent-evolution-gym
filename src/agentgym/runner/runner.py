"""End-to-end task runner for process worlds and the reference runtime."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from agentgym.core.package import AgentPackage
from agentgym.core.rollout import Rollout, RunStatus
from agentgym.core.scenario import read_snapshot
from agentgym.core.task import Task
from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType
from agentgym.core.verification import AssertionResult, VerificationResult
from agentgym.runner.budgets import BudgetTracker, ExecutionBudget
from agentgym.runner.lifecycle import world_session
from agentgym.runtime.base import (
    AgentTaskView,
    EventSink,
    ToolDescription,
    ToolExecutor,
    ToolResult,
)
from agentgym.runtime.llm import LLMClient
from agentgym.runtime.reference_agent import ReferenceAgent
from agentgym.world.base import World
from agentgym.world.process import ProcessWorldError, ProcessWorldProvider
from agentgym.world.snapshot import WorldSnapshot


class RunnerError(RuntimeError):
    """Raised for a runner setup or artifact-resolution failure."""


class _VerifierFailure(RuntimeError):
    """Internal wrapper distinguishing verifier faults from world faults."""


class RunnerRollout(Rollout):
    """Rollout plus the §31 status produced by orchestration."""

    status: RunStatus
    error: str | None = None


class _TrajectoryRecorder(EventSink):
    def __init__(self) -> None:
        self.events: list[TrajectoryEvent] = []

    async def emit(
        self,
        event_type: TrajectoryEventType | str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        event = TrajectoryEvent(
            sequence=len(self.events) + 1,
            timestamp=datetime.now(UTC).isoformat(),
            type=event_type,
            actor=actor,
            payload=payload,
        )
        self.events.append(event)


class Runner:
    """Provision a fresh world, run an agent, verify, and persist artifacts."""

    def __init__(
        self,
        *,
        domain_package: str = "domains.confluence",
        verifier_ref: str | None = None,
        verifier_modules: Sequence[str] | None = None,
        package_root: str | Path | None = None,
        snapshot_root: str | Path | None = None,
        default_budget: ExecutionBudget | None = None,
    ) -> None:
        self.domain_package = domain_package
        selected_verifier = verifier_ref
        if selected_verifier is None and verifier_modules:
            selected_verifier = verifier_modules[0]
        self.verifier_ref = selected_verifier or "verifiers.page_edit"
        self.package_root = Path(package_root).resolve() if package_root is not None else None
        self.snapshot_root = Path(snapshot_root).resolve() if snapshot_root is not None else None
        self.default_budget = default_budget or ExecutionBudget()

    async def run(
        self,
        task: Task,
        package: AgentPackage,
        world_provider: World | None,
        llm_client: LLMClient,
        run_dir: str | Path,
        *,
        budget: ExecutionBudget | None = None,
    ) -> RunnerRollout:
        """Execute one task/package pair and return a status-bearing rollout."""

        # Artifact paths are deliberately run-scoped.  The filesystem store is
        # synchronous in this story; all world/model IO remains async.
        artifact_dir = Path(run_dir).resolve()  # noqa: ASYNC240
        artifact_dir.mkdir(parents=True, exist_ok=True)
        recorder = _TrajectoryRecorder()
        tracker = BudgetTracker(budget or self.default_budget)
        await recorder.emit(
            TrajectoryEventType.RUN_STARTED,
            "runner",
            {"task_id": task.id, "package_id": package.id},
        )

        initial_path = None
        initial_snapshot: WorldSnapshot | None = None
        final_snapshot: WorldSnapshot | None = None
        verification = _not_verified("run did not reach verifier")
        status = RunStatus.ENVIRONMENT_ERROR
        error: str | None = None
        runtime_result = None
        world = world_provider

        try:
            initial_path = self._resolve_snapshot_path(task, artifact_dir)
            initial_snapshot = read_snapshot(initial_path)
            _write_json(
                artifact_dir / "initial_state.json", initial_snapshot.model_dump(mode="json")
            )

            if world is None:
                world = ProcessWorldProvider(initial_path)
            async with world_session(world, initial_snapshot) as active_world:
                capabilities = await active_world.capabilities()
                package_dir = self._resolve_package_root(package)
                world_url = _world_url(active_world)
                executor = await self._build_executor(
                    package=package,
                    package_dir=package_dir,
                    world_url=world_url,
                    actor_id=task.actor_id,
                    capabilities=capabilities,
                    event_sink=recorder,
                    concurrency_hook=self._concurrency_hook(task, active_world, recorder),
                )
                task_view = AgentTaskView.from_tools(
                    goal=task.goal,
                    actor_id=task.actor_id,
                    tools=executor.describe(),
                )
                agent = ReferenceAgent(
                    llm_client,
                    package_root=package_dir,
                )
                runtime_result = await agent.run(
                    task_view,
                    package,
                    executor,
                    recorder,
                    tracker,
                )
                if getattr(executor, "infrastructure_error", None) is not None:
                    raise RunnerError(str(executor.infrastructure_error))
                final_snapshot = await active_world.snapshot()

            if final_snapshot is None:
                raise RunnerError("world did not return a final snapshot")
            _write_json(artifact_dir / "final_state.json", final_snapshot.model_dump(mode="json"))
            status = _runtime_status(runtime_result.status)
            if runtime_result.status not in {
                RunStatus.AGENT_ERROR,
                RunStatus.TOOL_ERROR,
                RunStatus.TIMEOUT,
                RunStatus.BUDGET_EXCEEDED,
                RunStatus.POLICY_VIOLATION,
            }:
                verification = await self._verify_checked(
                    task, initial_snapshot, final_snapshot, recorder.events
                )
                await self._emit_verification(recorder, verification)
                status = _status_after_verification(verification)
            elif runtime_result.status == RunStatus.TOOL_ERROR:
                verification = await self._verify_checked(
                    task, initial_snapshot, final_snapshot, recorder.events
                )
                await self._emit_verification(recorder, verification)
        except _VerifierFailure as exc:
            error = str(exc)
            status = RunStatus.VERIFIER_ERROR
            verification = _not_verified(error)
            if final_snapshot is not None:
                _write_json(
                    artifact_dir / "final_state.json", final_snapshot.model_dump(mode="json")
                )
        except (ProcessWorldError, RunnerError, OSError, ValueError) as exc:
            error = str(exc)
            status = RunStatus.ENVIRONMENT_ERROR
            verification = _not_verified(error)
            if final_snapshot is None and initial_snapshot is not None:
                _write_json(
                    artifact_dir / "final_state.json", initial_snapshot.model_dump(mode="json")
                )
        except Exception as exc:
            error = str(exc)
            status = RunStatus.ENVIRONMENT_ERROR
            verification = _not_verified(error)
            if final_snapshot is None and initial_snapshot is not None:
                _write_json(
                    artifact_dir / "final_state.json", initial_snapshot.model_dump(mode="json")
                )

        if runtime_result is not None and runtime_result.error is not None and error is None:
            error = runtime_result.error

        await recorder.emit(
            TrajectoryEventType.RUN_COMPLETED,
            "runner",
            {"status": status.value, "error": error},
        )
        _write_trajectory(artifact_dir / "trajectory.jsonl", recorder.events)
        _write_json(
            artifact_dir / "manifest.json",
            {"task_id": task.id, "package_id": package.id, "status": status.value},
        )

        initial_ref = "initial_state.json"
        final_ref = "final_state.json"
        metrics = tracker.metrics()
        return RunnerRollout(
            id=f"rollout-{task.id}-{uuid.uuid4().hex[:12]}",
            task_id=task.id,
            package_id=package.id,
            initial_state_ref=initial_ref,
            final_state_ref=final_ref,
            trajectory_ref="trajectory.jsonl",
            verification=verification,
            metrics=metrics,
            status=status,
            error=error,
        )

    async def _build_executor(
        self,
        *,
        package: AgentPackage,
        package_dir: Path,
        world_url: str,
        actor_id: str,
        capabilities: Sequence[Any],
        event_sink: EventSink,
        concurrency_hook: Callable[[str, dict[str, Any], ToolResult], Awaitable[None]],
    ) -> _BaselineToolExecutor:
        """Load baseline tools for the reference runtime.

        This story uses a direct in-process executor so the orchestration path
        is testable without another child process.  The generic MCP stdio
        executor and its isolation adapter are intentionally deferred to story
        #40, as recorded in D3.
        """

        server_path = package_dir / package.tools.root / package.tools.server_entrypoint
        if not server_path.is_file():
            fallback = Path.cwd() / "packages" / "baseline" / "mcp" / "server.py"
            if fallback.is_file():
                server_path = fallback
            else:
                raise RunnerError(f"MCP server entrypoint does not exist: {server_path}")
        module = _import_module_from_path(server_path)
        mcp = getattr(module, "mcp", None)
        if mcp is None or not callable(getattr(mcp, "list_tools", None)):
            raise RunnerError(f"MCP server has no FastMCP tool registry: {server_path}")
        raw_tools = await mcp.list_tools()
        granted = {capability.id for capability in capabilities}
        declared = set(package.tools.declared_capabilities)
        effective = granted & declared if declared else granted
        descriptions: list[ToolDescription] = []
        functions: dict[str, Callable[..., Any]] = {}
        for raw_tool in raw_tools:
            name = getattr(raw_tool, "name", None)
            function = getattr(raw_tool, "fn", None)
            if not isinstance(name, str) or not callable(function):
                continue
            required = _required_capability(name)
            if required is not None and required not in effective:
                continue
            parameters = getattr(raw_tool, "parameters", {})
            descriptions.append(
                ToolDescription(
                    name=name,
                    description=str(getattr(raw_tool, "description", "") or ""),
                    parameters=dict(parameters) if isinstance(parameters, Mapping) else {},
                )
            )
            functions[name] = function
        return _BaselineToolExecutor(
            functions=functions,
            descriptions=descriptions,
            world_url=world_url,
            actor_id=actor_id,
            event_sink=event_sink,
            after_success=concurrency_hook,
        )

    def _concurrency_hook(
        self,
        task: Task,
        world: World,
        event_sink: EventSink,
    ) -> Callable[[str, dict[str, Any], ToolResult], Awaitable[None]]:
        concurrency = task.metadata.get("concurrency")
        fired = False

        async def hook(name: str, args: dict[str, Any], result: ToolResult) -> None:
            nonlocal fired
            if fired or name != "get_page" or result.error or not isinstance(concurrency, Mapping):
                return
            page_id = concurrency.get("page_id")
            if not isinstance(page_id, str) or args.get("page_id") != page_id:
                return
            human_edit = concurrency.get("human_edit")
            if not isinstance(human_edit, Mapping):
                return
            body = human_edit.get("body")
            actor = human_edit.get("actor", "human-editor")
            if not isinstance(body, str) or not isinstance(actor, str):
                return
            fired = True
            await event_sink.emit(
                TrajectoryEventType.WORLD_API_REQUEST,
                "runner",
                {"operation": "human-edit", "page_id": page_id, "actor": actor},
            )
            human_edit_method = getattr(world, "human_edit", None)
            if not callable(human_edit_method):
                raise RunnerError("world provider does not support the concurrency control hook")
            try:
                response = human_edit_method(page_id, actor, body)
                if inspect.isawaitable(response):
                    response = await response
            except Exception as error:
                raise RunnerError(f"concurrency control hook failed: {error}") from error
            await event_sink.emit(
                TrajectoryEventType.WORLD_API_RESPONSE,
                "runner",
                {"operation": "human-edit", "page_id": page_id, "version": response.get("version")}
                if isinstance(response, Mapping)
                else {"operation": "human-edit", "page_id": page_id},
            )

        return hook

    async def _verify(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        events: Sequence[TrajectoryEvent],
    ) -> VerificationResult:
        module_name = f"{self.domain_package}.{self.verifier_ref}"
        module = importlib.import_module(module_name)
        verifier = module.VERIFIER
        verify_method = getattr(verifier, "verify", None)
        if not callable(verify_method):
            verify_method = getattr(module, "verify", None)
        if not callable(verify_method):
            raise RunnerError(f"verifier module has no verify entrypoint: {module_name}")
        result = verify_method(task, initial, final, events)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, VerificationResult):
            raise RunnerError("verifier returned an invalid VerificationResult")
        return result

    async def _verify_checked(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        events: Sequence[TrajectoryEvent],
    ) -> VerificationResult:
        try:
            return await self._verify(task, initial, final, events)
        except Exception as error:
            raise _VerifierFailure(f"verifier failed: {error}") from error

    async def _emit_verification(
        self,
        recorder: _TrajectoryRecorder,
        verification: VerificationResult,
    ) -> None:
        for assertion in verification.assertions:
            await recorder.emit(
                TrajectoryEventType.VERIFICATION_ASSERTION,
                "verifier",
                assertion.model_dump(mode="json"),
            )
        await recorder.emit(
            TrajectoryEventType.VERIFICATION_COMPLETED,
            "verifier",
            {"passed": verification.passed, "score": verification.score},
        )

    def _resolve_snapshot_path(self, task: Task, run_dir: Path) -> Path:
        reference = Path(task.initial_snapshot_ref)
        if reference.is_absolute() and reference.is_file():
            return reference
        roots = [run_dir, run_dir.parent]
        if self.snapshot_root is not None:
            roots.insert(0, self.snapshot_root)
        roots.extend([Path.cwd(), Path(__file__).resolve().parents[3]])
        for root in roots:
            candidate = (root / reference).resolve()
            if candidate.is_file():
                return candidate
        raise RunnerError(
            "initial snapshot "
            f"{task.initial_snapshot_ref!r} was not found relative to run artifacts"
        )

    def _resolve_package_root(self, package: AgentPackage) -> Path:
        if self.package_root is not None:
            return self.package_root
        metadata_root = package.metadata.get("root")
        candidates = []
        if isinstance(metadata_root, str):
            candidates.append(Path(metadata_root))
        candidates.extend(
            [
                Path.cwd() / "packages" / package.id,
                Path(__file__).resolve().parents[3] / "packages" / package.id,
            ]
        )
        for candidate in candidates:
            resolved = candidate.expanduser().resolve()
            if resolved.is_dir():
                return resolved
        raise RunnerError(f"package root not found for {package.id!r}")


class _BaselineToolExecutor(ToolExecutor):
    def __init__(
        self,
        *,
        functions: Mapping[str, Callable[..., Any]],
        descriptions: Sequence[ToolDescription],
        world_url: str,
        actor_id: str,
        event_sink: EventSink,
        after_success: Callable[[str, dict[str, Any], ToolResult], Awaitable[None]],
    ) -> None:
        self._functions = dict(functions)
        self._descriptions = list(descriptions)
        self._world_url = world_url.rstrip("/")
        self._actor_id = actor_id
        self._event_sink = event_sink
        self._after_success = after_success
        self.infrastructure_error: BaseException | None = None

    def describe(self) -> list[ToolDescription]:
        return [description.model_copy(deep=True) for description in self._descriptions]

    async def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        function = self._functions.get(name)
        if function is None:
            return ToolResult(
                payload={"error": f"unknown tool: {name}"}, error=True, message="unknown tool"
            )
        await self._event_sink.emit(
            TrajectoryEventType.WORLD_API_REQUEST,
            "world",
            {"tool": name, "arguments": args},
        )
        old_world = os.environ.get("WORLD_API_URL")
        old_actor = os.environ.get("ACTOR_ID")
        os.environ["WORLD_API_URL"] = self._world_url
        os.environ["ACTOR_ID"] = self._actor_id
        try:
            value = function(**args)
            if inspect.isawaitable(value):
                value = await value
            payload = _tool_payload(value)
            result = ToolResult(payload=payload, error=False, message="")
            try:
                await self._after_success(name, args, result)
            except Exception as error:
                self.infrastructure_error = error
                result = ToolResult(payload={"error": str(error)}, error=True, message=str(error))
            await self._event_sink.emit(
                TrajectoryEventType.WORLD_API_RESPONSE,
                "world",
                {"tool": name, "error": result.error},
            )
            return result
        except Exception as error:
            result = ToolResult(payload={"error": str(error)}, error=True, message=str(error))
            await self._event_sink.emit(
                TrajectoryEventType.WORLD_API_RESPONSE,
                "world",
                {"tool": name, "error": True, "message": str(error)},
            )
            return result
        finally:
            _restore_environment("WORLD_API_URL", old_world)
            _restore_environment("ACTOR_ID", old_actor)


def _import_module_from_path(path: Path) -> ModuleType:
    name = f"agentgym_runtime_tools_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RunnerError(f"could not import MCP server: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as error:
        sys.modules.pop(name, None)
        raise RunnerError(f"could not load MCP server {path}: {error}") from error
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return module


def _world_url(world: World) -> str:
    for attribute in ("base_url", "url"):
        value = getattr(world, attribute, None)
        if isinstance(value, str) and value:
            return value
    raise RunnerError("world provider does not expose a loopback base URL")


def _required_capability(tool_name: str) -> str | None:
    if tool_name == "search_pages":
        return "confluence.search"
    if tool_name in {"get_page", "get_page_versions"}:
        return "confluence.pages.read"
    if tool_name in {"create_page", "update_page"}:
        return "confluence.pages.write"
    return None


def _tool_payload(value: object) -> dict[str, Any] | str:
    if isinstance(value, (dict, str)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _restore_environment(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def _runtime_status(status: RunStatus) -> RunStatus:
    return status


def _status_after_verification(verification: VerificationResult) -> RunStatus:
    if verification.passed:
        return RunStatus.PASS
    return RunStatus.PARTIAL if verification.score > 0 else RunStatus.TASK_FAIL


def _not_verified(reason: str) -> VerificationResult:
    return VerificationResult(
        passed=False,
        score=0.0,
        assertions=[
            AssertionResult(
                id="verification-not-run",
                passed=False,
                category="invariant",
                expected=None,
                actual=None,
                message=reason,
            )
        ],
        required_changes_passed=False,
        forbidden_changes_passed=False,
        invariants_passed=False,
        metadata={"verified": False, "reason": reason},
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_trajectory(path: Path, events: Sequence[TrajectoryEvent]) -> None:
    path.write_text(
        "".join(
            json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n" for event in events
        ),
        encoding="utf-8",
    )


async def run(
    task: Task,
    package: AgentPackage,
    world_provider: World | None,
    llm_client: LLMClient,
    run_dir: str | Path,
    *,
    budget: ExecutionBudget | None = None,
) -> RunnerRollout:
    """Module-level convenience wrapper around :class:`Runner`."""

    return await Runner().run(task, package, world_provider, llm_client, run_dir, budget=budget)


__all__ = ["Runner", "RunnerError", "RunnerRollout", "run"]
