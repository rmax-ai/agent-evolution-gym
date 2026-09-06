"""Scaffold smoke test: package imports and version present."""

import agentgym


def test_package_importable() -> None:
    assert agentgym.__version__ == "0.1.0"
