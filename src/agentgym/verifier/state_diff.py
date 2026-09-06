"""Generic, deterministic diffs over world snapshot resource mappings."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

type Resources = Mapping[str, Any]
type ResourceInput = Resources | object

_MISSING = object()


def _as_resources(value: ResourceInput) -> Resources:
    """Return a resource mapping, accepting a snapshot as a convenience."""

    resources = getattr(value, "resources", value)
    if not isinstance(resources, Mapping):
        raise TypeError("expected a resource mapping or an object with a resource mapping")
    return resources


def _collection(resources: Resources, kind: str) -> Mapping[Any, Any]:
    value = resources.get(kind, {})
    if not isinstance(value, Mapping):
        return {}
    return value


def _lookup(resources: ResourceInput, kind: str, resource_id: str) -> tuple[bool, object | None]:
    collection = _collection(_as_resources(resources), kind)
    if resource_id not in collection:
        return False, None
    return True, collection[resource_id]


def _field_changes(initial: object, final: object) -> dict[str, dict[str, object | None]]:
    if not isinstance(initial, Mapping) or not isinstance(final, Mapping):
        return {
            "value": {
                "old": deepcopy(initial),
                "new": deepcopy(final),
            }
        }

    fields: dict[str, dict[str, object | None]] = {}
    for field in sorted(set(initial) | set(final), key=str):
        old = initial.get(field, _MISSING)
        new = final.get(field, _MISSING)
        if old == new:
            continue
        fields[str(field)] = {
            "old": None if old is _MISSING else deepcopy(old),
            "new": None if new is _MISSING else deepcopy(new),
        }
    return fields


def _version_delta(initial: object, final: object) -> int | float | None:
    if not isinstance(initial, Mapping) or not isinstance(final, Mapping):
        return None
    old_version = initial.get("version")
    new_version = final.get("version")
    if isinstance(old_version, bool) or isinstance(new_version, bool):
        return None
    if not isinstance(old_version, (int, float)) or not isinstance(new_version, (int, float)):
        return None
    return new_version - old_version


def compare(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
) -> dict[str, dict[str, Any]]:
    """Compare resources and return created, deleted, and updated entries.

    Each resource kind is represented by a mapping with ``created``,
    ``deleted``, and ``updated`` ID lists.  Details for each updated resource
    live under ``changes[resource_id]`` and contain ``changed_fields`` whose
    values have ``old`` and ``new`` entries, together with ``version_delta``
    when both resources expose numeric ``version`` fields.
    """

    initial = _as_resources(initial_resources)
    final = _as_resources(final_resources)
    diff: dict[str, dict[str, Any]] = {}

    for kind in sorted(set(initial) | set(final), key=str):
        initial_collection = _collection(initial, kind)
        final_collection = _collection(final, kind)
        initial_ids = set(initial_collection)
        final_ids = set(final_collection)
        created = sorted(final_ids - initial_ids, key=str)
        deleted = sorted(initial_ids - final_ids, key=str)
        common_ids = initial_ids & final_ids

        changes: dict[Any, dict[str, Any]] = {}
        updated: list[Any] = []
        for resource_id in sorted(common_ids, key=str):
            old = initial_collection[resource_id]
            new = final_collection[resource_id]
            changed_fields = _field_changes(old, new)
            if not changed_fields:
                continue
            updated.append(resource_id)
            changes[resource_id] = {
                "changed_fields": changed_fields,
                "version_delta": _version_delta(old, new),
            }

        diff[str(kind)] = {
            "created": created,
            "deleted": deleted,
            "updated": updated,
            "changes": changes,
        }

    return diff


def unchanged(
    initial_resources: ResourceInput,
    final_resources: ResourceInput,
    resource_id: str,
    kind: str = "pages",
) -> bool:
    """Return whether a resource exists and is identical in both snapshots."""

    initial_exists, initial = _lookup(initial_resources, kind, resource_id)
    final_exists, final = _lookup(final_resources, kind, resource_id)
    return initial_exists and final_exists and initial == final


def _preserves(expected: object, actual: object) -> bool:
    """Check that expected values survive in an observed resource."""

    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        return all(
            key in actual and _preserves(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, str) and isinstance(actual, str):
        return expected in actual
    return expected == actual


def preserved(
    expected: object,
    actual: object,
    resource_id: str | None = None,
    kind: str = "pages",
) -> bool:
    """Return whether an expected value or resource fragment is preserved.

    The two-argument form compares an expected fragment with an observed
    resource.  For symmetry with :func:`unchanged`, the optional
    ``resource_id`` form looks up the resource in two resource mappings before
    applying the same fragment check.
    """

    if resource_id is not None:
        expected_exists, expected_resource = _lookup(expected, kind, resource_id)
        actual_exists, actual_resource = _lookup(actual, kind, resource_id)
        if not expected_exists or not actual_exists:
            return False
        return _preserves(expected_resource, actual_resource)
    return _preserves(expected, actual)


__all__ = ["ResourceInput", "Resources", "compare", "preserved", "unchanged"]
