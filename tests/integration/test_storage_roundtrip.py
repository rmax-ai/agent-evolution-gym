"""Runner, filesystem, and SQLite storage integration coverage."""

import json
from pathlib import Path

from domains.confluence.scenarios.edit_page import EditPageScenario

from agentgym.core.package import AgentPackage
from agentgym.runner.runner import Runner, RunnerConfig
from agentgym.runtime.llm import FakeLLM
from agentgym.storage.filesystem import RunStore, StorageIntegrityError
from agentgym.storage.sqlite import IndexStore
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
                        "arguments": {
                            "page_id": target,
                            "version": 1,
                            "body": expected_body,
                        },
                    }
                ]
            }
        return {"content": "Updated the page."}

    return FakeLLM(script)


async def test_runner_storage_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    task = EditPageScenario(snapshot_dir=tmp_path).generate(1100)
    package = AgentPackage.load("packages/baseline")
    run_dir = tmp_path / "runs" / "run-001"
    sqlite_path = tmp_path / "index.sqlite"

    rollout = await Runner(
        config=RunnerConfig(sqlite_path=sqlite_path, model_provider="test", model_identifier="fake")
    ).run(
        task,
        package,
        ProcessWorldProvider(tmp_path / task.initial_snapshot_ref),
        _scripted_edit_llm(task),
        run_dir,
    )

    loaded = RunStore().load_run(run_dir)
    indexed = await IndexStore(sqlite_path).runs_by_package(package.id)

    assert rollout.verification.passed is True
    assert loaded["manifest"]["task_id"] == task.id
    assert loaded["trajectory"][-1].type.value == "run.completed"
    assert indexed[0]["run_id"] == rollout.id

    final_state = json.loads((run_dir / "final-state.json").read_text(encoding="utf-8"))
    final_state["tampered"] = True
    (run_dir / "final-state.json").write_text(json.dumps(final_state), encoding="utf-8")

    try:
        RunStore().load_run(run_dir)
    except StorageIntegrityError:
        pass
    else:
        raise AssertionError("tampered final-state.json was accepted")
