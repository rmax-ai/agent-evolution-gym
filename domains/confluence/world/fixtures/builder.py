"""Seeded Confluence world fixtures used by tests and scenario generators."""

from random import Random
from typing import Final

from agentgym.world.store import InMemoryConfluenceStore

_DEFAULT_SEED: Final = 0

_USERS: Final[dict[str, dict[str, object]]] = {
    "alice": {
        "id": "alice",
        "username": "alice",
        "name": "Alice Chen",
        "email": "alice@example.test",
        "role": "editor",
    },
    "bob": {
        "id": "bob",
        "username": "bob",
        "name": "Bob Singh",
        "email": "bob@example.test",
        "role": "reader",
    },
    "carol": {
        "id": "carol",
        "username": "carol",
        "name": "Carol Rivera",
        "email": "carol@example.test",
        "role": "editor",
    },
    "admin": {
        "id": "admin",
        "username": "admin",
        "name": "Confluence Administrator",
        "email": "admin@example.test",
        "role": "admin",
        "is_admin": True,
    },
}

_SPACES: Final[dict[str, dict[str, object]]] = {
    "space-1": {
        "id": "space-1",
        "key": "ENG",
        "name": "Engineering",
        "owner_id": "alice",
    },
    "space-2": {
        "id": "space-2",
        "key": "PLAT",
        "name": "Platform",
        "owner_id": "bob",
    },
    "space-3": {
        "id": "space-3",
        "key": "FIN",
        "name": "Finance",
        "owner_id": "carol",
    },
}

_SPACE_PERMISSIONS: Final[dict[str, dict[str, list[str]]]] = {
    "space-1": {"readers": ["alice", "bob", "carol"], "writers": ["alice"]},
    "space-2": {"readers": ["alice", "bob"], "writers": ["bob"]},
    "space-3": {"readers": ["alice", "carol"], "writers": ["carol"]},
}

# The repeated "Deployment" and "Payments" titles intentionally create realistic
# retrieval distractors across spaces.  The body alternatives give seeded scenarios
# small, reproducible variations without changing the resource shape.
_PAGE_TEMPLATES: Final[tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...]] = (
    (
        "page-1",
        "space-1",
        "alice",
        ("Deployment Runbook", "Deployment Guide", "Deployment Procedures"),
        (
            "Production deployment steps for the engineering team.",
            "Release checklist and rollback instructions for production.",
        ),
    ),
    (
        "page-2",
        "space-1",
        "alice",
        ("Deployment Guide", "Deployment Runbook"),
        (
            "Local deployment setup and service ownership notes.",
            "Development deployment workflow for application teams.",
        ),
    ),
    (
        "page-3",
        "space-2",
        "bob",
        ("Deployment Runbook", "Deployment Operations"),
        (
            "Platform deployment steps and cluster verification checks.",
            "Operations guide for platform release coordination.",
        ),
    ),
    (
        "page-4",
        "space-2",
        "bob",
        ("Payments Architecture", "Payment Architecture"),
        (
            "Service boundaries and event flow for payment processing.",
            "Architecture decisions for the payments platform.",
        ),
    ),
    (
        "page-5",
        "space-3",
        "carol",
        ("Payments Architecture", "Payments Operations"),
        (
            "Finance controls and reconciliation requirements for payments.",
            "Operational ownership and reporting for payment workflows.",
        ),
    ),
    (
        "page-6",
        "space-3",
        "carol",
        ("Deployment Runbook", "Deployment Change Policy"),
        (
            "Finance change-control policy for production deployments.",
            "Approval requirements for deployment-related financial systems.",
        ),
    ),
)

_VARIANT_ALIASES: Final[dict[str, str]] = {
    "": "default",
    "full": "default",
    "standard": "default",
    "retrieval": "default",
    "concurrency": "concurrent_edit",
    "concurrent": "concurrent_edit",
    "permission": "permissions",
    "smoke": "minimal",
}

_BUILTIN_VARIANTS: Final[frozenset[str]] = frozenset(
    {"default", "minimal", "permissions", "concurrent_edit"}
)


def build_store(seed: int | None = None, *, variant: str = "default") -> InMemoryConfluenceStore:
    """Build a populated, deterministic Confluence store.

    ``seed`` controls only fixture variation; it never changes the resource schema.
    Omitting the seed selects a stable default so scenario setup remains reproducible.
    ``variant`` is intentionally permissive so future scenario families can introduce
    names without changing this public helper.  The built-in variants are ``default``,
    ``minimal``, ``permissions``, and ``concurrent_edit``.
    """

    normalized_variant = _normalize_variant(variant)
    rng = Random(_DEFAULT_SEED if seed is None else seed)
    space_ids = _space_ids_for_variant(normalized_variant)
    templates = _templates_for_variant(normalized_variant)
    users = {user_id: dict(user) for user_id, user in _USERS.items()}
    spaces = {space_id: dict(space) for space_id, space in _SPACES.items() if space_id in space_ids}
    permissions = {
        "spaces": {
            space_id: {
                "readers": list(entry["readers"]),
                "writers": list(entry["writers"]),
            }
            for space_id, entry in _SPACE_PERMISSIONS.items()
            if space_id in space_ids
        },
        "pages": (
            {"page-6": {"readers": ["alice", "carol"], "writers": ["carol"]}}
            if any(template[0] == "page-6" for template in templates)
            else {}
        ),
    }

    store = InMemoryConfluenceStore(users=users, spaces=spaces, permissions=permissions)
    for template in templates:
        page_id, space_id, owner_id, title_options, body_options = template
        if space_id not in spaces:
            continue
        store.add_page(
            {
                "id": page_id,
                "space_id": space_id,
                "title": rng.choice(title_options),
                "body": rng.choice(body_options),
                "owner_id": owner_id,
            }
        )

    if normalized_variant == "concurrent_edit" and "page-1" in store.pages:
        store.update_page("page-1", body="A human editor updated this page after the initial read.")

    return store


def _normalize_variant(variant: str) -> str:
    normalized = variant.strip().casefold().replace("-", "_").replace(" ", "_")
    resolved = _VARIANT_ALIASES.get(normalized, normalized)
    if resolved not in _BUILTIN_VARIANTS:
        raise ValueError(
            f"unknown fixture variant: {variant!r}; expected one of {sorted(_BUILTIN_VARIANTS)}"
        )
    return resolved


def _space_ids_for_variant(variant: str) -> set[str]:
    if variant == "minimal":
        return {"space-1", "space-2"}
    return set(_SPACES)


def _templates_for_variant(
    variant: str,
) -> tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...]:
    if variant == "minimal":
        return _PAGE_TEMPLATES[:2]
    if variant == "permissions":
        return _PAGE_TEMPLATES[:1] + _PAGE_TEMPLATES[4:]
    return _PAGE_TEMPLATES


build_fixture_store = build_store
