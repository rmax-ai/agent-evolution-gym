# AGENTS.md — Agent Evolution Gym

Conventions for Codex, Cursor, and human contributors. **SPEC.md is the sole source
of truth** (v0.1, 80 numbered sections, repo root). When this file and SPEC.md
disagree, SPEC.md wins. Cite SPEC section numbers in issues, PRs, and comments.

## Project DNA

**What this is.** A reproducible environment for automatically constructing and
refining deployable domain-agent capability packages through executable experience
(§80). The intended output is not a benchmark score — it is a better Agent Package (§80).

**What evolves — and only this.** The external, deployable `AgentPackage` (§1, §15),
conceptually `P = K + S + T` (§2):

- `knowledge/` — declarative domain knowledge, preferably Markdown (§16);
- `skills/` — procedural skills/prompts, `SKILL.md` per skill (§17);
- `mcp/` — workflow-level MCP tools with declared capabilities (§18).

The optimization loop is: execute task curriculum → trajectories + final world states →
deterministic verification → failure clustering + diagnosis → bounded package mutations →
validate candidate → accept/reject → AgentPackage N+1 (§1). The Gym does not optimize the
language model or agent harness (§3.2).

**What never changes — the fixed substrate** (§3.1, §80): task distribution, simulated
world, raw system APIs, permissions, verifiers, execution runtime. Also immutable during
optimization: foundation-model weights, hidden task definitions, environment state
generators (§3.2). The optimizer may improve the interface presented to the agent; it must
never modify the underlying simulated enterprise API (§3.1) or gain new privileges (§14).

**Core principles to honor in every change** (§3.3–§3.7): verification is external and
never trusts the agent; evaluate side effects (required + forbidden + invariants), not
just outcomes; train/eval on distributions via ScenarioFamily → TaskGenerator →
TaskInstances, not a static prompt set; held-out generalization (train/validation/test)
is mandatory; every optimization step is attributable — parent generation, exact
mutation, motivation, supporting failure evidence, validation delta, accept/reject reason.
No opaque "improve prompt" operations (§3.7).

## Code organisation (SPEC §7)

- `src/agentgym/` — the package, modules mirroring the SPEC:
  `core/` (domain, task, package, mutation, rollout, verification, trajectory,
  generation), `runner/` (runner, lifecycle, budgets), `world/` (base, snapshot,
  capabilities, docker), `runtime/` (base, process, reference_agent), `solver/` (base,
  diagnosis, mutations, greedy, reflection), `optimizer/` (optimizer, selection, pareto),
  `verifier/` (base, predicates, state_diff), `storage/` (store, sqlite, filesystem),
  `cli/` (main).
- `domains/<domain>/` — self-contained, pluggable domain packages: `domain.yaml`,
  `world/` (docker-compose + api/models/fixtures), `scenarios/`, `verifiers/`,
  `splits/` (`train.yaml`, `validation.yaml`, `test.yaml`).
- `packages/<name>/` — AgentPackage artifacts: `package.yaml`, `knowledge/`, `skills/`,
  `mcp/`.
- `experiments/` — run configurations and outputs.
- `tests/` — `unit/`, `integration/`, `domains/`, `e2e/`.

## Execution conventions

- uv-managed project (Python 3.12+); use `uv sync` / `uv run` / `uv add`, never pip
  directly. PyYAML, Pydantic v2, pytest, Typer, httpx per §71.
- Lint/format: `ruff check` and `ruff format` — run both, keep clean.
- Types: `ty` or `mypy` as configured in `pyproject.toml`; protocols in §70 must type-check.
- Tests: `pytest`. Async protocols are the norm (§70) — use `pytest-asyncio` (asyncio_mode
  auto) for all async tests.

## Testing requirements

- Encode every architecture invariant of SPEC §75 in tests (task/package isolation,
  solver/test-split isolation, MCP↔raw-API boundary, verifier self-report distrust, world
  reset, generation immutability, mutation lineage, optimizer boundaries).
- Unit tests must never require Docker or network: depend on the world-provider
  abstraction (`world/base.py`) and a lightweight in-process provider; Docker-backed
  `world/docker.py` is exercised in integration/domains/e2e only.
- Verifier tests must include deliberately wrong oracle implementations: a known-good
  oracle passes all generated tasks, and deliberately incorrect implementations fail the
  expected assertions (§72 Phase 3 acceptance).

## Architecture non-negotiables

- **Solver never touches test-split ground truth** (§64): test is completely inaccessible
  during optimization; validation exposes task outcome only, and assertion-level feedback
  is not given to the mutation solver by default.
- **Generated MCP never bypasses raw APIs** (§21): sandboxed container, network limited to
  the declared world API gateway via a capability proxy; no access to verifier, ground
  truth, database, fixtures, host filesystem, Docker socket, package history, test split,
  or optimizer state.
- **Verifier never trusts agent self-report** (§3.3): verify from world state and
  deterministic assertions; LLM grading is not used for primary success criteria.
- **Generations are immutable after acceptance** (§45); mutations are explicit diffs with
  lineage and evidence (§35); each package evaluation runs in a fresh world (§62).
- **Domain world provider abstraction**: domains declare `world_provider`; the core never
  hard-couples to Docker so unit tests stay hermetic (§8.1, §11).

## Pitfalls for coding agents

- Pydantic v2 idioms: use `StrEnum` for taxonomy enums (`RunStatus` §31,
  `ToolMutationType` §20); write `object | None` unions (e.g. `AssertionResult.expected`/
  `actual` §28), not bare `object`; persisted contracts are Pydantic models (§8).
- Never use `datetime.utcnow()` (deprecated); use timezone-aware
  `datetime.now(timezone.utc)` for snapshot/event timestamps (§12, §25).
- No mutable default arguments; budget/limit fields are explicit `BaseModel` defaults
  (§24, §36).
- Async-first IO: all core protocols are async (§70); use `httpx`, not `requests`; no
  blocking calls inside `runner/`, `world/`, or `verifier/` hot paths.
- Don't add convenience API endpoints to make agents succeed — the simulator is the
  underlying system, not the solution (§13).
