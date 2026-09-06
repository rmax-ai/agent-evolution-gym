"""Reusable deterministic verification predicates."""

from __future__ import annotations

from collections.abc import Collection, Mapping

from agentgym.core.verification import AssertionResult
from agentgym.verifier.base import build_result
from agentgym.verifier.state_diff import ResourceInput, compare, unchanged

REQUIRED = "required"
FORBIDDEN = "forbidden"
INVARIANT = "invariant"


def _result(
    assertion_id: str,
    passed: bool,
    category: str,
    expected: object | None,
    actual: object | None,
    message: str,
) -> AssertionResult:
    return AssertionResult(
        id=assertion_id,
        passed=passed,
        category=category,
        expected=expected,
        actual=actual,
        message=message,
    )


def assert_equal(
    assertion_id: str,
    expected: object,
    actual: object,
    *,
    category: str = REQUIRED,
    message: str | None = None,
) -> AssertionResult:
    """Assert that an observed value equals its expected value."""

    passed = actual == expected
    default_message = (
        f"{assertion_id}: matched expected value"
        if passed
        else f"{assertion_id}: expected {expected!r}, got {actual!r}"
    )
    return _result(assertion_id, passed, category, expected, actual, message or default_message)


def _resource_field(
    resources: ResourceInput,
    resource_id: str,
    field: str,
    kind: str,
) -> tuple[bool, object | None]:
    resource_mapping = getattr(resources, "resources", resources)
    if not isinstance(resource_mapping, Mapping):
        return False, None
    collection = resource_mapping.get(kind, {})
    if not isinstance(collection, Mapping) or resource_id not in collection:
        return False, None
    resource = collection[resource_id]
    if not isinstance(resource, Mapping) or field not in resource:
        return False, None
    return True, resource[field]


def assert_unchanged(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
    resource_id: str,
    kind: str = "pages",
    *,
    category: str = INVARIANT,
    assertion_id: str | None = None,
) -> AssertionResult:
    """Assert that one resource was neither changed nor removed."""

    initial_mapping = getattr(initial_resources, "resources", initial_resources)
    final_mapping = getattr(final_resources, "resources", final_resources)
    initial_collection = (
        initial_mapping.get(kind, {}) if isinstance(initial_mapping, Mapping) else {}
    )
    final_collection = final_mapping.get(kind, {}) if isinstance(final_mapping, Mapping) else {}
    initial_exists = isinstance(initial_collection, Mapping) and resource_id in initial_collection
    final_exists = isinstance(final_collection, Mapping) and resource_id in final_collection
    expected = initial_collection[resource_id] if initial_exists else None
    actual = final_collection[resource_id] if final_exists else None
    passed = unchanged(initial_resources, final_resources, resource_id, kind)
    result_id = assertion_id or f"unchanged:{kind}:{resource_id}"
    message = (
        f"{result_id}: {kind} resource {resource_id!r} is unchanged"
        if passed
        else f"{result_id}: {kind} resource {resource_id!r} changed or is missing"
    )
    return _result(result_id, passed, category, expected, actual, message)


def assert_version_bumped_by(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
    page_id: str,
    delta: int | float = 1,
    *,
    category: str = REQUIRED,
    assertion_id: str | None = None,
) -> AssertionResult:
    """Assert that a page's version increased by exactly ``delta``."""

    initial_exists, initial_version = _resource_field(
        initial_resources, page_id, "version", "pages"
    )
    final_exists, final_version = _resource_field(final_resources, page_id, "version", "pages")
    expected: object | None = None
    if (
        initial_exists
        and isinstance(initial_version, (int, float))
        and not isinstance(initial_version, bool)
    ):
        expected = initial_version + delta
    passed = (
        expected is not None
        and final_exists
        and isinstance(final_version, (int, float))
        and not isinstance(final_version, bool)
        and final_version == expected
    )
    result_id = assertion_id or f"version-bumped-by:pages:{page_id}"
    message = (
        f"{result_id}: page {page_id!r} version increased by {delta}"
        if passed
        else f"{result_id}: page {page_id!r} did not increase by {delta}"
    )
    return _result(result_id, passed, category, expected, final_version, message)


def assert_field_contains(
    final_resources: ResourceInput,
    page_id: str,
    field_or_fragment: str,
    fragment: str | None = None,
    *,
    kind: str = "pages",
    category: str = REQUIRED,
    assertion_id: str | None = None,
) -> AssertionResult:
    """Assert that a final resource field contains a text fragment.

    ``field_or_fragment`` is the field name when ``fragment`` is supplied;
    when it is omitted, the page ``body`` field is used.
    """

    if fragment is None:
        field = "body"
        expected_fragment = field_or_fragment
    else:
        field = field_or_fragment
        expected_fragment = fragment
    field_exists, actual = _resource_field(final_resources, page_id, field, kind)
    passed = field_exists and isinstance(actual, str) and expected_fragment in actual
    result_id = assertion_id or f"field-contains:{kind}:{page_id}:{field}"
    message = (
        f"{result_id}: {kind} resource {page_id!r} field {field!r} contains the fragment"
        if passed
        else f"{result_id}: {kind} resource {page_id!r} field {field!r} is missing the fragment"
    )
    return _result(result_id, passed, category, expected_fragment, actual, message)


def assert_no_other_pages_changed(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
    allowed_ids: Collection[str],
    *,
    category: str = FORBIDDEN,
    assertion_id: str = "no-other-pages-changed",
) -> AssertionResult:
    """Assert that only explicitly allowed page IDs changed."""

    page_diff = compare(initial_resources, final_resources).get(
        "pages", {"created": [], "deleted": [], "updated": []}
    )
    changed_ids = set(page_diff.get("created", []))
    changed_ids.update(page_diff.get("deleted", []))
    changed_ids.update(page_diff.get("updated", []))
    outside_allowed = sorted(changed_ids - set(allowed_ids), key=str)
    passed = not outside_allowed
    message = (
        f"{assertion_id}: no pages outside the allowed set changed"
        if passed
        else f"{assertion_id}: unexpected changed pages: {outside_allowed!r}"
    )
    return _result(assertion_id, passed, category, [], outside_allowed, message)


def assert_field_unchanged(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
    resource_id: str,
    field: str,
    kind: str = "pages",
    *,
    category: str = INVARIANT,
    assertion_id: str | None = None,
) -> AssertionResult:
    """Assert that one field survives unchanged on an existing resource."""

    initial_exists, expected = _resource_field(initial_resources, resource_id, field, kind)
    final_exists, actual = _resource_field(final_resources, resource_id, field, kind)
    passed = initial_exists and final_exists and expected == actual
    result_id = assertion_id or f"field-unchanged:{kind}:{resource_id}:{field}"
    message = (
        f"{result_id}: {kind} resource {resource_id!r} field {field!r} is unchanged"
        if passed
        else f"{result_id}: {kind} resource {resource_id!r} field {field!r} changed or is missing"
    )
    return _result(result_id, passed, category, expected, actual, message)


__all__ = [
    "FORBIDDEN",
    "INVARIANT",
    "REQUIRED",
    "assert_equal",
    "assert_field_contains",
    "assert_field_unchanged",
    "assert_no_other_pages_changed",
    "assert_unchanged",
    "assert_version_bumped_by",
    "build_result",
]
