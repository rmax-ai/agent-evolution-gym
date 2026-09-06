"""Solver diagnosis contracts."""

from enum import StrEnum

from pydantic import BaseModel


class DiagnosisLayer(StrEnum):
    """Package layers a diagnosis may identify as the source of a failure."""

    KNOWLEDGE = "knowledge"
    SKILL = "skill"
    TOOL = "tool"
    UNKNOWN = "unknown"


class Diagnosis(BaseModel):
    """A first-class failure diagnosis defined by SPEC section 33."""

    id: str
    task_ids: list[str]
    summary: str
    suspected_layer: DiagnosisLayer
    confidence: float
    evidence: list[str]
    suggested_mutation_type: str
