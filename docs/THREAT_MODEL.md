# Agent Evolution Gym — Threat Model

**Version:** v0.1 (companion document)
**Source of truth:** `SPEC.md`. All references (`SPEC §N`) point to numbered sections of SPEC.md. Companion to `docs/ARCHITECTURE.md`.
**Framing principle (SPEC §62):** "The optimizer itself is potentially adversarial to the benchmark if unconstrained." This document treats every trainable or runtime component — generated MCP tool code, the reference agent, the solver, the optimizer — as a potential attacker inside the gym, and analyzes the controls the specification places against them.

**Threat actors considered:**

| Actor | Trainable? | Position |
|---|---|---|
| Generated MCP tool code | Yes — evolves (§15–20) | Runs inside sandbox container, behind capability proxy (§21) |
| Reference runtime agent (LLM) | No — fixed runtime (§23) | Consumes package, calls tools, reads world content |
| Reflective solver | No (v0.1 solver is a tool, not the evolved object) — proposes all mutations (§32, §68) | Runs outside sandbox, reads rollouts/evidence |
| Optimizer loop | No — coordinates generations (§48–49) | Drives train/validation scheduling, acceptance (§40–41) |
| Domain content (page text) | No — fixed world | Data the agent reads; potential injection source (§13) |
| Human operator | — | Runs CLI/experiments (§52) |

**Assets at risk (ranked by importance to the benchmark's validity):**

1. Hidden ground truth: verifier source, expected final states, hidden task metadata, test/validation splits, optimizer state (§21, §62, §63).
2. Benchmark integrity: ability of acceptance decisions and research conclusions to reflect real generalization (§3.6, §62–64, §79).
3. Capability boundary: raw system APIs and permissions must be untouched by evolution (§3.2, §14).
4. World state integrity: unrelated simulated state, concurrent human edits, invariants (§3.4, §30, §44).
5. Artifact quality: package complexity, maintainability, auditability (§36, §43, §45).
6. Reproducibility: run manifests, snapshots, hashes (§54, §65).
7. Host infrastructure outside the gym (out of scope for v0.1 hardening; v0.1 is not a production system, SPEC §4).

**Baseline invariants assumed everywhere below (SPEC §75, encoded in tests):** TASK does not know the package implementation; AGENT PACKAGE does not know verifier internals; SOLVER does not access hidden test tasks; MCP TOOL does not bypass raw system APIs; VERIFIER does not trust agent self-report; WORLD can be reset to a known state; GENERATION is immutable after acceptance; MUTATION always has explicit lineage and evidence; OPTIMIZER cannot silently modify the world or task distribution.

---

## T1 — Generated MCP tool escapes its isolation

**References:** SPEC §21, §22, §25, §35, §62, §75 (MCP TOOL does not bypass raw system APIs).

| Field | Content |
|---|---|
| **Attack path** | Solver proposes `CREATE_TOOL`/`EDIT_TOOL` (SPEC §20) with arbitrary Python. Tool code, once running in its container, attempts to reach resources the spec denies: verifier, task ground truth, underlying database, task fixtures, host filesystem, Docker socket, package history, test split, optimizer state (§21); or attempts network egress beyond the declared world API gateway (§21). |
| **Asset at risk** | Hidden ground truth (assets 1–2); benchmark integrity; host infrastructure. |
| **Security boundary** | Container isolating generated MCP code from runtime/host; capability proxy interposed between the generated MCP server and the World API Gateway; network limited to the declared world API gateway (§21). Architecture: `Agent Runtime → Generated MCP server → capability proxy → World API Gateway → Simulated enterprise APIs` (§21). |
| **Preventive controls** | Hard isolation rule: "Generated MCP code must operate in an isolated container" (§21); verbatim deny-list of what generated code "must not directly access" (§21, see ARCHITECTURE §4.5); egress restricted to the gateway (§21); MCP validation pipeline stages 1–9 (parse, formatting, static typing, linting, tool-schema validation, capability validation, unit tests, contract tests, sandbox startup) — failure immediately rejects the candidate, so hostile code should not reach evaluation (§22); each package evaluation runs in a fresh world (§62). |
| **Detective controls** | Pipeline stage 9 sandbox startup + stage 10 smoke task exercise the code before trust (§22); trajectory events `tool.call`/`tool.result`/`tool.error` and `world.api.*` record every observable interaction (§25); every mutation is an explicit diff with evidence refs, enabling source review (§35); package/tool hashes recorded (§18, §54). |
| **Recovery controls** | Reject candidate (stages 1–9 immediate rejection, §22); discard container; restore world from snapshot (§11–12); log to rejected-mutation memory so the strategy is not repeated (§46). |
| **Residual risk** | Container/kernel escape and dependency supply-chain attacks against the MCP SDK stack (SPEC §71) are outside v0.1 hardening scope (not a production system, §4). Accepted for v0.1 given the simulated world and disposable containers. |

---

## T2 — Tool privilege escalation beyond declared capabilities

**References:** SPEC §14, §18, §21, §22 (stage 6), §31 (POLICY_VIOLATION), §75.

| Field | Content |
|---|---|
| **Attack path** | A mutated tool calls operations not in its `declared_capabilities` (SPEC §18) — e.g., reaching an unlisted API endpoint directly, chaining listed calls into an unauthorized effect, or declaring capabilities that its code does not actually honor. Privilege escalation could target state the task's capability set does not include (§14). |
| **Asset at risk** | Capability boundary and permissions model (asset 3); unrelated world resources. |
| **Security boundary** | The capability proxy between the generated MCP server and the World API Gateway (§21) is the enforcement point; `Capability(system, operation)` is the unit of grant (§14); per-task capability set is explicit (§14). |
| **Preventive controls** | Capability rule: "The Agent Package may only build MCP tools using those capabilities." / "An evolved tool must never gain new privileges." (§14); validation pipeline stage 6 capability validation checks the tool against declared capabilities before it may proceed (§22); stage 5 tool-schema validation constrains the tool's contract (§22); raw APIs expose no convenience back-doors — "The simulator represents the underlying system, not the desired solution" (§13). |
| **Detective controls** | Contract tests (stage 8) and smoke task (stage 10) exercise behavior under capability limits (§22); state-diff verification catches any world change outside required/forbidden sets (§30); out-of-bounds capability use surfaces as `POLICY_VIOLATION` (§31); forbidden-changes assertions report it (§28). |
| **Recovery controls** | Reject candidate; revert to the immutable parent generation (§45); record rejection with regressions (§46); rerun affected tasks from snapshots. |
| **Residual risk** | Proxy logic bugs / TOCTOU between static capability validation and runtime; mitigated by deterministic re-validation in fresh worlds (§62) and by verifier checks on actual world deltas (§30). Residual risk is low but non-zero because the proxy is v0.1 code. |

---

## T3 — Solver or agent reads verifier source, expected final state, hidden task metadata, or test split

**References:** SPEC §9, §21, §62, §63, §64, §75 (SOLVER / AGENT PACKAGE / MCP TOOL invariants).

| Field | Content |
|---|---|
| **Attack path** | (a) Agent obtains ground truth through tool results or world content (e.g., fixtures accidentally served by the API); (b) generated MCP code directly reads verifier files, task fixtures, or split files; (c) solver reads hidden task definitions, expected states, or test-split ground truth during optimization; (d) agent infers hidden metadata from leaked error messages or page artifacts. |
| **Asset at risk** | Hidden ground truth and split integrity (assets 1–2) — the validity of every generalization claim (§3.6, §63). |
| **Security boundary** | Container deny-list (§21); train/validation/test split policy (§64); solver evidence packaging (§37); storage separation between run artifacts, packages, and splits (§53). |
| **Preventive controls** | Verbatim prohibitions: generated MCP code must not access verifier, task ground truth, underlying database, task fixtures, package history, test split, optimizer state; network limited to the world API gateway (§21); optimizer safety list: no reading verifier source at runtime, expected final state, or hidden task metadata (§62); task prompts "must not expose verifier implementation details" (§9); hidden task definitions and verifiers are part of the fixed substrate the optimizer may not modify or read into the package (§3.2); split policy: test is "completely inaccessible", and assertion-level feedback is withheld from the mutation solver by default (§64); invariant: AGENT PACKAGE does not know verifier internals, SOLVER does not access hidden test tasks (§75). |
| **Detective controls** | Trajectory recording at observable boundaries makes any access attempt visible (§25); mutation diffs are explicit and evidence-linked for review (§35); run manifests and hashes make artifact provenance auditable (§54); validation-vs-train gap monitoring (overfitting controls, §63). |
| **Recovery controls** | Reject candidate; quarantine/revoke leaked artifacts; regenerate task instances with new seeds (§63 item 7); invalidate affected evaluations and rerun. |
| **Residual risk** | Inference side channels (error-message wording, timing, world API behavior revealing expected state) are hard to fully eliminate; the design counters with scenario-level splits and task regeneration (§3.6, §63). Residual model-level leakage is acknowledged and bounded, not assumed zero. |

---

## T4 — Optimizer games the benchmark (reward hacking via package mutations)

**References:** SPEC §3.6, §36, §41, §43, §44, §62, §63, §64.

| Field | Content |
|---|---|
| **Attack path** | The optimizer improves *training* numbers without real generalization by: encoding task-specific answers/IDs into knowledge or tool logic; specializing artifacts to the validation set's quirks; exploiting verifier blind spots (see T9); accumulating bespoke artifacts so the aggregate looks better while regressions hide; or selecting candidates that pass acceptance by metric gaming rather than behavioral improvement. |
| **Asset at risk** | Benchmark integrity and validity of research conclusions (asset 2); package quality. |
| **Security boundary** | Trainable substrate restricted to `knowledge/`, `skills/`, `mcp/` (§3.2); acceptance policy gate (§41); split policy (§64); mutation budget (§36). |
| **Preventive controls** | Held-out validation and hidden test split (§63 items 1–2); scenario-level splitting rather than random near-duplicates (§3.6, §63 item 3); mutation complexity penalties and package-size metrics (§63 items 4–5; §43); regression attribution keeps newly failing tasks visible regardless of aggregate improvement (§44, §63 item 6); task regeneration with new seeds (§63 item 7); periodic evaluation on unseen scenario combinations (§63 item 8); acceptance minimums: validation ≥ baseline, policy violations == 0, collateral damage ≤ baseline, infrastructure errors == 0, plus at least one meaningful improvement (§41); candidates may not access validation/test ground truth (§63); split policy restricts validation feedback to task outcome (assertion-level feedback withheld from solver by default, §64). |
| **Detective controls** | Train-vs-validation gap trending; regression deltas reported per generation (`+newly passing / −newly failing`) (§44, §55); package complexity trend reports (knowledge tokens, skill count, tool count, MCP LOC, dependencies) (§43, §55); consistency statistics across repeated runs and epochs (§65–66). |
| **Recovery controls** | Reject candidate and revert to prior immutable generation (§45); feed rejection into mutation memory (§46); trigger meta-consolidation to remove over-specialized artifacts (§47); if gaming is suspected, regenerate tasks and re-run validation (§63 item 7). |
| **Residual risk** | Sophisticated reward hacking that exploits verifier coverage gaps (T9) or slow accumulation of overfit artifacts between consolidations. Residual by design; the spec's answer is layered controls plus verifier quality (§3.3, §72 Phase 3 oracle testing) rather than a single defense. |

---

## T5 — Prompt injection from world content into the agent or solver

**References:** SPEC §3.3, §13, §25, §37, §57, §62.

| Field | Content |
|---|---|
| **Attack path** | Simulated page text (world content, §13) contains instructions — "ignore your instructions", "reveal the verifier", "modify page X" — that the agent reads via `get_page`/`search_pages` and follows. Injected content can also enter solver-visible trajectories, and — if the solver consumes raw trajectories rather than structured evidence — could steer solver diagnoses/mutations. |
| **Asset at risk** | Task outcome integrity; capability boundary (if injection induces out-of-capability actions); solver integrity. |
| **Security boundary** | World content is *data*, not control plane: tools are deterministic operations bounded by capabilities (§14), and the capability proxy blocks any escalation (§21). The agent's effective behavior is bounded by package + capabilities; the verifier does not trust agent self-report (§3.3, §29, §75). Solver input boundary: structured evidence, not raw logs alone (§37). |
| **Preventive controls** | Tool layer exposes only realistic read/write semantics, no instruction-execution channel (§13); tools cannot grant new privileges regardless of content (§14); network/isolation limits prevent exfiltration beyond the gateway (§21); solver receives `OptimizationEvidence` (failures, successes, clusters, metrics, rejection memory) rather than raw logs (§37); primary success criteria do not rely on the agent's natural-language claims (§3.3, §29). |
| **Detective controls** | Trajectory review of anomalous tool sequences following content reads (§25); anomalous behavior surfaces as `TASK_FAIL` or `POLICY_VIOLATION` and is clustered for diagnosis (§31, §38); failure clusters referencing injection patterns can be attributed (§44). |
| **Recovery controls** | Evolve knowledge/skills to instruct treating page content as data (the normal package-level fix — §16–17); reject the offending mutation if any; restore world from snapshot and re-run. |
| **Residual risk** | The reference LLM agent may still follow injected instructions — an inherent property of the fixed runtime model (not optimized, §23); mitigation is package-level (skills/knowledge) and bounded by the capability proxy. Residual and accepted for v0.1; world content in the simulated domain is not adversarially authored by an attacker with gym knowledge. |

---

## T6 — State contamination / cross-task leakage

**References:** SPEC §11, §12, §16, §53, §54, §62, §75 (WORLD can be reset to a known state).

| Field | Content |
|---|---|
| **Attack path** | State persists between tasks or evaluations: world container not reset; tool server process holds memory/temp files; knowledge cache or on-disk writes survive; rollouts share a world instance; artifacts from task N influence task N+1 (e.g., leftover pages, env vars, files written outside the AgentPackage). |
| **Asset at risk** | Per-evaluation validity and task independence (assets 1–2); verifier soundness; reproducibility. |
| **Security boundary** | World lifecycle: `start` / `restore(snapshot)` / `snapshot` / `stop` (§11); fresh world per evaluation: "Each package evaluation runs in a fresh world" (§62); per-run storage layout with its own manifest and state files (§53–54). |
| **Preventive controls** | Restore each world from a deterministic snapshot before a task (§11, §12); fresh world per package evaluation (§62); run-scoped directories (`runs/run-id/…`) and hashed manifests prevent artifact confusion (§53–54); v0.1 loads all knowledge directly — no embedding/retrieval index whose state could leak across tasks (§16); persisting state between tasks is prohibited unless allowed (§62). |
| **Detective controls** | State-diff verification compares initial vs. final snapshots across resources, surfacing unexpected residue (§30); rerunning identical manifest reproduces the same outcome (determinism checks, §54, §65); consistency across repeated runs is reported (§66). |
| **Recovery controls** | Reset world from snapshot; tear down and recreate tool containers between runs; rerun the rollout; quarantine the run directory if contamination is confirmed. |
| **Residual risk** | Leakage through components outside the world boundary (e.g., LLM-provider context, shared host caches) is outside gym control; documented in the run manifest's model fields (§54) but not eliminated. |

---

## T7 — Collateral damage to unrelated world state

**References:** SPEC §3.4, §28, §30, §41, §44, §57, §66, §77.

| Field | Content |
|---|---|
| **Attack path** | The agent (or an evolved tool) edits the wrong page, overwrites a concurrent human edit, rewrites an entire document, touches a neighboring page, or a buggy `update_page`/synthesized tool broadens its write scope. Task "succeeds" on the target change while damaging unrelated state. |
| **Asset at risk** | Unrelated simulated world state and concurrent human edits (asset 4); evaluation correctness under the §3.4 verification model. |
| **Security boundary** | Verification model: `required changes + forbidden changes + global invariants = verification result` (§3.4); state-diff over initial vs. final snapshots (§30); capability boundary limits reachable operations (§14). |
| **Preventive controls** | Verifiers assert forbidden changes and resource invariants, not only the desired outcome (§28, §30); acceptance policy requires collateral damage ≤ baseline and treats collateral regressions as rejection grounds (§41); scenario families explicitly exercise preservation (Family C) and concurrency (Family D) (§57); evolved workflows encode "smallest possible patch" and version-preservation behavior (§58, §77); deterministic tooling (`safe_patch_page`-style) reduces risky manual sequences (§19). |
| **Detective controls** | State-diff across the whole resource set, not just the target (§30); `forbidden_changes_passed`/`invariants_passed` flags on every verification result (§28); collateral modification rate is a reported per-package statistic (§66); regression attribution makes collateral damage on validation scenarios visible per mutation (§44). |
| **Recovery controls** | Reject the candidate on collateral regression (§41); restore the world from snapshot (§11–12); record the rejection and its regressions (§46). |
| **Residual risk** | Verifier coverage gaps — collateral damage in resources or invariants the verifier does not assert. This is the fundamental T9 residual; mitigated by the verifier-quality program (§3.3, §72 Phase 3: oracle passes all tasks, deliberately incorrect implementations fail expected assertions). |

---

## T8 — Determinism / reproducibility loss

**References:** SPEC §10, §12, §54, §65, §66, §67, §75 (WORLD can be reset).

| Field | Content |
|---|---|
| **Attack path** | Non-determinism creeps in: unseeded scenario generation; world restore not bit-identical (timestamps, ordering, auto-increment IDs); API implementation drift between runs; unpinned verifier/runtime/model versions; wall-clock-dependent logic; shared-state races across concurrent runs touching the same SQLite store or snapshot files. |
| **Asset at risk** | Reproducibility and auditability (asset 6); scientific validity of attribution — if noise dominates, "regression attribution" (SPEC §44) is meaningless. |
| **Security boundary** | Environmental reproducibility boundary: everything environmental is pinned; only model sampling noise is tolerated (§65). |
| **Preventive controls** | `ScenarioGenerator.generate(seed)` makes task generation seed-driven (§10); snapshots are persisted, restorable JSON state (§12); pins: world snapshot, task seed, package version, API implementation, verifier version, runtime configuration, model identifier (§65); run manifest records `task_hash`, `package_hash`, `domain_version`, `world_snapshot_hash`, runtime name/version, model provider/identifier, seed (§54); sha256 on knowledge artifacts and tool packages (§16, §18); run multiple epochs for important evaluations (§65). |
| **Detective controls** | Evaluation statistics include consistency across repeated runs and pass@1 (§66); re-executing a stored manifest should reproduce its outcome — drift is detectable by comparing rerun results; infrastructure failures are classified separately from package results so noise does not pollute optimization data (§31, §67). |
| **Recovery controls** | Re-run from the manifest; restore the pinned snapshot; pin/roll back drifted components; quarantine runs that fail reproducibility checks. |
| **Residual risk** | "Perfect reproducibility is impossible with probabilistic models" (§65) — LLM sampling variance is irreducible and is handled statistically (epochs, consistency metrics, §65–66), not by attempting to eliminate it. |

---

## T9 — Verifier blind spots (agent self-report, unvalidated answer artifacts)

**References:** SPEC §3.3, §3.4, §9, §28, §29, §30, §72 (Phase 3), §75 (VERIFIER does not trust agent self-report).

| Field | Content |
|---|---|
| **Attack path** | The agent finishes without performing the required world change and claims success in natural language; the verifier (if it keyed on the agent's final answer) would pass it. Relatedly: verifier assertions cover only the target resource, or only "required changes", so false claims and missed side effects pass; assertion design gaps become reward-hacking surface for the optimizer (T4). |
| **Asset at risk** | Correctness of acceptance decisions; benchmark integrity (asset 2). |
| **Security boundary** | Verification is external to the agent and deterministic; the verifier evaluates world state and state deltas, not the agent's claims (§3.3, §29). |
| **Preventive controls** | Verification preferentially uses (1) final world state, (2) state differences, (3) deterministic assertions, (4) generated artifact validation, (5) policy/invariant checks; "LLM grading should not be required for primary success criteria" (§3.3); "The verifier should not depend on the agent's natural-language final answer unless the task intrinsically requires an answer artifact" (§29); state-diff checks required changes + forbidden changes + invariants (§3.4, §30); invariant: VERIFIER does not trust agent self-report (§75); task goals are stated as state transitions, and prompts do not expose verifier details (§9); verifier ids/versions are per-task and pinned (§9, §65). |
| **Detective controls** | Per-assertion results (`AssertionResult` id/category/expected/actual) are persisted on every verification (§28); verifier QA per §72 Phase 3 — a known-good oracle passes all generated tasks and deliberately incorrect implementations fail expected assertions; audit trail (trajectory + final state + verification result) allows post-hoc review of any decision (§53). |
| **Recovery controls** | Fix the verifier assertion; mark affected evaluations invalid; re-run the affected tasks; treat verifier defects as infrastructure issues (`VERIFIER_ERROR`, §31) rather than package results. |
| **Residual risk** | Verifier coverage is limited by assertion design — a fundamental limit of the §3.4 model. Residual risk is accepted and bounded by the verifier-quality program; the architecture never compensates by trusting agent reports. |

---

## T10 — Mutation budget bypass / unbounded package growth

**References:** SPEC §36, §41, §43, §45, §46, §47, §55, §79 (RQ6).

| Field | Content |
|---|---|
| **Attack path** | The solver defeats per-step budget limits (§36) through accumulation: many small in-budget edits that collectively bloat the package; one bespoke tool/skill per scenario family (memorization via artifacts); duplicated knowledge and overlapping skills left behind; consolidation skipped or deferred so complexity compounds over generations. |
| **Asset at risk** | Package quality and complexity (asset 5); generalization (over-specialized artifacts memorize rather than transfer, §74); cost/latency as package size grows (§2, §43). |
| **Security boundary** | Per-mutation budget: `max_files_changed: 3`, `max_added_lines: 200`, `max_deleted_lines: 200`, `max_new_tools: 1`, `max_new_skills: 1` — "Candidates exceeding the budget are rejected" (§36); complexity metrics tracked per package (§43); consolidation every N = 5 accepted generations (§47). |
| **Preventive controls** | Budget enforced as a hard rejection gate at proposal/validation time (§36, §40); the optimizer is "discouraged from solving every case through bespoke artifacts" via tracked complexity metrics — knowledge_tokens, skill_tokens, skill_count, tool_count, MCP source LOC, MCP dependencies, average exposed tools per task (§43); package complexity is one of the acceptable "meaningful improvement" axes, so *reducing* complexity can justify acceptance (§41); meta-consolidation every 5 generations with allowed operations remove/merge/generalize/simplify, each passing the same validation suite (§47); every mutation carries explicit rationale and evidence, making repeated same-target edits auditable (§3.7, §35). |
| **Detective controls** | Per-generation observability includes package size (§55); complexity trend across generations flags monotonic growth; regression attribution and lineage make accumulation patterns visible (§44–45); rejected-mutation memory prevents re-proposing known-bad strategies (§46). |
| **Recovery controls** | Run a consolidation generation (remove/merge/generalize/simplify, §47); revert to an earlier immutable generation if growth harmed validation (§45); tighten budget or lower complexity thresholds in the optimizer config (§50, §51). |
| **Residual risk** | Complexity can still grow between consolidations, and consolidation itself may regress (it must pass the same validation suite, §47). Whether the loop produces simpler *and* more general solutions over time is an open research question (RQ6, §79), not an assumed property. |

---

## Summary of residual-risk posture

- **Accepted, bounded residuals:** verifier coverage gaps (T7/T9), LLM injection susceptibility (T5), container-escape sophistication (T1), model sampling nondeterminism (T8), accumulation between consolidations (T10).
- **Controlled by construction:** capability escalation (T2), ground-truth access (T3), cross-task leakage (T6) — the spec's controls here are prohibitions plus enforced boundaries (§14, §21, §62, §75), not monitoring.
- **The load-bearing assumption:** the verifier is external, deterministic, and state-based (§3.3, §28–30). Every other control inherits its soundness; verifier QA (SPEC §72 Phase 3) is therefore a security control, not just a functional one.
