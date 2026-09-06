"""Oracle and adversarial tests for the Confluence page-edit verifier."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest
from domains.confluence.scenarios.concurrency import ConcurrentEditScenario
from domains.confluence.scenarios.edit_page import EditPageScenario
from domains.confluence.scenarios.permissions import PermissionsScenario
from domains.confluence.scenarios.preservation import PreservationScenario
from domains.confluence.scenarios.retrieval import RetrievalScenario
from domains.confluence.verifiers.page_edit import VERIFIER, get_verifier, verify

from agentgym.core.scenario import read_snapshot
from agentgym.core.task import Task
from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType
from agentgym.core.verification import VerificationResult
from agentgym.world.snapshot import WorldSnapshot
from agentgym.world.store import InMemoryConfluenceStore


def _generate(
    scenario_type: type,
    seed: int,
    snapshot_dir: Path,
) -> tuple[Task, WorldSnapshot]:
    task = scenario_type(snapshot_dir=snapshot_dir).generate(seed)
    snapshot = read_snapshot(snapshot_dir / task.initial_snapshot_ref)
    return task, snapshot


def _restored_store(snapshot: WorldSnapshot) -> InMemoryConfluenceStore:
    return InMemoryConfluenceStore(resources=snapshot.resources)


def _target_and_fragment(task: Task) -> tuple[str, str]:
    config = task.metadata["verifier_config"]
    target_id = config["expected_page_ids"][0]
    fragment = config["expected_content_fragments"][target_id]
    assert isinstance(target_id, str)
    assert isinstance(fragment, str)
    return target_id, fragment


def _append_fragment(store: InMemoryConfluenceStore, page_id: str, fragment: str) -> None:
    page = store.pages[page_id]
    store.update_page(
        page_id,
        body=f"{page['body']}\n\n{fragment}",
        expected_version=page["version"],
    )


def _apply_expected_edit(task: Task, store: InMemoryConfluenceStore) -> None:
    target_id, fragment = _target_and_fragment(task)
    config = task.metadata["verifier_config"]
    expected_body = config.get("expected_final_body")
    if not isinstance(expected_body, str):
        _append_fragment(store, target_id, fragment)
        return
    store.update_page(
        target_id,
        body=expected_body,
        expected_version=store.pages[target_id]["version"],
    )


def _completion_event(task: Task) -> TrajectoryEvent:
    expected_response = task.metadata["verifier_config"]["expected_response"]
    return TrajectoryEvent(
        sequence=1,
        timestamp="2026-09-06T00:00:00+00:00",
        type=TrajectoryEventType.AGENT_COMPLETED,
        actor="agent",
        payload={"final_answer": f"Reported guidance: {expected_response}"},
    )


def _snapshot(store: InMemoryConfluenceStore) -> WorldSnapshot:
    return store.snapshot(
        snapshot_id="final",
        timestamp="2026-09-06T00:00:01+00:00",
    )


async def _verify_task(
    task: Task,
    initial: WorldSnapshot,
    final: WorldSnapshot,
) -> VerificationResult:
    return await verify(task, initial, final, {"final_answer": "incorrect self-report"})


async def test_known_good_retrieval_oracle_passes(tmp_path: Path) -> None:
    task, initial = _generate(RetrievalScenario, 1000, tmp_path)
    final = _snapshot(_restored_store(initial))

    result = await verify(task, initial, final, [_completion_event(task)])

    assert result.passed


@pytest.mark.parametrize(
    ("scenario_type", "seed"),
    ((EditPageScenario, 1100), (PreservationScenario, 1200)),
)
async def test_known_good_single_page_edit_oracle_passes(
    scenario_type: type,
    seed: int,
    tmp_path: Path,
) -> None:
    task, initial = _generate(scenario_type, seed, tmp_path)
    store = _restored_store(initial)
    _apply_expected_edit(task, store)

    result = await _verify_task(task, initial, _snapshot(store))

    assert result.passed


async def test_known_good_preservation_oracle_passes_with_explicit_forbidden_pages(
    tmp_path: Path,
) -> None:
    task, initial = _generate(PreservationScenario, 1201, tmp_path)
    store = _restored_store(initial)
    _apply_expected_edit(task, store)

    result = await _verify_task(task, initial, _snapshot(store))

    assert result.passed
    assert all(
        assertion.passed
        for assertion in result.assertions
        if assertion.id.startswith("forbidden-page-unchanged:")
    )


async def test_known_good_concurrent_edit_oracle_preserves_human_change(
    tmp_path: Path,
) -> None:
    task, initial = _generate(ConcurrentEditScenario, 1300, tmp_path)
    target_id, _requested_fragment = _target_and_fragment(task)
    concurrency = task.metadata["concurrency"]
    human_edit = concurrency["human_edit"]
    store = _restored_store(initial)
    if isinstance(human_edit, Mapping):
        human_body = human_edit["body"]
    else:
        human_body = f"{store.pages[target_id]['body']}\n\n{human_edit}"
    store.update_page(target_id, body=human_body, expected_version=1)
    store.update_page(
        target_id,
        body=task.metadata["verifier_config"]["expected_final_body"],
        expected_version=2,
    )

    result = await _verify_task(task, initial, _snapshot(store))

    assert result.passed
    assert any(
        assertion.id == "concurrent-human-edit-preserved" and assertion.passed
        for assertion in result.assertions
    )


@pytest.mark.parametrize("mode", ("denied_read", "denied_write", "allowed"))
async def test_known_good_permission_oracles_pass_for_all_modes(
    mode: str,
    tmp_path: Path,
) -> None:
    generator = PermissionsScenario(snapshot_dir=tmp_path)
    task = None
    for seed in range(3000, 3003):
        candidate = generator.generate(seed)
        if candidate.metadata["mode"] == mode:
            task = candidate
            break
    assert task is not None
    initial = read_snapshot(tmp_path / task.initial_snapshot_ref)
    store = _restored_store(initial)

    if mode == "allowed":
        target_id, fragment = _target_and_fragment(task)
        _append_fragment(store, target_id, fragment)

    trajectory = (
        [_completion_event(task)]
        if mode == "denied_read"
        else {"final_answer": "incorrect self-report"}
    )
    result = await verify(task, initial, _snapshot(store), trajectory)

    assert result.passed


async def test_wrong_page_edit_fails_required_and_collateral_assertions(tmp_path: Path) -> None:
    task, initial = _generate(EditPageScenario, 1101, tmp_path)
    target_id, fragment = _target_and_fragment(task)
    store = _restored_store(initial)
    wrong_page_id = next(page_id for page_id in store.pages if page_id != target_id)
    _append_fragment(store, wrong_page_id, fragment)

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == f"page-body-contains:{target_id}"
    ).passed
    assert not next(
        assertion for assertion in result.assertions if assertion.id == "no-other-pages-changed"
    ).passed


async def test_unrelated_page_change_fails_forbidden_assertion(tmp_path: Path) -> None:
    task, initial = _generate(EditPageScenario, 1102, tmp_path)
    target_id, fragment = _target_and_fragment(task)
    store = _restored_store(initial)
    _append_fragment(store, target_id, fragment)
    unrelated_page_id = next(page_id for page_id in store.pages if page_id != target_id)
    _append_fragment(store, unrelated_page_id, "unrelated collateral change")

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion for assertion in result.assertions if assertion.id == "no-other-pages-changed"
    ).passed


async def test_overwriting_human_edit_fails_concurrent_preservation(tmp_path: Path) -> None:
    task, initial = _generate(ConcurrentEditScenario, 1301, tmp_path)
    target_id, requested_fragment = _target_and_fragment(task)
    human_body = task.metadata["concurrency"]["human_edit"]["body"]
    store = _restored_store(initial)
    store.update_page(target_id, body=human_body, expected_version=1)
    store.update_page(target_id, body=requested_fragment, expected_version=2)

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == "concurrent-human-edit-preserved"
    ).passed


async def test_denied_write_with_unauthorized_state_change_fails(tmp_path: Path) -> None:
    generator = PermissionsScenario(snapshot_dir=tmp_path)
    task = None
    for seed in range(3000, 3003):
        candidate = generator.generate(seed)
        if candidate.metadata["mode"] == "denied_write":
            task = candidate
            break
    assert task is not None
    initial = read_snapshot(tmp_path / task.initial_snapshot_ref)
    target_id = task.metadata["verifier_config"]["expected_page_ids"][0]
    store = _restored_store(initial)
    store.update_page(target_id, body="unauthorized persisted edit", expected_version=1)

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == "denied-write-target-unchanged"
    ).passed


async def test_version_skip_of_plus_three_fails_exact_version_assertion(tmp_path: Path) -> None:
    task, initial = _generate(EditPageScenario, 1103, tmp_path)
    target_id, fragment = _target_and_fragment(task)
    store = _restored_store(initial)
    _append_fragment(store, target_id, fragment)
    _append_fragment(store, target_id, "second persisted write")
    _append_fragment(store, target_id, "third persisted write")

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == f"page-version-bumped-by-one:{target_id}"
    ).passed


async def test_changed_page_history_must_preserve_prior_entries(tmp_path: Path) -> None:
    task, initial = _generate(EditPageScenario, 1100, tmp_path)
    target_id, _ = _target_and_fragment(task)
    store = _restored_store(initial)
    _apply_expected_edit(task, store)
    store.page_versions[target_id][0]["body"] = "forged prior history"

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == f"page-history-prior-entries:{target_id}"
    ).passed


async def test_untouched_page_history_must_remain_byte_identical(tmp_path: Path) -> None:
    task, initial = _generate(EditPageScenario, 1101, tmp_path)
    target_id, _ = _target_and_fragment(task)
    store = _restored_store(initial)
    _apply_expected_edit(task, store)
    untouched_id = next(page_id for page_id in store.pages if page_id != target_id)
    store.page_versions[untouched_id][0]["body"] = "forged untouched history"

    result = await _verify_task(task, initial, _snapshot(store))

    assert not result.passed
    assert not next(
        assertion
        for assertion in result.assertions
        if assertion.id == f"page-history-unchanged:{untouched_id}"
    ).passed


async def test_unknown_family_fails_loudly(tmp_path: Path) -> None:
    task, initial = _generate(RetrievalScenario, 1001, tmp_path)
    unknown = task.model_copy(update={"metadata": {**task.metadata, "family": "unknown"}})
    final = _snapshot(_restored_store(initial))

    result = await _verify_task(unknown, initial, final)

    assert not result.passed
    assert any(assertion.message == "unknown family" for assertion in result.assertions)


def test_verifier_registry_exports_are_stable() -> None:
    assert get_verifier() is VERIFIER
    assert get_verifier(VERIFIER.id) is VERIFIER
