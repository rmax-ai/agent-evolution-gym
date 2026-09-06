"""Agent package contracts and directory persistence."""

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, field_validator

from agentgym.core.domain import DomainSpec
from agentgym.core.json_safe import ensure_json_safe
from agentgym.world.capabilities import Capability


class PackageIntegrityError(ValueError):
    """Raised when a package manifest does not match its artifact files."""


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
    parent_id: str | None
    knowledge: list[KnowledgeArtifact]
    skills: list[SkillArtifact]
    tools: ToolPackage
    metadata: dict[str, Any]

    @field_validator("metadata", mode="before")
    @classmethod
    def validate_metadata(cls, value: object) -> object:
        """Reject package metadata that cannot be persisted as JSON."""

        return ensure_json_safe(value)

    def validate_capabilities(
        self,
        domain_capabilities: DomainSpec | Iterable[str | Capability],
    ) -> None:
        """Raise when declared capabilities exceed the domain capability set.

        This subset check is defense in depth only. Authorization ownership
        remains at the runner boundary, where the §21 capability proxy and the
        §64 test-split isolation rules are enforced (D9); this method does not
        authorize MCP code or raw API calls.
        """

        self.tools.validate_capabilities(domain_capabilities)

    @classmethod
    def from_directory(
        cls,
        path: str | Path,
        domain: DomainSpec | Iterable[str | Capability] | None = None,
    ) -> Self:
        """Load a package manifest from a package directory.

        Persisted hashes are verified against the artifact files on disk and are
        retained as evidence of the manifest that was loaded.
        """

        package_dir = _package_directory(path)
        if not package_dir.is_dir():
            raise NotADirectoryError(f"Package directory does not exist: {package_dir}")

        manifest_path = package_dir / "package.yaml"
        with manifest_path.open(encoding="utf-8") as stream:
            package = cls.model_validate(yaml.safe_load(stream))

        package.verify_hashes(package_dir)
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
        tool_root = _tool_root_path(package_dir, self.tools.root)
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
        try:
            expected = self._computed_hashes(package_dir)
        except FileNotFoundError as error:
            raise PackageIntegrityError(
                "Agent package artifact files do not match the manifest"
            ) from error
        actual = self._stored_hashes()
        if expected != actual:
            raise PackageIntegrityError("Agent package artifact hashes do not match files on disk")

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

        tool_root = _tool_root_path(package_dir, self.tools.root)
        if not tool_root.exists():
            raise FileNotFoundError(f"Tool package root does not exist: {tool_root}")
        _tool_entrypoint(tool_root, self.tools.server_entrypoint)
        return [*knowledge_hashes, *skill_hashes, _sha256_path(tool_root)]

    def _stored_hashes(self) -> list[str]:
        """Return artifact hashes as recorded in the manifest."""

        return [
            *[artifact.sha256 for artifact in self.knowledge],
            *[artifact.sha256 for artifact in self.skills],
            self.tools.sha256,
        ]


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


def _artifact_path(package_dir: Path, collection: str, artifact_path: str) -> Path:
    """Resolve an artifact path while confining it to its declared layer."""

    candidate = _layer_path(package_dir, collection, artifact_path)
    if not candidate.exists():
        raise FileNotFoundError(f"Artifact file does not exist: {artifact_path}")
    return candidate


def _tool_entrypoint(tool_root: Path, entrypoint: str) -> Path:
    """Resolve and validate the MCP server entrypoint."""

    relative_path = _strict_relative_path(entrypoint, field="MCP server entrypoint")
    candidate = (tool_root / relative_path).resolve()
    try:
        candidate.relative_to(tool_root)
    except ValueError as error:
        raise ValueError(f"MCP server entrypoint escapes tool root: {entrypoint}") from error
    if not candidate.is_file():
        raise FileNotFoundError(f"MCP server entrypoint does not exist: {entrypoint}")
    return candidate


def _layer_path(package_dir: Path, collection: str, path: str) -> Path:
    """Resolve a path represented relative to a package layer."""

    relative_path = _strict_relative_path(path, field=f"{collection} artifact")
    if relative_path.parts[:1] == (collection,):
        candidate = package_dir / relative_path
    else:
        if relative_path.parts[:1] in {"knowledge", "skills", "mcp", "package.yaml"}:
            raise ValueError(f"{collection} artifact path crosses package layers: {path}")
        candidate = package_dir / collection / relative_path

    layer_root = (package_dir / collection).resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(layer_root)
    except ValueError as error:
        raise ValueError(f"{collection} artifact path escapes its layer: {path}") from error
    return resolved


def _tool_root_path(package_dir: Path, root: str) -> Path:
    """Resolve a tool root that must be ``mcp`` or one of its descendants."""

    relative_path = _strict_relative_path(root, field="tool package root")
    if relative_path.parts[:1] != ("mcp",):
        raise ValueError(f"Tool package root must be under the mcp layer: {root}")

    mcp_root = (package_dir / "mcp").resolve()
    resolved = (package_dir / relative_path).resolve()
    try:
        resolved.relative_to(mcp_root)
    except ValueError as error:
        raise ValueError(f"Tool package root escapes the mcp layer: {root}") from error
    return resolved


def _strict_relative_path(path: str, *, field: str) -> Path:
    """Parse a package path and reject absolute or traversal components."""

    relative_path = Path(path)
    if relative_path.is_absolute() or not relative_path.parts:
        raise ValueError(f"{field} must be a non-empty relative path: {path}")
    if any(part in {".", ".."} for part in relative_path.parts):
        raise ValueError(f"{field} must not contain traversal components: {path}")
    return relative_path


def _sha256_path(path: Path) -> str:
    """Hash one file or a canonical, path-aware tree of regular files.

    Individual knowledge and skill artifacts retain their byte digest. Tool
    directories include each POSIX relative path and byte length before the file
    bytes, in sorted path order, so renames and ambiguous concatenations change
    the digest. Symlinks are rejected rather than hashing an unspecified target.
    """

    digest = hashlib.sha256()
    if path.is_symlink():
        raise ValueError(f"Symlinks are not allowed in package artifacts: {path}")
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        entries = list(path.rglob("*"))
        if any(candidate.is_symlink() for candidate in entries):
            raise ValueError(f"Symlinks are not allowed in tool package trees: {path}")
        files = sorted(
            (candidate for candidate in entries if candidate.is_file()),
            key=lambda candidate: candidate.relative_to(path).as_posix(),
        )
        for candidate in files:
            relative_path = candidate.relative_to(path).as_posix().encode("utf-8")
            contents = candidate.read_bytes()
            digest.update(len(relative_path).to_bytes(8, "big"))
            digest.update(relative_path)
            digest.update(len(contents).to_bytes(8, "big"))
            digest.update(contents)
    else:
        raise FileNotFoundError(f"Artifact path does not exist: {path}")
    return digest.hexdigest()
