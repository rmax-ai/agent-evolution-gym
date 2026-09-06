"""Package mutation contracts."""

from enum import StrEnum

from pydantic import BaseModel


class ToolMutationType(StrEnum):
    """Tool mutation operations defined by SPEC section 20."""

    CREATE_TOOL = "create_tool"
    EDIT_TOOL = "edit_tool"
    DELETE_TOOL = "delete_tool"


class Mutation(BaseModel):
    """An explicit diff to apply to an agent package, as defined by SPEC section 35."""

    id: str
    package_id: str
    layer: str
    operation: str
    target: str | None
    rationale: str
    evidence_refs: list[str]
    patch: str


class MutationBudget(BaseModel):
    """Limits on package changes defined by SPEC section 36."""

    max_files_changed: int = 3
    max_added_lines: int = 200
    max_deleted_lines: int = 200
    allow_tool_creation: bool = True
    max_new_tools: int = 1
    max_new_skills: int = 1
