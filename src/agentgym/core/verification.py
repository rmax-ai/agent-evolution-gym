"""Verification result contracts."""

from typing import Any

from pydantic import BaseModel, field_serializer
from pydantic_core import to_jsonable_python


def _json_safe(value: object | None) -> object | None:
    """Convert an observed value into a value suitable for JSON persistence."""

    return to_jsonable_python(value, fallback=lambda unknown: str(unknown))


class AssertionResult(BaseModel):
    """The deterministic result of one verifier assertion."""

    id: str
    passed: bool
    category: str
    expected: object | None
    actual: object | None
    message: str

    @field_serializer("expected", "actual", when_used="json")
    def serialize_observed_value(self, value: object | None) -> object | None:
        """Normalize observed values when the assertion is persisted as JSON."""

        return _json_safe(value)


class VerificationResult(BaseModel):
    """The complete deterministic verification result for a rollout."""

    passed: bool
    score: float
    assertions: list[AssertionResult]
    required_changes_passed: bool
    forbidden_changes_passed: bool
    invariants_passed: bool
    metadata: dict[str, Any]
