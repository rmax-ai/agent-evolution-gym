"""Deterministic state-based verification for Confluence page tasks."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentgym.core.task import Task
from agentgym.core.verification import AssertionResult, VerificationResult
from agentgym.verifier.base import build_result
from agentgym.verifier.predicates import (
    FORBIDDEN,
    INVARIANT,
    REQUIRED,
    assert_equal,
    assert_field_contains,
    assert_no_other_pages_changed,
    assert_unchanged,
    assert_version_bumped_by,
)
from agentgym.world.snapshot import WorldSnapshot

VERIFIER_ID = "confluence-safe-page-edit-v1"

_SUPPORTED_FAMILIES = frozenset(
    {"retrieval", "edit_page", "preservation", "concurrent_edit", "permissions"}
)
_UNCHANGED_INVARIANT_KINDS = ("users", "spaces", "permissions")


class PageEditVerifier:
    """Verify Confluence task side effects from initial and final snapshots."""

    id = VERIFIER_ID

    async def verify(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        trajectory: object,
    ) -> VerificationResult:
        """Return deterministic assertions for a Confluence task."""

        family = task.metadata.get("family")
        if not isinstance(family, str) or family not in _SUPPORTED_FAMILIES:
            return _unknown_family_result(family)

        config_value = task.metadata.get("verifier_config")
        if not isinstance(config_value, Mapping):
            return _configuration_failure("invalid verifier_config")
        config = config_value

        result_metadata = {"verifier_id": VERIFIER_ID, "family": family}
        if family == "retrieval":
            return build_result(
                _verify_read_only(initial, final, trajectory, config),
                metadata=result_metadata,
            )

        if family == "permissions":
            mode = _permission_mode(task.metadata, config)
            if mode == "denied_read":
                return build_result(
                    _verify_read_only(initial, final, trajectory, config),
                    metadata={**result_metadata, "mode": mode},
                )
            if mode == "denied_write":
                return build_result(
                    _verify_denied_write(task, initial, final, config),
                    metadata={**result_metadata, "mode": mode},
                )
            if mode == "allowed":
                return build_result(
                    _verify_edit(initial, final, config, exact_body=False),
                    metadata={**result_metadata, "mode": mode},
                )
            return _configuration_failure("unknown permission mode")

        if family == "concurrent_edit":
            return build_result(
                _verify_concurrent(task, initial, final, config),
                metadata=result_metadata,
            )

        if family == "preservation":
            return build_result(
                _verify_preservation(initial, final, config),
                metadata=result_metadata,
            )

        return build_result(
            _verify_edit(initial, final, config, exact_body=True),
            metadata=result_metadata,
        )


VERIFIER = PageEditVerifier()
VERIFIERS = (VERIFIER,)


async def verify(
    task: Task,
    initial: WorldSnapshot,
    final: WorldSnapshot,
    trajectory: object,
) -> VerificationResult:
    """Module-level verifier entry point used by domain loading code."""

    return await VERIFIER.verify(task, initial, final, trajectory)


def get_verifier(verifier_id: str = VERIFIER_ID) -> PageEditVerifier:
    """Return the registered verifier for ``verifier_id``."""

    if verifier_id != VERIFIER_ID:
        raise KeyError(f"unknown verifier: {verifier_id}")
    return VERIFIER


def _verify_edit(
    initial: WorldSnapshot,
    final: WorldSnapshot,
    config: Mapping[str, Any],
    *,
    exact_body: bool,
) -> list[AssertionResult]:
    targets, target_error = _target_page_ids(config)
    if target_error is not None:
        return [_configuration_failure_assertion(target_error)]

    fragments = _content_fragments(config)
    assertions: list[AssertionResult] = []
    for page_id in targets:
        fragment = fragments.get(page_id)
        if not isinstance(fragment, str) and not exact_body:
            assertions.append(
                _configuration_failure_assertion(
                    f"missing expected content fragment for page {page_id!r}"
                )
            )
        elif isinstance(fragment, str):
            assertions.append(
                assert_field_contains(
                    final.resources,
                    page_id,
                    fragment,
                    assertion_id=f"page-body-contains:{page_id}",
                )
            )
        if exact_body:
            expected_body, body_error = _expected_final_body(config, page_id, len(targets))
            if body_error is not None:
                assertions.append(_configuration_failure_assertion(body_error))
            else:
                assertions.append(
                    assert_equal(
                        f"page-body-exact:{page_id}",
                        expected_body,
                        _page_body(final, page_id),
                    )
                )
        assertions.append(
            assert_version_bumped_by(
                initial.resources,
                final.resources,
                page_id,
                delta=1,
                assertion_id=f"page-version-bumped-by-one:{page_id}",
            )
        )

    assertions.append(
        assert_no_other_pages_changed(
            initial.resources,
            final.resources,
            set(targets),
            assertion_id="no-other-pages-changed",
        )
    )
    assertions.extend(_world_invariants(initial, final))
    return assertions


def _verify_read_only(
    initial: WorldSnapshot,
    final: WorldSnapshot,
    trajectory: object,
    config: Mapping[str, Any],
) -> list[AssertionResult]:
    """Verify both read-only state and an independently observed answer artifact."""

    assertions = [_world_unchanged(initial, final, category=FORBIDDEN)]
    expected_response = config.get("expected_response")
    if not isinstance(expected_response, str) or not expected_response:
        assertions.append(_configuration_failure_assertion("missing expected response"))
    else:
        assertions.append(_completion_evidence(trajectory, expected_response))
    return assertions


def _verify_preservation(
    initial: WorldSnapshot,
    final: WorldSnapshot,
    config: Mapping[str, Any],
) -> list[AssertionResult]:
    assertions = _verify_edit(initial, final, config, exact_body=True)
    if any(assertion.id.startswith("configuration:") for assertion in assertions):
        return assertions

    targets, target_error = _target_page_ids(config)
    if target_error is not None:
        return [_configuration_failure_assertion(target_error)]
    preserved_fragments, fragments_error = _preserved_body_fragments(config)
    if fragments_error is not None:
        assertions.append(_configuration_failure_assertion(fragments_error))
        return assertions
    assertions.extend(
        _body_fragment_preservation_assertions(
            initial,
            final,
            targets[0],
            preserved_fragments,
        )
    )

    forbidden_ids, forbidden_error = _page_id_collection(config, "forbidden_page_ids")
    if forbidden_error is not None:
        assertions.append(_configuration_failure_assertion(forbidden_error))
        return assertions
    for page_id in forbidden_ids:
        assertions.append(
            assert_unchanged(
                initial.resources,
                final.resources,
                page_id,
                category=FORBIDDEN,
                assertion_id=f"forbidden-page-unchanged:{page_id}",
            )
        )
    return assertions


def _verify_concurrent(
    task: Task,
    initial: WorldSnapshot,
    final: WorldSnapshot,
    config: Mapping[str, Any],
) -> list[AssertionResult]:
    assertions = _verify_edit(initial, final, config, exact_body=True)
    if any(assertion.id.startswith("configuration:") for assertion in assertions):
        return assertions

    targets, _ = _target_page_ids(config)
    concurrency = task.metadata.get("concurrency")
    if not isinstance(concurrency, Mapping):
        concurrency = config.get("concurrency")
    if not isinstance(concurrency, Mapping):
        assertions.append(_configuration_failure_assertion("missing concurrency metadata"))
        return assertions

    concurrent_page_id = concurrency.get("page_id")
    target_page_id = targets[0]
    if not isinstance(concurrent_page_id, str):
        assertions.append(_configuration_failure_assertion("missing concurrency page id"))
    elif concurrent_page_id != target_page_id:
        assertions.append(
            _configuration_failure_assertion(
                "concurrency page id does not match the expected target"
            )
        )

    human_fragment = _human_edit_fragment(
        task.metadata,
        config,
        initial,
        target_page_id,
    )
    if human_fragment is None:
        assertions.append(_configuration_failure_assertion("missing concurrent human edit"))
    else:
        assertions.append(
            assert_field_contains(
                final.resources,
                target_page_id,
                human_fragment,
                assertion_id="concurrent-human-edit-preserved",
            )
        )
    _replace_version_assertion(assertions, target_page_id, initial, final, delta=2)
    return assertions


def _verify_denied_write(
    task: Task,
    initial: WorldSnapshot,
    final: WorldSnapshot,
    config: Mapping[str, Any],
) -> list[AssertionResult]:
    del task
    targets, target_error = _target_page_ids(config)
    if target_error is not None:
        return [_configuration_failure_assertion(target_error)]
    target_page_id = targets[0]
    return [
        assert_unchanged(
            initial.resources,
            final.resources,
            target_page_id,
            category=FORBIDDEN,
            assertion_id="denied-write-target-unchanged",
        ),
        assert_no_other_pages_changed(
            initial.resources,
            final.resources,
            {target_page_id},
            assertion_id="no-other-pages-changed",
        ),
        _world_unchanged(initial, final, category=INVARIANT, assertion_id="no-attempt-persisted"),
    ]


def _world_invariants(
    initial: WorldSnapshot,
    final: WorldSnapshot,
) -> list[AssertionResult]:
    assertions = [
        assert_equal(
            f"unchanged:{kind}",
            initial.resources.get(kind, {}),
            final.resources.get(kind, {}),
            category=INVARIANT,
            message=f"unchanged:{kind}: resource collection is unchanged",
        )
        for kind in _UNCHANGED_INVARIANT_KINDS
    ]
    assertions.extend(_page_history_invariants(initial, final))
    return assertions


def _page_history_invariants(
    initial: WorldSnapshot,
    final: WorldSnapshot,
) -> list[AssertionResult]:
    """Check append-only page history for changed and untouched pages."""

    initial_pages = _resource_collection(initial, "pages")
    final_pages = _resource_collection(final, "pages")
    initial_histories = _resource_collection(initial, "page_versions")
    final_histories = _resource_collection(final, "page_versions")
    page_ids = set(initial_pages) | set(final_pages) | set(initial_histories) | set(final_histories)
    assertions: list[AssertionResult] = []

    for page_id in sorted(page_ids, key=str):
        initial_page = initial_pages.get(page_id)
        final_page = final_pages.get(page_id)
        initial_history = initial_histories.get(page_id)
        final_history = final_histories.get(page_id)
        page_changed = _canonical_bytes(initial_page) != _canonical_bytes(final_page)

        if not page_changed:
            assertions.append(
                _history_assertion(
                    f"page-history-unchanged:{page_id}",
                    _canonical_bytes(initial_history) == _canonical_bytes(final_history),
                    initial_history,
                    final_history,
                    "page history is unchanged for an untouched page"
                    if _canonical_bytes(initial_history) == _canonical_bytes(final_history)
                    else "page history changed for an untouched page",
                )
            )
            continue

        if not isinstance(final_page, Mapping):
            assertions.append(
                _history_assertion(
                    f"page-history-final-page:{page_id}",
                    False,
                    "final page resource",
                    final_page,
                    "changed page is missing from the final world",
                )
            )
            continue

        final_version = final_page.get("version")
        history_is_sequence = isinstance(final_history, Sequence) and not isinstance(
            final_history, (str, bytes, bytearray)
        )
        history_length_passed = (
            isinstance(final_version, int)
            and not isinstance(final_version, bool)
            and history_is_sequence
            and len(final_history) == final_version
        )
        assertions.append(
            _history_assertion(
                f"page-history-length:{page_id}",
                history_length_passed,
                final_version,
                len(final_history) if history_is_sequence else final_history,
                "page history length equals the final page version"
                if history_length_passed
                else "page history length does not equal the final page version",
            )
        )

        initial_entries = (
            list(initial_history)
            if isinstance(initial_history, Sequence)
            and not isinstance(initial_history, (str, bytes, bytearray))
            else []
        )
        final_entries = list(final_history) if history_is_sequence else []
        overlap = min(max(len(final_entries) - 1, 0), len(initial_entries))
        prior_passed = all(
            _canonical_bytes(final_entries[index]) == _canonical_bytes(initial_entries[index])
            for index in range(overlap)
        )
        assertions.append(
            _history_assertion(
                f"page-history-prior-entries:{page_id}",
                prior_passed,
                initial_entries[:overlap],
                final_entries[:overlap],
                "prior page history entries are preserved"
                if prior_passed
                else "a prior page history entry was changed",
            )
        )
        last_matches_page = bool(final_entries) and (
            _canonical_bytes(final_entries[-1]) == _canonical_bytes(final_page)
        )
        assertions.append(
            _history_assertion(
                f"page-history-final-entry:{page_id}",
                last_matches_page,
                final_page,
                final_entries[-1] if final_entries else None,
                "the last page history entry matches the final page"
                if last_matches_page
                else "the last page history entry does not match the final page",
            )
        )
    return assertions


def _resource_collection(snapshot: WorldSnapshot, kind: str) -> Mapping[Any, Any]:
    value = snapshot.resources.get(kind, {})
    return value if isinstance(value, Mapping) else {}


def _canonical_bytes(value: object) -> bytes:
    """Serialize JSON-safe state canonically for byte-wise comparisons."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _history_assertion(
    assertion_id: str,
    passed: bool,
    expected: object,
    actual: object,
    message: str,
) -> AssertionResult:
    return AssertionResult(
        id=assertion_id,
        passed=passed,
        category=INVARIANT,
        expected=expected,
        actual=actual,
        message=f"{assertion_id}: {message}",
    )


def _expected_final_body(
    config: Mapping[str, Any],
    page_id: str,
    target_count: int,
) -> tuple[str | None, str | None]:
    value = config.get("expected_final_body")
    if isinstance(value, str):
        return value, None
    if isinstance(value, Mapping):
        body = value.get(page_id)
        if isinstance(body, str):
            return body, None
    if value is None:
        return None, "missing expected final body"
    if target_count == 1:
        return None, "invalid expected final body"
    return None, f"missing expected final body for page {page_id!r}"


def _preserved_body_fragments(
    config: Mapping[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    value = config.get("preserved_body_fragments")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return (), "missing or invalid preserved_body_fragments"
    fragments = tuple(value)
    if any(not isinstance(fragment, str) for fragment in fragments):
        return (), "preserved_body_fragments must contain only strings"
    return fragments, None


def _body_fragment_preservation_assertions(
    initial: WorldSnapshot,
    final: WorldSnapshot,
    page_id: str,
    fragments: Sequence[str],
) -> list[AssertionResult]:
    initial_body = _page_body(initial, page_id)
    final_body = _page_body(final, page_id)
    assertions: list[AssertionResult] = []
    for index, fragment in enumerate(fragments):
        passed = (
            isinstance(initial_body, str)
            and isinstance(final_body, str)
            and fragment in initial_body
            and fragment in final_body
        )
        assertions.append(
            AssertionResult(
                id=f"preserved-body-fragment:{page_id}:{index}",
                passed=passed,
                category=FORBIDDEN,
                expected=fragment,
                actual=final_body,
                message=(
                    f"preserved-body-fragment:{page_id}:{index}: section text survived"
                    if passed
                    else (
                        f"preserved-body-fragment:{page_id}:{index}: section text was not preserved"
                    )
                ),
            )
        )
    return assertions


def _completion_evidence(trajectory: object, expected_response: str) -> AssertionResult:
    completion_seen = False
    answer_seen = False
    for event in _trajectory_events(trajectory):
        event_type = _event_value(event, "type")
        event_type = getattr(event_type, "value", event_type)
        if event_type != "agent.completed":
            continue
        completion_seen = True
        payload = _event_value(event, "payload")
        if not isinstance(payload, Mapping):
            continue
        final_answer = payload.get("final_answer")
        if not isinstance(final_answer, str):
            continue
        answer_seen = True
        if expected_response in final_answer:
            return AssertionResult(
                id="completion-evidence",
                passed=True,
                category=REQUIRED,
                expected=expected_response,
                actual=final_answer,
                message="completion-evidence: final answer contains expected response",
            )
    if not completion_seen or not answer_seen:
        message = "no completion evidence"
    else:
        message = "completion evidence does not contain expected response"
    return AssertionResult(
        id="completion-evidence",
        passed=False,
        category=REQUIRED,
        expected=expected_response,
        actual=None,
        message=message,
    )


def _trajectory_events(trajectory: object) -> tuple[object, ...]:
    if isinstance(trajectory, Mapping):
        events = trajectory.get("events")
        if isinstance(events, Sequence) and not isinstance(events, (str, bytes, bytearray)):
            return tuple(events)
        if "type" in trajectory and "payload" in trajectory:
            return (trajectory,)
        return ()
    if isinstance(trajectory, Sequence) and not isinstance(trajectory, (str, bytes, bytearray)):
        return tuple(trajectory)
    if (
        _event_value(trajectory, "type") is not None
        and _event_value(trajectory, "payload") is not None
    ):
        return (trajectory,)
    events = getattr(trajectory, "events", None)
    if isinstance(events, Sequence) and not isinstance(events, (str, bytes, bytearray)):
        return tuple(events)
    return ()


def _event_value(event: object, key: str) -> object:
    if isinstance(event, Mapping):
        return event.get(key)
    return getattr(event, key, None)


def _world_unchanged(
    initial: WorldSnapshot,
    final: WorldSnapshot,
    *,
    category: str,
    assertion_id: str = "world-unchanged",
) -> AssertionResult:
    return assert_equal(
        assertion_id,
        initial.resources,
        final.resources,
        category=category,
        message=(
            "world-unchanged: final world resources match the initial snapshot"
            if initial.resources == final.resources
            else "world-unchanged: final world resources differ from the initial snapshot"
        ),
    )


def _replace_version_assertion(
    assertions: list[AssertionResult],
    page_id: str,
    initial: WorldSnapshot,
    final: WorldSnapshot,
    *,
    delta: int,
) -> None:
    """Replace the ordinary edit version assertion with the concurrency delta."""

    for index, assertion in enumerate(assertions):
        if assertion.id == f"page-version-bumped-by-one:{page_id}":
            assertions[index] = assert_version_bumped_by(
                initial.resources,
                final.resources,
                page_id,
                delta=delta,
                assertion_id="page-version-bumped-by-two:concurrent-edit",
            )
            return
    assertions.append(
        assert_version_bumped_by(
            initial.resources,
            final.resources,
            page_id,
            delta=delta,
            assertion_id="page-version-bumped-by-two:concurrent-edit",
        )
    )


def _target_page_ids(config: Mapping[str, Any]) -> tuple[tuple[str, ...], str | None]:
    return _page_id_collection(config, "expected_page_ids")


def _page_id_collection(
    config: Mapping[str, Any],
    key: str,
) -> tuple[tuple[str, ...], str | None]:
    value = config.get(key)
    if isinstance(value, str):
        values: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = value
    else:
        return (), f"missing or invalid {key}"

    page_ids = tuple(page_id for page_id in values if isinstance(page_id, str) and page_id)
    if len(page_ids) != len(values) or not page_ids:
        return (), f"missing or invalid {key}"
    if len(set(page_ids)) != len(page_ids):
        return (), f"duplicate page ids in {key}"
    return page_ids, None


def _content_fragments(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get("expected_content_fragments", config.get("expected_fragments", {}))
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        page_ids, error = _target_page_ids(config)
        if error is None and len(page_ids) == 1:
            return {page_ids[0]: value}
    return {}


def _permission_mode(metadata: Mapping[str, Any], config: Mapping[str, Any]) -> object:
    mode = config.get("mode")
    if mode is None:
        mode = metadata.get("mode")
    return mode


def _human_edit_fragment(
    metadata: Mapping[str, Any],
    config: Mapping[str, Any],
    initial: WorldSnapshot,
    page_id: str,
) -> str | None:
    explicit_fragment = config.get("preserve_concurrent_fragment")
    if isinstance(explicit_fragment, str) and explicit_fragment:
        return explicit_fragment

    concurrency = metadata.get("concurrency")
    if not isinstance(concurrency, Mapping):
        concurrency = config.get("concurrency")
    if not isinstance(concurrency, Mapping):
        return None
    human_edit = concurrency.get("human_edit")
    if isinstance(human_edit, str) and human_edit:
        return human_edit
    if not isinstance(human_edit, Mapping):
        return None

    for key in ("fragment", "text", "content"):
        value = human_edit.get(key)
        if isinstance(value, str) and value:
            return value

    body = human_edit.get("body")
    if not isinstance(body, str) or not body:
        return None
    initial_body = _page_body(initial, page_id)
    if isinstance(initial_body, str) and body.startswith(initial_body):
        suffix = body[len(initial_body) :].strip()
        if suffix:
            return suffix
    return body


def _page_body(snapshot: WorldSnapshot, page_id: str) -> str | None:
    pages = snapshot.resources.get("pages", {})
    if not isinstance(pages, Mapping):
        return None
    page = pages.get(page_id)
    if not isinstance(page, Mapping):
        return None
    body = page.get("body")
    return body if isinstance(body, str) else None


def _unknown_family_result(family: object) -> VerificationResult:
    return build_result(
        [
            AssertionResult(
                id="unknown-family",
                passed=False,
                category=REQUIRED,
                expected=sorted(_SUPPORTED_FAMILIES),
                actual=family,
                message="unknown family",
            )
        ],
        metadata={"verifier_id": VERIFIER_ID, "family": family},
    )


def _configuration_failure(message: str) -> VerificationResult:
    return build_result(
        [_configuration_failure_assertion(message)],
        metadata={"verifier_id": VERIFIER_ID},
    )


def _configuration_failure_assertion(message: str) -> AssertionResult:
    return AssertionResult(
        id=f"configuration:{message}",
        passed=False,
        category=REQUIRED,
        expected="valid task verifier configuration",
        actual=None,
        message=message,
    )


__all__ = [
    "VERIFIER",
    "VERIFIERS",
    "VERIFIER_ID",
    "PageEditVerifier",
    "get_verifier",
    "verify",
]
