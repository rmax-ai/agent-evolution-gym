"""Accepted package generation contracts."""

from typing import Any, Never

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agentgym.core.json_safe import ensure_json_safe


class _FrozenList(list[Any]):
    """A JSON-serializable list that rejects all normal mutations."""

    def _raise_immutable(self, *args: object, **kwargs: object) -> Never:
        """Raise for a mutation attempt."""

        del args, kwargs
        raise TypeError("Generation containers are immutable")

    __setitem__ = _raise_immutable
    __delitem__ = _raise_immutable
    __iadd__ = _raise_immutable
    __imul__ = _raise_immutable
    append = _raise_immutable
    clear = _raise_immutable
    extend = _raise_immutable
    insert = _raise_immutable
    pop = _raise_immutable
    remove = _raise_immutable
    reverse = _raise_immutable
    sort = _raise_immutable


class _FrozenDict(dict[str, Any]):
    """A JSON-serializable dictionary that rejects all normal mutations."""

    def _raise_immutable(self, *args: object, **kwargs: object) -> Never:
        """Raise for a mutation attempt."""

        del args, kwargs
        raise TypeError("Generation containers are immutable")

    __setitem__ = _raise_immutable
    __delitem__ = _raise_immutable
    clear = _raise_immutable
    pop = _raise_immutable
    popitem = _raise_immutable
    setdefault = _raise_immutable
    update = _raise_immutable
    __ior__ = _raise_immutable


def _deep_freeze(value: object) -> object:
    """Copy JSON containers into immutable, Pydantic-serializable containers."""

    if isinstance(value, dict):
        return _FrozenDict({key: _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return _FrozenList(_deep_freeze(item) for item in value)
    return value


class Generation(BaseModel):
    """An immutable accepted agent-package state defined by SPEC section 45."""

    model_config = ConfigDict(frozen=True)

    number: int
    package_id: str
    parent_package_id: str | None
    mutation_ids: list[str]
    train_metrics: dict[str, Any]
    validation_metrics: dict[str, Any]
    created_at: str

    @field_validator("train_metrics", "validation_metrics", mode="before")
    @classmethod
    def validate_metrics(cls, value: object) -> object:
        """Reject metric values that cannot be persisted as JSON."""

        return ensure_json_safe(value)

    @model_validator(mode="after")
    def freeze_nested_containers(self) -> "Generation":
        """Deep-freeze nested JSON containers while preserving JSON dumping.

        The frozen dict/list subclasses retain Pydantic's normal JSON
        serialization behavior, unlike ``MappingProxyType``, while preventing
        mutation of accepted lineage and metric state through nested references.
        """

        object.__setattr__(self, "mutation_ids", _deep_freeze(self.mutation_ids))
        object.__setattr__(self, "train_metrics", _deep_freeze(self.train_metrics))
        object.__setattr__(self, "validation_metrics", _deep_freeze(self.validation_metrics))
        return self
