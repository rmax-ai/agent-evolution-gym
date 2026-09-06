"""Runner-owned world lifecycle helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from agentgym.world.base import World
from agentgym.world.snapshot import WorldSnapshot


@asynccontextmanager
async def world_session(world: World, initial_snapshot: WorldSnapshot) -> AsyncIterator[World]:
    """Start, restore, yield, and always stop one fresh world execution."""

    started = False
    try:
        await world.start()
        started = True
        await world.restore(initial_snapshot)
        yield world
    finally:
        if started:
            await world.stop()


async def start_world(world: World, initial_snapshot: WorldSnapshot) -> None:
    """Start and seed a world for callers that manage cleanup themselves."""

    await world.start()
    try:
        await world.restore(initial_snapshot)
    except Exception:
        await world.stop()
        raise


async def stop_world(world: World) -> None:
    """Stop a world through the shared lifecycle boundary."""

    await world.stop()


__all__ = ["start_world", "stop_world", "world_session"]
