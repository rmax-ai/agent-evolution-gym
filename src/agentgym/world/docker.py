"""Thin Docker-backed world provider declaration.

Docker is an optional execution boundary for the simulator.  The provider keeps
the shared :mod:`agentgym.world.base` lifecycle shape without importing a Docker
SDK or making unit tests depend on a local daemon.  Container orchestration and
the capability proxy remain deployment concerns; the compose artifact points at
the Confluence ASGI application for environments that provide Docker.
"""

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Final, NoReturn

from agentgym.world.capabilities import Capability
from agentgym.world.snapshot import WorldSnapshot

_DEFAULT_COMPOSE_FILE: Final[Path] = (
    Path(__file__).resolve().parents[3] / "domains" / "confluence" / "world" / "docker-compose.yaml"
)


class DockerProviderUnavailable(RuntimeError):
    """Raised when the Docker world provider cannot reach a Docker executable."""


class DockerWorldProvider:
    """Declare the async world contract for containerized execution.

    The lifecycle is deliberately deferred until the Docker runner and capability
    proxy land.  On a host without Docker, lifecycle calls fail with a clear
    ``DockerProviderUnavailable`` error; with Docker installed they fail with
    ``NotImplementedError`` rather than silently running an unisolated fallback.
    """

    def __init__(
        self,
        compose_file: str | Path | None = None,
        *,
        docker_command: str = "docker",
        capabilities: Iterable[Capability] | None = None,
    ) -> None:
        self.compose_file = (
            Path(compose_file) if compose_file is not None else _DEFAULT_COMPOSE_FILE
        )
        self.docker_command = docker_command
        self._declared_capabilities = [
            capability.model_copy(deep=True)
            for capability in (
                capabilities if capabilities is not None else _default_capabilities()
            )
        ]

    async def start(self) -> None:
        """Start the containerized world once Docker orchestration is available."""

        self._raise_unavailable("start")

    async def restore(self, snapshot: WorldSnapshot) -> None:
        """Restore a snapshot through the future container API boundary."""

        del snapshot
        self._raise_unavailable("restore")

    async def snapshot(self) -> WorldSnapshot:
        """Capture state from the future containerized world."""

        self._raise_unavailable("snapshot")

    async def capabilities(self) -> list[Capability]:
        """Return the capabilities declared for the Confluence world."""

        return [capability.model_copy(deep=True) for capability in self._declared_capabilities]

    async def stop(self) -> None:
        """Stop the containerized world once Docker orchestration is available."""

        self._raise_unavailable("stop")

    def _raise_unavailable(self, operation: str) -> NoReturn:
        if shutil.which(self.docker_command) is None:
            raise DockerProviderUnavailable(
                "DockerWorldProvider requires Docker; "
                f"cannot {operation} the Confluence world without '{self.docker_command}'."
            )
        raise NotImplementedError(
            "DockerWorldProvider orchestration is not implemented yet; "
            f"cannot {operation} using {self.compose_file}."
        )


def _default_capabilities() -> list[Capability]:
    return [
        Capability(
            id="confluence.pages.read",
            system="confluence",
            operation="pages.read",
        ),
        Capability(
            id="confluence.pages.write",
            system="confluence",
            operation="pages.write",
        ),
        Capability(
            id="confluence.search",
            system="confluence",
            operation="search",
        ),
    ]


__all__ = ["DockerProviderUnavailable", "DockerWorldProvider"]
