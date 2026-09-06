"""Agent package contracts and directory persistence."""

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel

from agentgym.core.domain import DomainSpec
from agentgym.world.capabilities import Capability


class KnowledgeArtifact(BaseModel):
    """A declarative knowledge document included in an agent package."""

    path: str
    sha256: str
    tags: list[str]


class SkillArtifact(BaseModel):
    """A procedural skill document included in an agent package."""

    path: str
    sha256: str


class ToolPackage(BaseModel):
    """The deterministic MCP tools included in an agent package."""

    root: str
    server_entrypoint: str
    sha256: str
    declared_capabilities: list[str]

    def validate_capabilities(
        self,
        domain_capabilities: DomainSpec | Iterable[str | Capability],
    ) -> None:
        """Raise when the tool package declares a capability outside the domain."""

        allowed = _capability_ids(domain_capabilities)
        undeclared = sorted(set(self.declared_capabilities) - allowed)
        if undeclared:
            capabilities = ", ".join(undeclared)
            raise ValueError(f"Tool package declares unavailable capabilities: {capabilities}")


class AgentPackage(BaseModel):
    """The portable, persisted knowledge, skill, and tool package for an agent."""

    id: str
    version: str
    generation: int
    parent_id: str | None = None
    knowledge: list[KnowledgeArtifact]
    skills: list[SkillArtifact]
    tools: ToolPackage
    metadata: dict[str, Any]

    def validate_capabilities(
        self,
        domain_capabilities: DomainSpec | Iterable[str | Capability],
    ) -> None:
        """Raise when this package's MCP tools exceed the domain capabilities."""

        self.tools.validate_capabilities(domain_capabilities)

    @classmethod
    def from_directory(
        cls,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> Self:
        """Load a package manifest from a package directory.

        Hashes are recomputed from the artifact bytes on disk so the returned
        contract reflects the files that will actually be executed.
        """

        package_dir = _package_directory(path)
        if not package_dir.is_dir():
            raise NotADirectoryError(f"Package directory does not exist: {package_dir}")

        manifest_path = package_dir / "package.yaml"
        with manifest_path.open(encoding="utf-8") as stream:
            package = cls.model_validate(yaml.safe_load(stream))

        package._set_hashes(package_dir)
        if domain is not None:
            package.validate_capabilities(domain)
        return package

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> Self:
        """Load a package from its ``package.yaml`` file."""

        manifest_path = Path(path)
        if manifest_path.name != "package.yaml":
            raise ValueError("Agent package manifests must be named package.yaml")
        return cls.from_directory(manifest_path.parent, domain=domain)

    @classmethod
    def load(
        cls,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> Self:
        """Load a package from either its directory or its package manifest."""

        package_path = Path(path)
        if package_path.is_file():
            return cls.from_yaml(package_path, domain=domain)
        return cls.from_directory(package_path, domain=domain)

    def save(
        self,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> None:
        """Write ``package.yaml`` after hashing the package's artifact files."""

        if domain is not None:
            self.validate_capabilities(domain)

        package_dir = _package_directory(path)
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "knowledge").mkdir(exist_ok=True)
        (package_dir / "skills").mkdir(exist_ok=True)
        tool_root = _resolve_path(package_dir, self.tools.root)
        tool_root.mkdir(parents=True, exist_ok=True)

        self._set_hashes(package_dir)
        manifest = yaml.safe_dump(
            self.model_dump(mode="json"),
            sort_keys=False,
        )
        (package_dir / "package.yaml").write_text(manifest, encoding="utf-8")

    def to_directory(
        self,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> None:
        """Alias for :meth:`save`."""

        self.save(path, domain=domain)

    def to_yaml(
        self,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> None:
        """Write a package manifest and its computed artifact hashes."""

        manifest_path = Path(path)
        if manifest_path.name != "package.yaml":
            raise ValueError("Agent package manifests must be named package.yaml")
        self.save(manifest_path.parent, domain=domain)

    def verify_hashes(self, path: str | Path) -> None:
        """Raise if persisted artifact hashes do not match files on disk."""

        package_dir = _package_directory(path)
        expected = self._computed_hashes(package_dir)
        actual = [
            *[artifact.sha256 for artifact in self.knowledge],
            *[artifact.sha256 for artifact in self.skills],
            self.tools.sha256,
        ]
        if expected != actual:
            raise ValueError("Agent package artifact hashes do not match files on disk")

    def _set_hashes(self, package_dir: Path) -> None:
        """Replace manifest hashes with digests computed from package files."""

        computed = self._computed_hashes(package_dir)
        knowledge_count = len(self.knowledge)
        skill_count = len(self.skills)
        for artifact, digest in zip(self.knowledge, computed[:knowledge_count], strict=True):
            artifact.sha256 = digest
        skill_hashes = computed[knowledge_count : knowledge_count + skill_count]
        for artifact, digest in zip(self.skills, skill_hashes, strict=True):
            artifact.sha256 = digest
        self.tools.sha256 = computed[-1]

    def _computed_hashes(self, package_dir: Path) -> list[str]:
        """Return knowledge, skill, and tool hashes in manifest order."""

        knowledge_hashes = [
            _sha256_path(_artifact_path(package_dir, "knowledge", artifact.path))
            for artifact in self.knowledge
        ]
        skill_hashes = [
            _sha256_path(_artifact_path(package_dir, "skills", artifact.path))
            for artifact in self.skills
        ]

        tool_root = _resolve_path(package_dir, self.tools.root)
        if not tool_root.exists():
            raise FileNotFoundError(f"Tool package root does not exist: {tool_root}")
        _tool_entrypoint(package_dir, tool_root, self.tools.server_entrypoint)
        return [*knowledge_hashes, *skill_hashes, _sha256_path(tool_root)]


def _capability_ids(
    domain_capabilities: DomainSpec | Iterable[str | Capability],
) -> set[str]:
    """Normalize a domain or capability collection to capability IDs."""

    values = (
        domain_capabilities.capabilities
        if isinstance(domain_capabilities, DomainSpec)
        else domain_capabilities
    )
    capability_ids: set[str] = set()
    for capability in values:
        if isinstance(capability, Capability):
            capability_ids.add(capability.id)
        elif isinstance(capability, str):
            capability_ids.add(capability)
        else:
            raise TypeError("Domain capabilities must be strings or Capability models")
    return capability_ids


def _package_directory(path: str | Path) -> Path:
    """Normalize a package directory or its package manifest path."""

    package_path = Path(path)
    return package_path.parent if package_path.name == "package.yaml" else package_path


def _resolve_path(package_dir: Path, path: str) -> Path:
    """Resolve a package-relative path while preventing directory escape."""

    package_root = package_dir.resolve()
    candidate = Path(path)
    resolved = (candidate if candidate.is_absolute() else package_root / candidate).resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as error:
        raise ValueError(f"Package path escapes package directory: {path}") from error
    return resolved


def _artifact_path(package_dir: Path, collection: str, artifact_path: str) -> Path:
    """Resolve an artifact path stored with or without its collection prefix."""

    relative_path = Path(artifact_path)
    candidates = [_resolve_path(package_dir, artifact_path)]
    if not relative_path.is_absolute() and relative_path.parts[:1] != (collection,):
        candidates.append(_resolve_path(package_dir, str(Path(collection) / relative_path)))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Artifact file does not exist: {artifact_path}")


def _tool_entrypoint(package_dir: Path, tool_root: Path, entrypoint: str) -> Path:
    """Resolve and validate the MCP server entrypoint."""

    candidates = [_resolve_path(tool_root, entrypoint)]
    entrypoint_path = Path(entrypoint)
    if not entrypoint_path.is_absolute():
        candidates.append(_resolve_path(package_dir, entrypoint))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"MCP server entrypoint does not exist: {entrypoint}")


def _sha256_path(path: Path) -> str:
    """Hash one artifact file or all files in an artifact directory."""

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        files = sorted(
            (candidate for candidate in path.rglob("*") if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(path).as_posix(),
        )
        for candidate in files:
            digest.update(candidate.read_bytes())
    else:
        raise FileNotFoundError(f"Artifact path does not exist: {path}")
    return digest.hexdigest()
