"""Verification result contracts."""

from typing import Any

from pydantic import BaseModel, field_validator

from agentgym.core.json_safe import ensure_json_safe


class AssertionResult(BaseModel):
    """The deterministic result of one verifier assertion."""

    id: str
    passed: bool
    category: str
    expected: object | None
    actual: object | None
    message: str

    @field_validator("expected", "actual", mode="before")
    @classmethod
    def validate_observed_value(cls, value: object | None) -> object | None:
        """Reject observed values that cannot round-trip through JSON."""

        return ensure_json_safe(value)


class VerificationResult(BaseModel):
    """The complete deterministic verification result for a rollout."""

    passed: bool
    score: float
    assertions: list[AssertionResult]
    required_changes_passed: bool
    forbidden_changes_passed: bool
    invariants_passed: bool
    metadata: dict[str, Any]

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, value: object) -> object:
        """Reject verification metadata that cannot be persisted as JSON."""

        return ensure_json_safe(value)
