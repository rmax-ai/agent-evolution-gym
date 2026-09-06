"""Lifecycle helper re-exports for process-based Confluence worlds."""

from .app import start_world, stop_world

__all__ = ["start_world", "stop_world"]
