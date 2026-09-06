# ROADMAP.md — Agent Evolution Gym v0.1

Implementation roadmap derived from **SPEC §72** (Development Phases 1–8) and
**SPEC §76** (Suggested First Implementation Sequence). SPEC.md is the source of truth;
each phase below quotes its SPEC acceptance language. This repo is developed through
GitHub issues (see "Pipeline notes") — phases map to milestone epics, not to branches
that diverge from main.

## Phase summary

| # | Focus | Key deliverables | Acceptance criteria (SPEC §72) | Dependencies |
|---|-------|------------------|-------------------------------|--------------|
| 1 | Core models | `core/` Pydantic models: Task, DomainSpec, WorldSnapshot, AgentPackage, Rollout, VerificationResult, Mutation, Generation | All persisted models round-trip cleanly and are covered by unit tests | — |
| 2 | Static Confluence world | `domains/confluence/world/`: users, spaces, pages, versions, permissions; REST APIs; snapshot/restore | The world can be deterministically restored from a snapshot | 1 |
| 3 | Task generators + verifiers | ≥5 scenario generators, 20+ concrete tasks, state-based verifiers, splits | Known-good oracle passes all tasks; deliberately incorrect implementations fail expected assertions | 2 |
| 4 | Baseline Agent Package | `packages/baseline/`: minimal knowledge, primitive MCP, no advanced skills | Baseline succeeds on some but not all tasks; target 30–60% initial success | 2, 3 |
| 5 | Rollout infrastructure | `runner/`, trajectory logging, run manifests, metrics, failure taxonomy (`RunStatus` §31) | Any failed rollout can be reconstructed from stored artifacts | 4 |
| 6 | Skill/Knowledge evolution | `solver/` diagnosis, knowledge + skill mutations, held-out validation, generation lineage, rejection memory | The optimizer can produce at least one validated improvement over the baseline package | 5 |
| 7 | MCP evolution | CREATE/EDIT/DELETE_TOOL, MCP sandbox, static checks, capability proxy, contract tests | The solver can synthesize a workflow tool without gaining undeclared environment access | 6 |
| 8 | Generalization experiment | Full evolution across train → validation → hidden test (§64) | Demonstrate improvement on hidden tasks, not only training examples | 7 |

## Phase details

### Phase 1 — Core models
Implement the `core/` persisted contracts: Task (§9), DomainSpec (§8.1), WorldSnapshot
(§12), AgentPackage (§15), Rollout (§26), VerificationResult (§28), Mutation (§35),
Generation (§45). All contracts are Pydantic v2 models (§8). Acceptance (SPEC §72):
> All persisted models round-trip cleanly and are covered by unit tests.

### Phase 2 — Static Confluence world
Build the first domain's simulator: users, spaces, pages, versions, permissions; REST
APIs that behave like real enterprise APIs (auth, authorization, version conflicts,
pagination, realistic errors — §13); snapshot/restore (§11–§12). Do not add convenience
endpoints that merely make agents succeed (§13). Acceptance (SPEC §72):
> The world can be deterministically restored from a snapshot.

### Phase 3 — Task generators + verifiers
Implement at least 5 scenario generators across the initial families — Retrieval,
Basic editing, Preservation, Concurrency, Permissions (§57) — yielding 20+ concrete
tasks, plus state-diff verifiers over initial vs. final snapshots (§29–§30) and the
train/validation/test splits (§3.6, §64). Acceptance (SPEC §72):
> Known-good oracle implementation passes all generated tasks. Deliberately incorrect
> implementations fail expected assertions.

### Phase 4 — Baseline Agent Package
Assemble `packages/baseline/` (§7, §58): minimal knowledge, primitive MCP tools
(`get_page`, `search_pages`, `update_page`), no advanced skills. Wire one deliberately
thin reference runtime (§23). Acceptance (SPEC §72):
> Baseline agent succeeds on some but not all tasks. A 100% baseline is undesirable
> because evolution cannot be demonstrated. Target initial success: 30–60%.

### Phase 5 — Rollout infrastructure
Implement the Runner (§5, §70), trajectory logging at observable boundaries (§25),
run manifests for reproducibility (§54), rollout metrics (§27), and the failure
taxonomy — infrastructure failures tracked separately from task failures (§31, §67).
Acceptance (SPEC §72):
> Any failed rollout can be reconstructed from stored artifacts.

### Phase 6 — Skill/Knowledge evolution
Close the learning loop without tools: diagnosis (§32–§34), knowledge mutations
(ADD/EDIT/DELETE/SPLIT/MERGE_DOCUMENT §16), skill mutations (CREATE/EDIT/DELETE_SKILL
§17), held-out validation with the acceptance policy (§40–§41, §49), immutable
generation lineage (§45), and rejection memory (§46). Acceptance (SPEC §72):
> The optimizer can produce at least one validated improvement over the baseline package.

### Phase 7 — MCP evolution
Add tool-layer evolution: CREATE_TOOL / EDIT_TOOL / DELETE_TOOL (§20), the MCP
validation pipeline (§22), sandbox with capability proxy and no undeclared network
access (§21), and contract tests. Tool synthesis requires trajectory evidence of a
stable deterministic operation (§19, §61). Acceptance (SPEC §72):
> The solver can synthesize a workflow tool without gaining undeclared environment access.

### Phase 8 — Generalization experiment
Run the full evolution (§49–§50) across train, validation, and the hidden test split
(§64), with regression attribution per accepted generation (§44) and evaluation
statistics per package (§66). Acceptance (SPEC §72):
> Demonstrate improvement on hidden tasks, not only training examples.

## Build order rationale (SPEC §76)

Do not start with optimization. The SPEC prescribes this order:

1. Confluence simulator (P2) → 2. deterministic snapshots (P2) → 3. scenario generator
(P3) → 4. verifier (P3) → 5. primitive MCP (P4) → 6. baseline runtime (P4/P5) →
7. trajectory recorder (P5) → 8. evaluation CLI (P5) → 9. AgentPackage persistence (P6)
→ 10. knowledge mutation (P6) → 11. skill mutation (P6) → 12. validation acceptance
loop (P6) → 13. failure clustering (P6) → 14. MCP mutation (P7) → 15. meta-consolidation
(§47).

Rationale (SPEC §76): "This minimizes uncertainty. If the simulator and verifier are
wrong, optimization results are meaningless." Phase 1 core models land first as the
enabling foundation (every later phase persists Pydantic contracts through them);
within that constraint, environment+verifier work precedes any evolution machinery.

## Success criteria and stretch goal

- **PoC success criteria:** SPEC §73 — weak baseline package → realistic low-level APIs →
  non-trivial task distribution → deterministic verifiers catching collateral damage →
  solver improves knowledge/skills with held-out validation → at least one accepted
  package improves validation → one MCP tool created/improved → improvement transfers to
  hidden test instances → all generations reproducible and auditable.
- **Stretch goal (SPEC §74):** emergent abstraction — training failures suggest a
  bespoke tool (e.g. `edit_deployment_section_safely`) but broader validation drives
  replacement by a general one (`safe_patch_page`) that solves more scenario families at
  lower package complexity. Track the knowledge → skill → tool progression (§59) and
  tool-usage telemetry (§60) as the signal.
- Research framing: RQ1–RQ7 (§79) should be answerable from stored artifacts once
  Phases 6–8 land.

## Pipeline notes

- **Issues:** development is tracked as GitHub issues with label columns
  (e.g. `todo`, `in-progress`, `blocked`, `review`, `done`); every phase is a milestone
  epic, each numbered deliverable a linked issue that cites its SPEC sections.
- **Verification gates:** every merge passes, in order: `ruff check` → type check
  (`ty`/`mypy`) → `pytest` (unit + affected suites). Architecture-invariant tests
  (SPEC §75) and deliberately-wrong-oracle verifier tests are part of the default suite.
- **Final validation:** before calling a phase done, run a fresh-clone claims audit —
  clone the repo, `uv sync`, run all gates, and reproduce the phase's headline claims
  (snapshot determinism, oracle results, baseline %, accepted generations, hidden-test
  transfer) from committed artifacts alone.
