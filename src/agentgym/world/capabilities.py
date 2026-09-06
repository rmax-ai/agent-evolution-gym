"""World capability contracts."""

from pydantic import BaseModel


class Capability(BaseModel):
    """One explicit permission granted to a task execution."""

    id: str
    system: str
    operation: str
