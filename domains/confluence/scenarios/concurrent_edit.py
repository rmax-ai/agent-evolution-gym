"""Compatibility module for the domain manifest's concurrent-edit name."""

from .concurrency import (
    ConcurrencyGenerator,
    ConcurrencyScenario,
    ConcurrentEditScenario,
)

GENERATOR = ConcurrentEditScenario()

__all__ = [
    "GENERATOR",
    "ConcurrencyGenerator",
    "ConcurrencyScenario",
    "ConcurrentEditScenario",
]
