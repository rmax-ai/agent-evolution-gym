# Dev-2 review — Static Confluence world

Review date: 2026-09-06. Scope is the merged Dev-2 world/store/API/fixture work
named in the request. No production source was changed.

## Verdict summary

| Area | Verdict | Severity |
| --- | --- | --- |
| §13 raw-API realism | ISSUE | High |
| §14 permission and capability boundary | ISSUE | High |
| Optimistic concurrency and immutable history | ISSUE | High |
| §12 snapshot/restore determinism | ISSUE | Medium |
| §56 API surface | OK | — |
| Fixtures for §57 families | ISSUE | Medium |
| Dev-3 lifecycle/runtime consumption | ISSUE | Blocker |

## Findings

### 1. Declared Docker world is not runnable

**ISSUE — Blocker.** `domain.yaml` declares `world_provider: docker` (SPEC §8.1),
but `DockerWorldProvider.start`, `restore`, `snapshot`, and `stop` always raise
(`DockerProviderUnavailable` without Docker and `NotImplementedError` with it)
([docker.py](../../src/agentgym/world/docker.py#L54-L88)). A runner therefore
cannot obtain the fresh, restorable world required by SPEC §§11, 12, 62, and 75.

Compose serves `main:app`, a module-global app created with an empty store
([app.py](../../domains/confluence/world/api/app.py#L20-L35),
[app.py](../../domains/confluence/world/api/app.py#L58)). `start_world()` only
sets an in-process flag; it neither starts uvicorn nor wires a supplied store to
the global app ([app.py](../../domains/confluence/world/api/app.py#L38-L55)).
Fixtures are never wired into that entrypoint.

**Follow-up:** implement per-execution process/container lifecycle, readiness,
loopback URL, restore/snapshot transport, and shutdown. Seed/restore state must
be passed to the served world, not a separate app instance. Add an integration
test: start provider, restore fixture snapshot, mutate over HTTP, snapshot,
then prove the next world is fresh. This blocks Dev-3 runner work.

### 2. Capability declarations are not enforced at the raw API

**ISSUE — High.** `capabilities()` returns all static domain capabilities
([docker.py](../../src/agentgym/world/docker.py#L70-L109)), but FastAPI routes
authorize only `X-Actor`. There is no task-scoped capability set, proxy/token,
or route enforcement for `confluence.pages.write` or `confluence.search`. A
loopback caller can invoke every raw route regardless of its execution grant.
This fails the explicit non-escalating set in SPEC §14 and the boundary in
§§21 and 62.

**Follow-up:** have runner/provider construct grants per execution and expose
the raw service only through an authenticated capability proxy/gateway. Test
user ACLs and task capabilities as independent checks.

### 3. Permission policy has unconditional owner/admin escalation

**ISSUE — High.** Page owners and global admins bypass both page and space ACLs
([routes.py](../../domains/confluence/world/api/routes.py#L114-L135)); space
owners/admin-list members bypass ACLs on create
([routes.py](../../domains/confluence/world/api/routes.py#L105-L112),
[routes.py](../../domains/confluence/world/api/routes.py#L191-L199)). Thus an
owner can write despite being absent from both grants and an admin can write
anything. If this is intended, it needs to be an explicit modeled policy, not
an implicit override: scenario generators cannot express owner/admin denial and
it weakens the requested §14 least-privilege boundary.

The flexible, undocumented permission shapes also widen access accidentally: a
bare list/string naming an actor, or `True`, grants both read and write
([routes.py](../../domains/confluence/world/api/routes.py#L218-L249)). Fixtures
use named `readers`/`writers`, but consumers are offered multiple semantics.

**Follow-up:** define one persisted ACL schema with explicit read/write/admin
rules. Decide whether owner/admin is an ACL grant or policy bypass; test both
positive and negative owner/admin cases and every accepted representation.

### 4. Compare-and-update is not a store-level atomic operation; history is mutable in-process

**ISSUE — High.** The route validates `If-Version` correctly (400 malformed,
428 missing, 409 stale) ([routes.py](../../domains/confluence/world/api/routes.py#L483-L534)).
Because current mutation contains no `await`, it is effectively serialized in
one event loop today. But `update_page()` accepts no expected version: the route
checks then separately mutates public state ([store.py](../../src/agentgym/world/store.py#L157-L180)).
An async/persistent implementation, callback, direct consumer, or multi-worker
deployment turns this into check-then-write.

History is copied on append/retrieval, but `page_versions` remains public and
`resources` exposes live mutable dictionaries
([store.py](../../src/agentgym/world/store.py#L74-L90)). An in-process caller can
rewrite/delete audit history without an API. This fails the requested
direct-store-bypass standard and SPEC §13 immutable history.

**Follow-up:** make conditional update plus version bump/history append one
transaction/lock-protected store operation; race two writers and require exactly
one winner. Keep mutable state private or return detached/read-only views; test
that supported store accessors cannot change retained history.

### 5. Snapshot state is copied, but full snapshots and pagination are not deterministic

**ISSUE — Medium.** Deep-copy/restore behavior is sound for the covered resource
aliasing cases. Yet `snapshot()` inserts wall-clock `timestamp`
([store.py](../../src/agentgym/world/store.py#L92-L101)); identical states yield
different serialized `WorldSnapshot`s. Existing tests compare only `resources`.
List/search preserve `store.pages` insertion order with no canonical sort
([routes.py](../../domains/confluence/world/api/routes.py#L350-L382)), so offset
pagination is only stable when construction order happens to be stable.

**Follow-up:** inject/explicitly set snapshot timestamps for reproducible state
identity (or clearly separate provenance from equality), test full snapshots as
intended, and define a stable list/search sort key before pagination. Test
equivalent states built in different insertion orders.

### 6. §13 realism remains incomplete

**ISSUE — High.** Auth, ACLs, common error envelopes, visibility filtering,
offset pagination, conflicts, and API-level version history exist. But §13 also
calls for partial failures and latency where relevant; no deterministic latency
profile, fault injection, timeout, transient failure, or partial-result/write
mode exists. This leaves retry/error skills unexercised.

Pagination validates bounds and computes total after visibility filtering, but
lacks a stable ordering guarantee (finding 5). Continuation tokens are optional
at this stage; stable ordering is not.

**Follow-up:** add deterministic scenario-configured latency/failure profiles at
the raw boundary, with normal error envelopes and defined state effects. Add
tests for invalid/out-of-range pages, stable order, and failure paths.

### 7. Raw API surface is narrow and appropriate

**OK.** The six exposed operations are list/search/get/version/create/update;
they match the initial §56 resource operations and do not add comments, labels,
attachments, or solution-shaped convenience endpoints. Preserve this split by
keeping lifecycle/control facilities outside the agent-visible raw API.

### 8. Fixtures are a useful start but lack scenario control

**ISSUE — Medium.** Repeated Deployment/Payments titles across spaces and seeded
alternatives are useful retrieval distractors
([builder.py](../../domains/confluence/world/fixtures/builder.py#L69-L133)). The
permissions variant gives one read-but-not-write case. However it is only six
pages/three spaces; variants mostly delete pages rather than parameterizing
distractor density and ACL modes; default owner/admin bypasses limit permission
cases. This is not yet the breadth expected for SPEC §§10 and 57.

`concurrent_edit` pre-applies the change before rollout
([builder.py](../../domains/confluence/world/fixtures/builder.py#L194-L195)); it
cannot model a change after read or coordinate a human write. Unknown variant
names silently resolve to default ([builder.py](../../domains/confluence/world/fixtures/builder.py#L200-L218)),
masking generator errors.

**Follow-up:** use typed, rejecting fixture/scenario parameters. Add composable
controls for exact/similar titles, same-title cross-space distractors,
neighboring sections, page/space ACL intersections, owner/admin policy modes,
and a deterministic post-read concurrent-write hook.

## Verification performed

`uv run pytest tests/domains/test_confluence_api.py tests/domains/test_confluence_api_permissions.py tests/unit/test_confluence_store.py tests/unit/test_domain_and_snapshots.py tests/unit/test_world_protocols.py -q` passed: **28 tests**.

`uv run ruff check` over the reviewed source and tests passed. These checks do
not exercise a running Docker provider, task-scoped capabilities, fault/latency,
or a genuine competing-writer compare-and-swap.
