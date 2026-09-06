"""World snapshot contracts."""

from typing import Any

from pydantic import BaseModel


class WorldSnapshot(BaseModel):
    """A reproducible serialized state of a domain world."""

    id: str
    domain_id: str
    schema_version: str
    timestamp: str
    resources: dict[str, Any]
