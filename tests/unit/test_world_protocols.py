"""Unit tests for world lifecycle and snapshot contracts."""

import inspect

from agentgym.world.base import World


def test_world_protocol_exposes_async_lifecycle_methods() -> None:
    for method_name in ("start", "restore", "snapshot", "capabilities", "stop"):
        assert inspect.iscoroutinefunction(getattr(World, method_name))
