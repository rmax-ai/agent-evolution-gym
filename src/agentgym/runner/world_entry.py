"""Subprocess entry point for a seeded Confluence process world."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from domains.confluence.world.api.app import create_app

from agentgym.core.scenario import read_snapshot
from agentgym.world.store import InMemoryConfluenceStore


def main() -> None:
    """Load the execution snapshot and serve its private loopback app."""

    snapshot_value = os.environ.get("AGENTGYM_SNAPSHOT_PATH")
    control_key = os.environ.get("AGENTGYM_CONTROL_KEY")
    port_value = os.environ.get("AGENTGYM_PORT")
    if not snapshot_value or not control_key or not port_value:
        raise RuntimeError(
            "AGENTGYM_SNAPSHOT_PATH, AGENTGYM_CONTROL_KEY, and AGENTGYM_PORT are required"
        )

    snapshot_path = Path(snapshot_value)
    snapshot = read_snapshot(snapshot_path)
    store = InMemoryConfluenceStore(resources=snapshot.resources)
    application = create_app(store, control_key=control_key)
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=int(port_value),
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()


__all__ = ["main"]
