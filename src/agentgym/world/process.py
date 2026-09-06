"""Process-backed world provider for local, Docker-free executions.

Each provider owns one uvicorn child process and one loopback port.  The child
starts from the snapshot file supplied to the provider and exposes trusted
state operations only behind a random control key.  The raw Confluence router
never receives that key and therefore remains the agent-visible API.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import socket
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import httpx

from agentgym.world.capabilities import Capability
from agentgym.world.snapshot import WorldSnapshot

_DEFAULT_READY_TIMEOUT: Final[float] = 15.0
_DEFAULT_REQUEST_TIMEOUT: Final[float] = 10.0


class ProcessWorldError(RuntimeError):
    """Raised when a process world cannot be started or contacted."""


class ProcessWorldProvider:
    """Run one Confluence simulator instance in a local uvicorn subprocess."""

    def __init__(
        self,
        snapshot_path: str | Path,
        *,
        capabilities: Iterable[Capability] | None = None,
        control_key: str | None = None,
        readiness_timeout: float = _DEFAULT_READY_TIMEOUT,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self.snapshot_path = Path(snapshot_path).expanduser().resolve()
        self.control_key = control_key or secrets.token_urlsafe(32)
        self.readiness_timeout = readiness_timeout
        self.request_timeout = request_timeout
        self._declared_capabilities = [
            capability.model_copy(deep=True)
            for capability in (
                capabilities if capabilities is not None else _default_capabilities()
            )
        ]
        self._process: asyncio.subprocess.Process | None = None
        self._port: int | None = None
        self._base_url: str | None = None

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        """Return the owned child process, if the provider is running."""

        return self._process

    @property
    def port(self) -> int:
        """Return the assigned loopback port or raise before startup."""

        if self._port is None:
            raise ProcessWorldError("process world has not been started")
        return self._port

    @property
    def base_url(self) -> str:
        """Return the loopback URL used by raw API clients."""

        if self._base_url is None:
            raise ProcessWorldError("process world has not been started")
        return self._base_url

    @property
    def url(self) -> str:
        """Alias for :attr:`base_url` used by runner integrations."""

        return self.base_url

    @property
    def world_url(self) -> str:
        """Explicit alias for callers handing the world gateway to tools."""

        return self.base_url

    async def start(self) -> None:
        """Spawn the world child and wait for its private control endpoint."""

        if self._process is not None and self._process.returncode is None:
            return
        if not self.snapshot_path.is_file():
            raise ProcessWorldError(f"world snapshot does not exist: {self.snapshot_path}")

        try:
            port = _reserve_loopback_port()
        except OSError as error:
            raise ProcessWorldError(f"failed to reserve a loopback port: {error}") from error
        environment = _child_environment(self.snapshot_path, self.control_key, port)
        command = [sys.executable, "-m", "agentgym.runner.world_entry"]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                env=environment,
                cwd=str(_repository_root()),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError) as error:
            raise ProcessWorldError(f"failed to spawn process world: {error}") from error

        self._process = process
        self._port = port
        self._base_url = f"http://127.0.0.1:{port}"
        try:
            await self._wait_until_ready()
        except Exception as error:
            await self.stop()
            if isinstance(error, ProcessWorldError):
                raise error
            raise ProcessWorldError("process world failed readiness probe") from error

    async def restore(self, snapshot: WorldSnapshot) -> None:
        """Restore state through the trusted control channel."""

        await self._control_request(
            "POST",
            "/api/control/restore",
            json=snapshot.model_dump(mode="json"),
        )

    async def snapshot(self) -> WorldSnapshot:
        """Capture complete current state through the trusted control channel."""

        payload = await self._control_request("POST", "/api/control/snapshot")
        try:
            return WorldSnapshot.model_validate(payload)
        except Exception as error:
            raise ProcessWorldError("world returned an invalid snapshot") from error

    async def human_edit(self, page_id: str, actor: str, body: str) -> dict[str, object]:
        """Apply one trusted post-read human edit for a concurrency scenario."""

        payload = await self._control_request(
            "POST",
            "/api/control/human-edit",
            json={"page_id": page_id, "actor": actor, "body": body},
        )
        if not isinstance(payload, dict):
            raise ProcessWorldError("world returned an invalid human-edit response")
        return payload

    async def capabilities(self) -> list[Capability]:
        """Return a detached copy of this execution's capability grants."""

        return [capability.model_copy(deep=True) for capability in self._declared_capabilities]

    async def stop(self) -> None:
        """Terminate the child and release the provider's process resources."""

        process = self._process
        self._process = None
        self._port = None
        self._base_url = None
        if process is None:
            return

        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _wait_until_ready(self) -> None:
        deadline = asyncio.get_running_loop().time() + self.readiness_timeout
        last_error: BaseException | None = None
        while asyncio.get_running_loop().time() < deadline:
            process = self._process
            if process is None:
                raise ProcessWorldError("process world exited before readiness")
            if process.returncode is not None:
                raise ProcessWorldError(
                    f"process world exited before readiness (code {process.returncode})"
                )
            try:
                await self._control_request(
                    "POST",
                    "/api/control/snapshot",
                    request_timeout=min(self.request_timeout, 1.0),
                )
                return
            except (httpx.HTTPError, ProcessWorldError) as error:
                last_error = error
                await asyncio.sleep(0.05)

        detail = f": {last_error}" if last_error is not None else ""
        raise ProcessWorldError(f"process world readiness timed out{detail}")

    async def _control_request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        request_timeout: float | None = None,
    ) -> object:
        if self._base_url is None:
            raise ProcessWorldError("process world has not been started")
        headers = {"X-Control-Key": self.control_key}
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=request_timeout or self.request_timeout,
                trust_env=False,
            ) as client:
                response = await client.request(method, path, headers=headers, json=json)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise ProcessWorldError(f"process world control request failed: {error}") from error


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _child_environment(snapshot_path: Path, control_key: str, port: int) -> dict[str, str]:
    repository_root = _repository_root()
    existing_pythonpath = os.environ.get("PYTHONPATH")
    paths = [str(repository_root), str(repository_root / "src")]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    environment = os.environ.copy()
    environment.update(
        {
            "AGENTGYM_SNAPSHOT_PATH": str(snapshot_path),
            "AGENTGYM_CONTROL_KEY": control_key,
            "AGENTGYM_PORT": str(port),
            "PYTHONPATH": os.pathsep.join(paths),
        }
    )
    return environment


def _reserve_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _default_capabilities() -> list[Capability]:
    return [
        Capability(id="confluence.pages.read", system="confluence", operation="pages.read"),
        Capability(id="confluence.pages.write", system="confluence", operation="pages.write"),
        Capability(id="confluence.search", system="confluence", operation="search"),
    ]


__all__ = ["ProcessWorldError", "ProcessWorldProvider"]
