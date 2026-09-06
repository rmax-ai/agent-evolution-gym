"""Phase-3 acceptance proof over every Confluence curriculum task."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from domains.confluence.scenarios._common import replace_section
from domains.confluence.verifiers.page_edit import verify

from agentgym.core.scenario import read_snapshot
from agentgym.core.splits import load_split
from agentgym.core.task import Task
from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType
from agentgym.runner.curriculum import materialize
from agentgym.world.snapshot import WorldSnapshot
from agentgym.world.store import InMemoryConfluenceStore


def _completion_trajectory(task: Task) -> list[TrajectoryEvent]:
    expected_response = task.metadata["verifier_config"].get("expected_response")
    if not isinstance(expected_response, str):
        return []
    return [
        TrajectoryEvent(
            sequence=1,
            timestamp="2026-09-06T00:00:00+00:00",
            type=TrajectoryEventType.AGENT_COMPLETED,
            actor="agent",
            payload={"final_answer": f"The reported guidance is: {expected_response}"},
        )
    ]


def _final_snapshot(store: InMemoryConfluenceStore) -> WorldSnapshot:
    return store.snapshot(
        snapshot_id="final",
        timestamp="2026-09-06T00:00:01+00:00",
    )


def _target_id(task: Task) -> str:
    return task.metadata["verifier_config"]["expected_page_ids"][0]


def _apply_trusted_action(task: Task, store: InMemoryConfluenceStore) -> None:
    family = task.metadata["family"]
    config = task.metadata["verifier_config"]
    target_id = _target_id(task)

    if family in {"edit_page", "preservation"}:
        store.update_page(
            target_id,
            body=config["expected_final_body"],
            expected_version=store.pages[target_id]["version"],
        )
    elif family == "concurrent_edit":
        human_edit = task.metadata["concurrency"]["human_edit"]
        human_body = human_edit["body"] if isinstance(human_edit, Mapping) else human_edit
        store.update_page(
            target_id,
            body=human_body,
            expected_version=store.pages[target_id]["version"],
        )
        store.update_page(
            target_id,
            body=config["expected_final_body"],
            expected_version=store.pages[target_id]["version"],
        )
    elif family == "permissions" and task.metadata["mode"] == "allowed":
        body = replace_section(
            store.pages[target_id]["body"],
            "Change control",
            config["expected_content_fragments"][target_id],
        )
        store.update_page(
            target_id,
            body=body,
            expected_version=store.pages[target_id]["version"],
        )


def _materialized_tasks(tmp_path: Path) -> list[Task]:
    tasks: list[Task] = []
    for split_name in ("train", "validation", "test"):
        split = load_split(f"domains/confluence/splits/{split_name}.yaml")
        tasks.extend(
            materialize(
                split,
                "domains.confluence",
                snapshot_root=tmp_path / split_name,
                split_name=split_name,
            )
        )
    return tasks


async def test_trusted_oracle_passes_every_manifest_task(tmp_path: Path) -> None:
    tasks = _materialized_tasks(tmp_path)

    assert len(tasks) == 37
    for task in tasks:
        initial = read_snapshot((tmp_path / task.split) / task.initial_snapshot_ref)
        store = InMemoryConfluenceStore(resources=initial.resources)
        _apply_trusted_action(task, store)

        result = await verify(task, initial, _final_snapshot(store), _completion_trajectory(task))

        assert result.passed, (task.id, [assertion.message for assertion in result.assertions])


async def test_wrong_oracle_variants_fail_expected_checks(tmp_path: Path) -> None:
    tasks = _materialized_tasks(tmp_path)

    preservation = next(task for task in tasks if task.metadata["family"] == "preservation")
    initial = read_snapshot((tmp_path / preservation.split) / preservation.initial_snapshot_ref)
    store = InMemoryConfluenceStore(resources=initial.resources)
    target_id = _target_id(preservation)
    store.update_page(
        target_id,
        body=preservation.metadata["verifier_config"]["expected_content_fragments"][target_id],
        expected_version=1,
    )
    result = await verify(preservation, initial, _final_snapshot(store), [])
    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == f"page-body-exact:{target_id}"
    ).passed

    concurrent = next(task for task in tasks if task.metadata["family"] == "concurrent_edit")
    initial = read_snapshot((tmp_path / concurrent.split) / concurrent.initial_snapshot_ref)
    store = InMemoryConfluenceStore(resources=initial.resources)
    target_id = _target_id(concurrent)
    human_body = concurrent.metadata["concurrency"]["human_edit"]["body"]
    store.update_page(target_id, body=human_body, expected_version=1)
    store.update_page(
        target_id,
        body=concurrent.metadata["verifier_config"]["expected_content_fragments"][target_id],
        expected_version=2,
    )
    result = await verify(concurrent, initial, _final_snapshot(store), [])
    assert not result.passed

    denied_write = next(
        task
        for task in tasks
        if task.metadata["family"] == "permissions" and task.metadata["mode"] == "denied_write"
    )
    initial = read_snapshot((tmp_path / denied_write.split) / denied_write.initial_snapshot_ref)
    store = InMemoryConfluenceStore(resources=initial.resources)
    target_id = _target_id(denied_write)
    store.update_page(target_id, body="unauthorized mutation", expected_version=1)
    result = await verify(denied_write, initial, _final_snapshot(store), [])
    assert not result.passed

    retrieval = next(task for task in tasks if task.metadata["family"] == "retrieval")
    initial = read_snapshot((tmp_path / retrieval.split) / retrieval.initial_snapshot_ref)
    store = InMemoryConfluenceStore(resources=initial.resources)
    target_id = _target_id(retrieval)
    store.update_page(
        target_id,
        body=f"{store.pages[target_id]['body']}\n\nmutation",
        expected_version=store.pages[target_id]["version"],
    )
    result = await verify(
        retrieval,
        initial,
        _final_snapshot(store),
        _completion_trajectory(retrieval),
    )
    assert not result.passed

    no_op = InMemoryConfluenceStore(resources=initial.resources)
    result = await verify(retrieval, initial, _final_snapshot(no_op), [])
    assert not result.passed
    assert any(assertion.message == "no completion evidence" for assertion in result.assertions)
