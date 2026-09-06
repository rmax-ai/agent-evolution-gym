"""End-to-end runner coverage with a deterministic fake model."""

import json
from pathlib import Path

from domains.confluence.scenarios.edit_page import EditPageScenario

from agentgym.core.package import AgentPackage
from agentgym.core.rollout import RunStatus
from agentgym.core.trajectory import TrajectoryEvent
from agentgym.runner.budgets import ExecutionBudget
from agentgym.runner.runner import Runner
from agentgym.runtime.llm import FakeLLM
from agentgym.world.process import ProcessWorldProvider


def _scripted_edit_llm(task):
    target = task.metadata["verifier_config"]["expected_page_ids"][0]
    expected_body = task.metadata["verifier_config"]["expected_final_body"]
    calls = 0

    def script(_messages, _tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "tool_calls": [
                    {"id": "search", "name": "search_pages", "arguments": {"query": "Deployment"}}
                ]
            }
        if calls == 2:
            return {
                "tool_calls": [{"id": "get", "name": "get_page", "arguments": {"page_id": target}}]
            }
        if calls == 3:
            return {
                "tool_calls": [
                    {
                        "id": "update",
                        "name": "update_page",
                        "arguments": {"page_id": target, "version": 1, "body": expected_body},
                    }
                ]
            }
        return {"content": "Updated the page."}

    return FakeLLM(script)


async def test_runner_stub_edit_verifies_and_writes_trajectory(tmp_path: Path) -> None:
    task = EditPageScenario(snapshot_dir=tmp_path).generate(1100)
    package = AgentPackage.load("packages/baseline")
    provider = ProcessWorldProvider(tmp_path / task.initial_snapshot_ref)

    rollout = await Runner().run(
        task,
        package,
        provider,
        _scripted_edit_llm(task),
        tmp_path / "run",
    )

    assert rollout.status is RunStatus.PASS
    assert rollout.verification.passed is True
    assert rollout.status is not RunStatus.VERIFIER_ERROR
    events = [
        TrajectoryEvent.model_validate(json.loads(line))
        for line in (tmp_path / "run" / "trajectory.jsonl").read_text().splitlines()
    ]
    assert any(event.type.value == "tool.call" for event in events)
    completion = next(event for event in events if event.type.value == "agent.completed")
    assert completion.payload["final_answer"] == "Updated the page."


async def test_runner_stops_infinite_tool_loop_at_budget(tmp_path: Path) -> None:
    task = EditPageScenario(snapshot_dir=tmp_path).generate(1100)
    package = AgentPackage.load("packages/baseline")
    provider = ProcessWorldProvider(tmp_path / task.initial_snapshot_ref)
    llm = FakeLLM(
        [
            {
                "tool_calls": [
                    {
                        "id": "loop",
                        "name": "search_pages",
                        "arguments": {"query": "Deployment"},
                    }
                ]
            }
        ]
    )

    rollout = await Runner().run(
        task,
        package,
        provider,
        llm,
        tmp_path / "budget-run",
        budget=ExecutionBudget(max_model_turns=2, max_tool_calls=100),
    )

    assert rollout.status in {RunStatus.BUDGET_EXCEEDED, RunStatus.TIMEOUT}
    assert rollout.status is not RunStatus.VERIFIER_ERROR
