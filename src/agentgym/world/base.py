"""Protocols for simulated enterprise worlds."""

from typing import Protocol

from agentgym.world.capabilities import Capability
from agentgym.world.snapshot import WorldSnapshot


class World(Protocol):
    """Async lifecycle and state contract for a simulated world."""

    async def start(self) -> None:
        """Start the world and make its raw APIs available."""

    async def restore(self, snapshot: WorldSnapshot) -> None:
        """Replace the world state with the supplied snapshot."""

    async def snapshot(self) -> WorldSnapshot:
        """Capture the complete current world state."""

    async def capabilities(self) -> list[Capability]:
        """Return the capabilities granted for the current execution."""

    async def stop(self) -> None:
        """Stop the world and release its resources."""
