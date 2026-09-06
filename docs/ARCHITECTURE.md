# Agent Evolution Gym — Architecture

**Version:** v0.1 (companion document)
**Source of truth:** `SPEC.md` (Technical Design Specification, Draft for implementation). This document is descriptive of the architecture specified there; where the two differ, SPEC.md prevails.
**Scope:** System architecture for Agent Evolution Gym v0.1 — an environment for automatically developing domain-specialized AI agents through repeated task execution, verification, failure analysis, and controlled modification of the agent's **external** capability substrate.

All section references (`SPEC §N`) point to numbered sections of SPEC.md.

---

## 1. Executive Summary

Agent Evolution Gym automatically develops domain-specialized AI agents by repeatedly executing tasks, verifying outcomes, analyzing failures, and applying **controlled, bounded mutations** to the agent's *deployable external capability package* — never to the model or the harness (SPEC §1).

The system deliberately holds the following **relatively fixed** (SPEC §1):

- task distribution;
- simulated enterprise world;
- raw system APIs;
- permissions;
- verification logic;
- execution runtime.

It evolves an external, deployable **AgentPackage** composed of (SPEC §1, §2):

1. domain knowledge (`knowledge/`);
2. procedural skills/prompts (`skills/`);
3. workflow-level MCP tools (`mcp/`).

The core optimization loop is (SPEC §1, §80):

```
AgentPackage N
      ↓
execute task curriculum
      ↓
trajectories + final world states
      ↓
deterministic verification
      ↓
failure clustering + diagnosis
      ↓
propose bounded package mutations
      ↓
validate candidate
      ↓
accept / reject
      ↓
AgentPackage N+1
```

The objective is **not** "which model or harness performs best?" — it is: *given a fixed domain, task distribution, system APIs, and deterministic verifiers, can an automated solver discover the knowledge, procedural skills, and tool abstractions required to turn a general-purpose agent into a reliable domain-specialized agent?* The Agent Package is the primary trainable artifact (SPEC §1). The intended output is not a benchmark score; the output is a better Agent Package (SPEC §80).

Formally (SPEC §2): `P = K + S + T`, where `P` is the Agent Package, `K` knowledge, `S` skills/instructions, `T` the tool interface. The world and task distribution define the optimization problem `P* = argmax_P E_{t~D}[V(t,P)]` subject to safety constraints, capability boundaries, complexity limits, cost limits, and generalization requirements (SPEC §2). The result must be a portable package attachable to a compatible general-purpose agent runtime (SPEC §2).

**Primary execution model for v0.1:** Python 3.12+, local Docker-based execution, CLI + Python SDK interface, optimization target = externalized Agent Package, initial domain = enterprise knowledge/workflow operations, initial tool protocol = MCP (SPEC header). Explicit non-goals for v0.1 include model fine-tuning, RL on model weights, distributed Kubernetes execution, hosted benchmark marketplaces, production system access, and unrestricted arbitrary code mutation (SPEC §4).

---

## 2. System Model — Seven Concepts (SPEC §5)

The system has **seven main concepts** (SPEC §5):

```
Domain                          AgentPackage                    Solver
│                               │                               │
├── Task Curriculum             ├── Knowledge                   ├── Analyze rollouts
├── World Simulator             ├── Skills                      ├── Diagnose failures
├── Raw System APIs             └── MCP Tools                   ├── Propose mutations
└── Verifiers                                                   └── Select candidates

Runner                          Optimizer
│                               │
├── Provision world             └── Coordinates generations
├── Attach package
├── Run agent                   Artifact Store                  Runtime Adapter
├── Capture trajectory          │                               └── Connects an arbitrary
└── Invoke verifier             ├── packages                       agent runtime to the gym
                                ├── rollouts
                                ├── trajectories
                                └── evaluation results
```

The seven concepts are: **Domain** (task curriculum, world simulator, raw system APIs, verifiers), **AgentPackage** (knowledge, skills, MCP tools), **Solver** (analyze rollouts, diagnose failures, propose mutations, select candidates), **Runner** (provision world, attach package, run agent, capture trajectory, invoke verifier), **Optimizer** (coordinates generations), **Artifact Store** (packages, rollouts, trajectories, evaluation results), and **Runtime Adapter** (connects an arbitrary agent runtime to the gym) (SPEC §5).

**Trainable vs. fixed substrate** (SPEC §1, §3.1, §3.2):

- *Fixed substrate:* task distribution; simulated enterprise world; raw system APIs; permissions; verification logic; execution runtime (SPEC §1). Raw enterprise systems are part of the **world**; MCP workflow abstractions are part of the **agent** (SPEC §3.1).
- *Trainable substrate:* the optimization loop may modify `knowledge/`, `skills/`, `mcp/` only. It must **not** modify: foundation model weights, hidden task definitions, verifiers, raw system APIs, environment state generators, permissions (SPEC §3.2). The optimizer may improve the interface presented to the agent; it must never modify the underlying simulated enterprise API (SPEC §3.1).

**Design principles that shape the architecture** (SPEC §3):

- §3.3 **Verification must be external to the agent** — the agent must not decide whether it succeeded; verification preferentially uses (1) final world state, (2) state differences, (3) deterministic assertions, (4) generated artifact validation, (5) policy/invariant checks; LLM grading should not be required for primary success criteria.
- §3.4 **Evaluate side effects, not only desired outcomes** — a task may succeed while damaging unrelated state; therefore `required changes + forbidden changes + global invariants = verification result`; collateral damage yields FAIL.
- §3.5 **Train and evaluate on distributions, not individual prompts** — domains consist of scenario generators producing many task instances (`ScenarioFamily → TaskGenerator → many TaskInstances`).
- §3.6 **Held-out generalization is mandatory** — every domain contains train / validation / test; the solver gets rich rollout evidence from training tasks; validation determines candidate acceptance; test stays hidden until final evaluation; split by scenario structure where possible, not random near-duplicates.
- §3.7 **Every optimization step must be attributable** — every candidate package carries parent generation, exact mutation, motivation, supporting failure evidence, validation delta, and rejection/acceptance reason. No opaque "improve prompt" operations.

---

## 3. High-Level Data and Control Flow (SPEC §6, §80)

The end-to-end data/control flow (SPEC §6 diagram, annotated):

```
 Domain (task generators, world simulator, verifiers)
        │ task instances
        ▼
      Runner ───────────────► AgentPackage (knowledge, skills, MCP workflows)
        │                              │
        ▼                              ▼
   Static World  ◄────────────  Agent Runtime
   (system APIs, identities,        │ interactions
    permissions, mutable state)     ▼
        │                    Final World State
        ▼                           │
     Verifier ◄─────────────────────┘
        │  trajectory + result
        ▼
     Solver (diagnose → mutate → evaluate)
        │
        ▼
   AgentPackage N+1
```

The learning mechanism of the system is: **execute → observe → verify → diagnose → mutate → validate → retain** (SPEC §80). Mapping onto components:

| Step | Responsible component | SPEC § |
|---|---|---|
| Execute | Runner + Runtime Adapter provision world, attach package, run agent against task instances | §23–27 |
| Observe | Runner captures trajectory events + final world state; Artifact Store persists them | §25–26, §53 |
| Verify | External Verifier computes state-diff assertions over initial vs. final snapshots + trajectory | §28–30 |
| Diagnose | Solver clusters failures and emits first-class Diagnoses | §32–34, §37–38 |
| Mutate | Solver proposes bounded, explicit-diff Mutations (knowledge/skill/tool) | §35–36, §39 |
| Validate | Candidate passes sequential gates: structural → static → smoke → train replay → validation → acceptance policy | §40–41 |
| Retain | Accepted package becomes an immutable Generation; lineage, evidence, regression deltas persisted | §44–46, §53 |

The Optimizer (SPEC §48–49) coordinates this loop across generations and applies stop conditions (SPEC §50). Attribution data flows back into solver inputs (rejected-mutation memory, §46) and into every optimization report (observability, §55).

---

## 4. Component Architecture and Responsibilities

The repository maps components to modules: `core/` (domain, task, package, mutation, rollout, verification, trajectory, generation), `runner/`, `world/`, `runtime/`, `solver/`, `optimizer/`, `verifier/`, `storage/`, `cli/` (SPEC §7). Pydantic models are used for persisted contracts (SPEC §8). The domain directory layout (`domains/confluence/`) packages world (`world/`), scenario generators (`scenarios/`), verifiers (`verifiers/`), and split files (`splits/{train,validation,test}.yaml`) (SPEC §7). Baseline packages live in `packages/baseline/` (SPEC §7, §58).

### 4.1 Domain, Task Curriculum, Scenario Generators (SPEC §8.1, §9, §10, §56–57)

**Responsibilities.** A `DomainSpec` declares the world provider, scenario modules, verifier modules, the three splits, and the capability list (SPEC §8.1). A `Task` is one instantiated problem with a goal, actor identity, initial snapshot reference, verifier id, and metadata; the task id/scenario/split fields tie every task back to its source (SPEC §9). Programmable `ScenarioGenerator`s produce semantically different task instances from a seeded parameter space (SPEC §10).

**Key contract (SPEC §10):**

```python
class ScenarioGenerator(Protocol):
    id: str
    def generate(self, seed: int) -> Task: ...
```

A scenario generator creates: initial world state, user/actor identity, task goal, distractors, expected state transitions, and verifier configuration (SPEC §10). Generators must produce semantically different cases, not surface-level text permutations (SPEC §10).

**Controls and constraints.**

- Task prompts must never expose verifier implementation details (SPEC §9).
- v0.1 ships one domain: the Enterprise Confluence Simulator (users, spaces, pages, versions, permissions) with ~20–30 task templates across five families: A Retrieval, B Basic editing, C Preservation, D Concurrency, E Permissions (SPEC §56–57).
- Training/evaluation is distribution-based: `ScenarioFamily → TaskGenerator → many TaskInstances` (SPEC §3.5). Splits are declared on `DomainSpec` (`train_split`, `validation_split`, `test_split`) (SPEC §8.1) and are scenario-structured where possible (SPEC §3.6).
- The Task model must not know the package implementation (invariant, SPEC §75).

### 4.2 World, WorldSnapshot, Raw System APIs, Capability Boundary (SPEC §11–14)

**Responsibilities.** The `World` protocol provides lifecycle and state management: `start`, `restore(snapshot)`, `snapshot`, `capabilities`, `stop` (SPEC §11). `WorldSnapshot` records a reproducible world state (`resources` dict; JSON persistence initially, database dumps later) (SPEC §12). Raw system APIs are the stable environmental interface that must behave like real enterprise APIs (authentication, authorization, version conflicts, pagination, realistic errors, partial failures, latency where relevant, immutable audit history) (SPEC §13). `Capability` is an explicit `(system, operation)` permission, e.g. `confluence.pages.read`, `confluence.pages.write`, `confluence.search` (SPEC §14).

**Key contracts (SPEC §11, §12):**

```python
class World(Protocol):
    async def start(self) -> None: ...
    async def restore(self, snapshot: WorldSnapshot) -> None: ...
    async def snapshot(self) -> WorldSnapshot: ...
    async def capabilities(self) -> list["Capability"]: ...
    async def stop(self) -> None: ...

class WorldSnapshot(BaseModel):
    id: str
    domain_id: str
    schema_version: str
    timestamp: str
    resources: dict
```

**Controls and constraints.**

- Raw APIs must **not** expose convenience operations merely to make agents successful: "The simulator represents the underlying system, not the desired solution" (SPEC §13).
- **Capability rule (verbatim, SPEC §14):** "Every task execution receives an explicit capability set." "The Agent Package may only build MCP tools using those capabilities." "An evolved tool must never gain new privileges."
- The world must be resettable to a known state (invariant, SPEC §75), and snapshots must make executions reproducible (SPEC §12). "Each package evaluation runs in a fresh world" (SPEC §62).

### 4.3 AgentPackage: Knowledge, Skills, MCP Tool Package (SPEC §15–18)

**Responsibilities.** `AgentPackage` is the trainable unit: id, version, generation, parent id, plus `knowledge: list[KnowledgeArtifact]`, `skills: list[SkillArtifact]`, and a `ToolPackage` (SPEC §15). Directory representation: `package.yaml` + `knowledge/`, `skills/`, `mcp/` (SPEC §15).

- **Knowledge artifacts** (SPEC §16) are declarative Markdown information (domain concepts, terminology, system semantics, policies, troubleshooting, known constraints), each with `path`, `sha256`, `tags`. v0.1 loads all knowledge directly when package size permits; no embedding/retrieval optimization initially. Supported mutations: `ADD_DOCUMENT`, `EDIT_DOCUMENT`, `DELETE_DOCUMENT`, `SPLIT_DOCUMENT`, `MERGE_DOCUMENT`.
- **Skill artifacts** (SPEC §17) are procedural knowledge, e.g. `skills/safely-edit-page/SKILL.md` with When-to-use / Inputs / Procedure / Failure handling / Completion structure. v0.1 implements only `CREATE_SKILL`, `EDIT_SKILL`, `DELETE_SKILL` (generalize/merge are later).
- **ToolPackage** (SPEC §18): deterministic MCP-exposed capabilities with `root`, `server_entrypoint`, `sha256`, and `declared_capabilities`; directory `mcp/` with `server.py`, `tools/`, `tests/`. Baseline tools: `get_page`, `search_pages`, `update_page` (SPEC §18, §58).

### 4.4 Tool Evolution Principle and Mutation Types (SPEC §19–20)

The optimizer may learn to transform repeated reasoning into deterministic tooling (SPEC §19): a repeated trajectory such as `get_page → inspect version → calculate replacement → update_page → get_page → verify` may become a synthesized `safe_patch_page` tool that internally reads → validates → patches → updates → verifies. Expected benefits: reduced model reasoning burden, tool calls, latency, and recurrent failure probability (SPEC §19). **Tool creation occurs only when there is trajectory evidence that a stable deterministic operation exists** (SPEC §19). v0.1 tool mutations are limited to `CREATE_TOOL`, `EDIT_TOOL`, `DELETE_TOOL`; `COMPOSE_TOOLS`, `SPLIT_TOOL`, `GENERALIZE_TOOL` are future and must not be implemented automatically in v0.1 (SPEC §20). Baseline tools are primitive and deliberately weak — a 100% baseline is undesirable because evolution cannot be demonstrated (target initial success 30–60%, SPEC §72 Phase 4).

### 4.5 MCP Security Boundary (SPEC §21)

**Prescribed architecture (SPEC §21):**

```
Agent Runtime
     │
     ▼
Generated MCP server
     │
     │ capability proxy
     ▼
World API Gateway
     │
     ▼
Simulated enterprise APIs
```

**Isolation requirement (verbatim, SPEC §21):** "Generated MCP code must operate in an isolated container." "Generated MCP code must not directly access:" the following — each is a hard prohibition and must not be softened:

- verifier;
- task ground truth;
- underlying database;
- task fixtures;
- host filesystem;
- Docker socket;
- package history;
- test split;
- optimizer state.

"Network access must be limited to the declared world API gateway." (SPEC §21)

This boundary is enforced by (a) container isolation of generated MCP code, (b) a **capability proxy** interposed between the generated MCP server and the World API Gateway, and (c) network egress restricted to the declared gateway. See also §4.21 (safety model) and docs/THREAT_MODEL.md.

### 4.6 MCP Validation Pipeline (SPEC §22)

**Every MCP mutation must pass, in order (verbatim stages, SPEC §22):**

1. parse
2. formatting
3. static typing
4. linting
5. tool-schema validation
6. capability validation
7. unit tests
8. contract tests
9. sandbox startup
10. smoke task
11. validation evaluation

**Failure at stages 1–9 immediately rejects the candidate.** (SPEC §22) Stages 10–11 are evaluation stages: a smoke task exercises the sandboxed candidate, and validation evaluation measures generalization. This pipeline is the acceptance gate for all tool mutations and is the enforcement point for §14 capability rules (§22 stage 6, "capability validation") and §21 isolation.

### 4.7 Runner, Runtime Adapter, Execution Budget (SPEC §23–27)

**Responsibilities.** The `Runner` provisions the world, attaches the package, runs the agent, captures the trajectory, and invokes the verifier (SPEC §5, §6). The `RuntimeAdapter` is deliberately thin (SPEC §23):

```python
class RuntimeAdapter(Protocol):
    async def run(self, goal: str, package: AgentPackage,
                  environment: "EnvironmentConnection", event_sink: "EventSink",
                  budget: "ExecutionBudget") -> "RuntimeResult": ...
```

v0.1 ships exactly one reference runtime — a generic tool-calling model loop. It is **not** optimized and contains **no task-specific logic** (SPEC §23). Model/harness details belong to an execution adapter below the conceptual architecture (SPEC §3.2).

**Execution budget (SPEC §24):**

```python
class ExecutionBudget(BaseModel):
    max_wall_seconds: int = 300
    max_model_turns: int = 50
    max_tool_calls: int = 100
    max_tokens: int | None = None
```

Budget violations are **distinct outcomes** (SPEC §24) — see failure taxonomy (§4.25).

**Trajectory (SPEC §25).** The Gym records interactions only at observable boundaries — no private chain-of-thought is required. Event taxonomy includes `run.started`, `agent.started`, `model.request/response`, `tool.call/result/error`, `world.api.request/response`, `artifact.created`, `agent.error/completed`, `verification.assertion/completed`, `run.completed`. Persisted: observable messages, tool actions, system responses, and state transitions.

**Rollout (SPEC §26).** One execution of one task with one Agent Package: `task_id`, `package_id`, `initial_state_ref`, `final_state_ref`, `trajectory_ref`, `verification`, `metrics`. **RolloutMetrics** (SPEC §27): wall_seconds, model_turns, tool_calls, input/output tokens, estimated cost.

### 4.8 Verifier and State-Diff Verification (SPEC §28–30)

**Responsibilities.** Verification is external to the agent and deterministic (SPEC §3.3). The `Verifier` receives the task, initial snapshot, final snapshot, and trajectory (SPEC §29):

```python
class Verifier(Protocol):
    async def verify(self, task: Task, initial: WorldSnapshot,
                     final: WorldSnapshot, trajectory: "Trajectory") -> VerificationResult: ...
```

The verifier computes `diff = compare(initial_state, final_state)` and checks **required changes**, **forbidden changes**, and **resource invariants** (SPEC §30). Example assertions (SPEC §30):

```python
assert final.pages[target].body == expected_body
assert final.pages[target].version == initial.pages[target].version + 1
assert unchanged(initial.pages[unrelated_id], final.pages[unrelated_id])
assert preserved(concurrent_human_change, final.pages[target])
```

**Verification model (SPEC §28):** `AssertionResult(id, passed, category, expected, actual, message)` and `VerificationResult(passed, score, assertions, required_changes_passed, forbidden_changes_passed, invariants_passed, metadata)`. The verifier **must not** depend on the agent's natural-language final answer unless the task intrinsically requires an answer artifact (SPEC §29), and must not trust agent self-report (SPEC §75). Side effects count: a task that succeeds while damaging unrelated state results in FAIL/collateral damage (SPEC §3.4).

### 4.9 Solver: Diagnosis and Mutations (SPEC §32–39)

**Responsibilities.** The `Solver` analyzes rollouts and proposes mutations (SPEC §32):

```python
class Solver(Protocol):
    async def diagnose(self, package: AgentPackage, rollouts: list[Rollout]) -> list["Diagnosis"]: ...
    async def propose(self, package: AgentPackage, diagnosis: "Diagnosis",
                      budget: "MutationBudget") -> list["Mutation"]: ...
```

**Diagnosis is a first-class artifact** (SPEC §33): `task_ids`, `summary`, `suspected_layer` (valid layers: `knowledge`, `skill`, `tool`, `unknown`), `confidence`, `evidence`, `suggested_mutation_type`. **Diagnostic heuristics** (SPEC §34): missing knowledge (repeated searches for the same fact, wrong interpretation despite correct tool use → knowledge), missing procedure (capabilities exist and facts known but ordering/recovery fails repeatedly, inconsistent procedures across runs → skill), missing tool abstraction (repeated multi-call sequence, deterministic transformations consuming reasoning, repeated errors between same API operations, concurrency/retry/validation discipline needed, high tool-call count around a stable workflow → MCP tool).

**Mutation model (SPEC §35):** every mutation is an explicit diff artifact — `package_id`, `layer`, `operation`, `target`, `rationale`, `evidence_refs`, `patch`. **Mutation Budget (SPEC §36):** prevents uncontrolled package growth —

```python
class MutationBudget(BaseModel):
    max_files_changed: int = 3
    max_added_lines: int = 200
    max_deleted_lines: int = 200
    allow_tool_creation: bool = True
    max_new_tools: int = 1
    max_new_skills: int = 1
```

**Candidates exceeding the budget are rejected** (SPEC §36).

**Evidence and clustering (SPEC §37–38).** The solver receives structured `OptimizationEvidence` — `failures`, `successes`, `failure_clusters`, `aggregate_metrics`, `rejected_mutations` — not raw logs alone; rejected mutations are remembered so known-bad strategies are not repeated (SPEC §37). Before proposing, related failures are grouped: summarize → classify failure layer → cluster on structured tags → prioritize by frequency × severity (SPEC §38); no vector-DB infrastructure initially (SPEC §38). **Candidate generation (SPEC §39):** for each selected diagnosis, generate candidates from `current package + failure evidence + successful contrasting examples + rejected mutation history + mutation budget`; v0.1: 1–3 candidates per optimization step.

### 4.10 Candidate Validation Gates and Acceptance Policy (SPEC §40–41)

**Sequential gates (SPEC §40):**

```
Candidate
   ↓
structural validation
   ↓
static validation
   ↓
smoke tasks
   ↓
train replay subset
   ↓
validation suite
   ↓
acceptance policy
```

"Never run the full validation suite for syntactically broken candidates." (SPEC §40) For MCP mutations, the earlier §4.6 pipeline (parse → … → sandbox startup) supplies the structural/static gates (SPEC §22).

**Acceptance policy (SPEC §41):** do not accept a candidate merely because the training score improved. Minimum constraints:

- validation success ≥ baseline validation success;
- policy violations == 0;
- collateral damage ≤ baseline collateral damage;
- infrastructure errors == 0.

Then require at least one meaningful improvement in: success rate, cost, latency, tool calls, or package complexity (SPEC §41).

### 4.11 Multi-Objective Evaluation and Package Complexity (SPEC §42–43)

Candidate quality is represented as a vector, not collapsed to a scalar (SPEC §42):

```
Q(P) = (success, safety, generalization, cost, latency, complexity)
```

The underlying dimensions are maintained; v0.1 uses a deterministic acceptance policy, and Pareto search is deferred (SPEC §42). **Package complexity metrics** (SPEC §43) to track: `knowledge_tokens`, `skill_tokens`, `skill_count`, `tool_count`, `MCP source LOC`, `MCP dependencies`, `average exposed tools per task`. "The optimizer should be discouraged from solving every case through bespoke artifacts." (SPEC §43)

### 4.12 Regression Attribution (SPEC §44)

After every accepted mutation, compare before-package vs. after-package **for every validation scenario** and persist: newly passing tasks, newly failing tasks, unchanged passes, unchanged failures (e.g. `+12 newly passing, −2 newly failing, 74 unchanged passing, 9 unchanged failing`) (SPEC §44). "Those two regressions must remain visible even if aggregate performance improves." (SPEC §44)

### 4.13 Generation Lineage, Rejected Mutation Memory, Meta-Consolidation (SPEC §45–47)

- **Generation (SPEC §45):** an immutable accepted Agent Package state: `number`, `package_id`, `parent_package_id`, `mutation_ids`, `train_metrics`, `validation_metrics`, `created_at`. Lineage forms a tree: `g0 → g1 (add concurrency skill) → g2 (create safe_patch_page tool) → g3 (simplify skill)`, plus rejected branches.
- **Rejected Mutation Memory (SPEC §46):** `RejectedMutationSummary(mutation_id, diagnosis_id, summary, rejection_reason, regressions)`; relevant rejection history is fed into future solver calls.
- **Meta-Consolidation (SPEC §47):** every N accepted generations (recommended default N = 5), a consolidation solver inspects duplicate knowledge, obsolete rules, overlapping skills, unused skills, overlapping tools, and unnecessarily specialized tools. Allowed operations: remove, merge, generalize, simplify. **Any consolidation candidate must pass the same validation suite.**

### 4.14 Optimizer Loop and Stop Conditions (SPEC §48–50)

The `Optimizer` coordinates the complete evolution loop (SPEC §48). v0.1 algorithm (SPEC §49): run train split with current package → analyze rollouts into evidence → diagnose → prioritize one diagnosis → propose candidates within the mutation budget → for each candidate: structural validation, static validation, apply, smoke evaluation, validation evaluation, acceptance policy → accept first passing candidate, else reject and (optionally) expand diagnosis; repeat. **Stop conditions (SPEC §50):** max generations reached; target validation success reached; no accepted mutation for N iterations; budget exhausted; package complexity threshold exceeded; manual stop. Recommended defaults: `max_generations = 20`, `stagnation_limit = 5` (SPEC §50).

### 4.15 Tool Usage Telemetry and Automated Tool-Making Heuristic (SPEC §60–61)

Tool sequences are recorded so repeated subgraphs can be discovered (SPEC §60). Aggregates: sequence frequency, success correlation, failure correlation, average latency, average tokens around sequence. This evidence can later trigger tool-synthesis proposals (SPEC §60). **Automated tool-making heuristic (SPEC §61):** propose a new tool **only when all of** the following hold:

- same tool sequence appears ≥ 5 times;
- sequence length ≥ 3;
- the operation is mostly deterministic;
- the sequence appears across ≥ 2 scenario families;
- failure/cost evidence suggests the abstraction is useful.

"Do not create a tool solely because a sequence is frequent. Require a concrete expected benefit." (SPEC §61) Tool evolution is further gated by the MCP validation pipeline (§4.6) and capability rules (§4.2).

### 4.16 Storage Layout and Run Manifest (SPEC §53–54)

v0.1 uses **filesystem + SQLite**; no external databases (SPEC §53).

```
runs/run-id/
├── manifest.json
├── trajectory.jsonl
├── initial-state.json
├── final-state.json
└── verification.json

generations/000/, 001/, …
mutations/
```

SQLite indexes: runs, tasks, packages, generations, mutations, diagnoses, evaluations (SPEC §53). **Run manifest (SPEC §54):** every run records enough to reproduce it — `task_id`, `task_hash`, `package_id`, `package_hash`, `domain_version`, `world_snapshot_hash`, `runtime {name, version}`, `model {provider, identifier}`, `seed`. Model information is recorded for reproducibility even though the model is not the optimization target (SPEC §54).

### 4.17 Observability (SPEC §55)

Every optimization report exposes: generation; validation success; train success; tool calls; latency; token usage; package size; accepted mutation; affected failure cluster; new passes; new regressions (SPEC §55). Example report shape (SPEC §55): per-generation validation deltas (`success 81% → 89%`, `tool calls 13.2 → 8.1`, `violations 0 → 0`), the accepted mutation (`CREATE_TOOL safe_patch_page`), evidence (e.g. 14 concurrency-related failures), and regression deltas (`+9 passing, −1 failing`).

### 4.18 Safety Model, Overfitting Controls, Test Split Policy (SPEC §62–64)

**Safety model (verbatim prohibitions, SPEC §62):** "The optimizer itself is potentially adversarial to the benchmark if unconstrained." Explicitly prevent:

- reading verifier source at runtime;
- reading expected final state;
- reading hidden task metadata;
- direct database access;
- modifying initial snapshots;
- modifying raw APIs;
- network access outside allowed systems;
- writing outside AgentPackage;
- persisting state between tasks unless allowed.

"Each package evaluation runs in a fresh world." (SPEC §62)

**Overfitting controls (SPEC §63):** (1) held-out validation; (2) hidden test split; (3) scenario-level splitting; (4) mutation complexity penalties; (5) package-size metrics; (6) regression attribution; (7) task regeneration with new seeds; (8) periodic evaluation on unseen scenario combinations. "A candidate must not access validation or test ground truth." (SPEC §63)

**Test split policy (SPEC §64):** during optimization — train: full trajectory, full verifier feedback; validation: task outcome; assertion-level feedback may be available to the acceptance system **but not** the mutation solver by default; test: completely inaccessible. Optional stricter mode: solver receives only aggregate validation score. (SPEC §64)

### 4.19 Determinism and Evaluation Statistics (SPEC §65–66)

"Perfect reproducibility is impossible with probabilistic models, but environmental reproducibility is mandatory." (SPEC §65) Pin: world snapshot, task seed, package version, API implementation, verifier version, runtime configuration, model identifier (SPEC §65). Run multiple epochs for important evaluations (SPEC §65). Per-package statistics (SPEC §66): success rate; pass@1; consistency across repeated runs; average wall time; average tool calls; average tokens; policy violation rate; collateral modification rate; package complexity. Later: `pass^k` for consistency-sensitive evaluation (SPEC §66).

### 4.20 Runtime-Failure Taxonomy — Infrastructure vs. Package Failures (SPEC §31, §67)

Do not encode every unsuccessful run as FAIL (SPEC §31). `RunStatus`: `PASS`, `TASK_FAIL`, `PARTIAL`, `AGENT_ERROR`, `TOOL_ERROR`, `ENVIRONMENT_ERROR`, `VERIFIER_ERROR`, `TIMEOUT`, `BUDGET_EXCEEDED`, `POLICY_VIOLATION` (SPEC §31). Only genuine task execution results influence task-performance optimization; infrastructure failures are tracked separately (SPEC §31). Classification guidance (SPEC §67):

- HTTP simulator crashes → `ENVIRONMENT_ERROR`;
- generated MCP throws exception → `TOOL_ERROR`;
- agent selects wrong page → `TASK_FAIL`;
- agent hits wall-time limit → `TIMEOUT`.

Optimization datasets must filter or separately handle infrastructure failures (SPEC §67); never attribute environmental failures to the package (SPEC §67).

### 4.21 Reference Solver Design (SPEC §68)

v0.1 implements a simple **LLM-powered reflective solver**. Inputs: current package summary, failure cluster, representative failed trajectories, representative successful trajectories, validation metrics, rejected mutation memory, mutation budget (SPEC §68). Output: structured JSON `{diagnosis: {layer, summary}, mutation: {operation, path, content}}`; schema validation is required (SPEC §68). The solver consumes structured evidence, not raw logs alone (SPEC §37), and never accesses hidden test tasks (SPEC §75).

### 4.22 Future Optimizer Adapters (SPEC §69)

The core Gym must not depend on a particular optimizer (SPEC §69). Designed-for futures: GEPA-style reflective search, evolutionary search, MCTS workflow search, Bayesian optimization, human-designed mutations, RL controller (SPEC §69). The `Solver`/`Optimizer` protocol split (§4.9, §4.14) is the extension seam.

### 4.23 Python Protocol Summary (SPEC §70)

The core conceptual API surface is defined by protocols in SPEC §70: `Domain.sample_tasks(split, count) → list[Task]`, `WorldFactory.create(task) → World`, `RuntimeAdapter.run(task, package, world) → RuntimeResult`, `Verifier.verify(task, initial, final, trajectory) → VerificationResult`, `Solver.diagnose/propose`, `Optimizer.optimize(domain, package) → AgentPackage`. Reference repository layout in §7; dependency recommendations (Python 3.12, Pydantic, Typer, FastAPI, httpx, pytest, Docker/Docker Compose, SQLite, structlog, PyYAML, MCP SDK isolated behind an internal adapter) in SPEC §71.

### 4.24 Development Phases and Success Criteria

Phased build order is defined in SPEC §72 (Core models → static Confluence world → tasks + verifiers → baseline package at 30–60% success → rollout infra → skill/knowledge evolution → MCP evolution → generalization experiment) and SPEC §76 (simulator first; optimization last). PoC success criteria (SPEC §73) and the stretch goal of emergent abstraction (`edit_deployment_section_safely` → `safe_patch_page`, SPEC §74) constrain what the architecture must be able to demonstrate. Phase acceptance gates are enumerated in SPEC §72.

---

## 5. Architecture Invariants (SPEC §75)

These invariants are specified to **be encoded in tests** (SPEC §75). Verbatim:

```
TASK
does not know the package implementation.

AGENT PACKAGE
does not know verifier internals.

SOLVER
does not access hidden test tasks.

MCP TOOL
does not bypass raw system APIs.

VERIFIER
does not trust agent self-report.

WORLD
can be reset to a known state.

GENERATION
is immutable after acceptance.

MUTATION
always has explicit lineage and evidence.

OPTIMIZER
cannot silently modify the world or task distribution.
```

---

## 6. Open Questions (Phase 1 Research Topics)

The following are deliberately **not resolved** in this document. They are Phase 1 research topics to be investigated during implementation:

- **Execution host without Docker availability.** The v0.1 initial execution model is local Docker-based (SPEC header), and generated MCP code must operate in an isolated container (SPEC §21). Whether a viable fallback isolation host exists (and what security properties it would need to preserve §21 prohibitions and §62 safety prohibitions) is an open research topic.
- **LLM provider for the reference runtime agent and the reflective solver.** The spec pins *model identifier* in the run manifest for reproducibility (SPEC §54) and ships one reference runtime (generic tool-calling loop, SPEC §23) plus an LLM-powered reflective solver (SPEC §68), but does not mandate a specific provider/model. Provider selection, cost, and determinism implications are open research topics.
- **World provider default: process vs. docker.** `DomainSpec.world_provider` is a declared field (SPEC §8.1, example value `docker`), and v0.1 targets Docker-based execution (SPEC header), but the default process-vs-Docker choice per domain — and the isolation/snapshot trade-offs of each — is an open research topic.

These items intentionally do not restate requirements from SPEC.md; they are open decisions for the implementation phase.
