"""Validation helpers for values persisted as JSON.

Persisted JSON values deliberately use a reject-with-error policy. Values such as
dates, decimals, tuples, and arbitrary objects are not implicitly stringified or
otherwise normalized, because a lossy conversion would make a persisted contract
fail to round-trip to the value that was verified.
"""

import math


def ensure_json_safe(value: object | None, *, path: str = "$") -> object | None:
    """Return ``value`` after rejecting anything outside the JSON value domain.

    Accepted values are ``None``, booleans, finite numbers, strings, lists, and
    dictionaries with string keys whose values satisfy the same rule. Recursive
    containers are tracked while traversing so cyclic values receive a useful
    ``ValueError`` instead of recursing indefinitely.
    """

    _validate_json_value(value, path=path, active_containers=set())
    return value


def _validate_json_value(
    value: object | None,
    *,
    path: str,
    active_containers: set[int],
) -> None:
    """Validate one JSON value recursively."""

    if value is None or isinstance(value, (bool, int, str)):
        return

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite float, which is not JSON-safe")
        return

    if isinstance(value, dict):
        _enter_container(value, path=path, active_containers=active_containers)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError(f"{path} contains a non-string dictionary key: {key!r}")
                _validate_json_value(
                    item,
                    path=f"{path}.{key}",
                    active_containers=active_containers,
                )
        finally:
            active_containers.remove(id(value))
        return

    if isinstance(value, list):
        _enter_container(value, path=path, active_containers=active_containers)
        try:
            for index, item in enumerate(value):
                _validate_json_value(
                    item,
                    path=f"{path}[{index}]",
                    active_containers=active_containers,
                )
        finally:
            active_containers.remove(id(value))
        return

    raise ValueError(
        f"{path} contains a non-JSON-safe value of type {type(value).__name__}; "
        "persisted values must be JSON values"
    )


def _enter_container(
    value: dict[object, object] | list[object],
    *,
    path: str,
    active_containers: set[int],
) -> None:
    """Record a container and reject a cycle in the current traversal."""

    value_id = id(value)
    if value_id in active_containers:
        raise ValueError(f"{path} contains a cyclic container, which is not JSON-safe")
    active_containers.add(value_id)
