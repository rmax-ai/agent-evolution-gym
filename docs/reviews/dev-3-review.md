# Dev-3 review — task generators and verifiers

Reviewed merged `main` at `0296a04`. This is a review only; no implementation
changes were made. Focus is SPEC v0.1 §§3.3–3.6, 9–10, 28–30, 64–65, 72, and
75.

## Verdicts

| Area | Verdict | Notes |
| --- | --- | --- |
| Task model / generator fidelity (§§9–10) | **ISSUE — high** | The persisted `Task` fields exist and generation is seeded, but every generated task says `split="train"`, including validation/test instances. The full task metadata contains verifier-private oracle data, with no runtime projection boundary. |
| Split policy (§§3.6, §64) | **ISSUE — high** | Permissions is structurally held out and manifest seed values currently do not overlap, but this is neither represented on generated tasks nor enforced by `SplitSpec`/a curriculum loader. |
| Verifier semantics (§§3.3, 28–30) | **ISSUE — high** | The verifier is external and ignores trajectory/self-report, and unknown families fail loud. However preservation semantics and retrieval success are substantially under-verified. |
| State diff / predicates (§30) | **ISSUE — medium** | Generic create/delete/update and version deltas are deterministic and copied, but page-version history is not covered by page-task invariants or direct tests. |
| Determinism / snapshot staging (§65) | **ISSUE — medium** | Local `Random(seed)`, sorted diff output, fixed scenario timestamp, and sorted JSON are good. Default shared snapshot paths and relative-reference ambiguity are unsafe for concurrent/run-scoped callers. |
| Phase 3 oracle tests (§72) | **ISSUE — medium** | Good representative happy-path/adversarial coverage, but it does not prove a known-good oracle over every generated split task nor test several material negative paths. |
| Dev-4/5 integration surface | **ISSUE — high** | No runner/curriculum implementation currently defines split injection, private verifier config, run snapshot roots, concurrency injection, or domain-relative module resolution. |

## Findings

### 1. Generated tasks lose their actual split; verifier oracle is carried in agent-facing `Task.metadata`

`ConfluenceScenario._task()` always constructs `Task(split="train")`. Thus a
task expanded from `validation.yaml` or `test.yaml` will be mislabeled unless a
future caller mutates an otherwise persisted task. This weakens both the split
contract in §9 and the solver/test isolation required by §§3.6 and 64.

The same method serializes `verifier_config` into `Task.metadata`. It includes
the exact target page ID and required fragment; preservation adds forbidden IDs;
concurrency supplies the injected human body; permissions exposes `mode`. §9
only forbids exposure in the task prompt, but §75 requires the package not to
know verifier internals. There is no runner/runtime contract in the current
tree that projects an internal evaluation task into an agent-safe task view.
Passing `Task` wholesale to a runtime would make this a direct ground-truth
leak—not merely a theoretical one. Existing goal-leak tests inspect `goal`
only and therefore do not establish the required boundary.

**Follow-up:** make split a generator/curriculum input or stamp it when
materializing the task, while retaining a validated immutable evaluation
record. Keep verifier configuration in private evaluation state (or introduce
an explicit agent-facing task DTO containing only goal, actor identity, and
allowed execution context). Add an integration test that a runtime cannot read
the private fields.

### 2. The manifests make a sensible structural split, but enforcement is absent

`permissions` occurs only in test, while retrieval/edit/preservation/concurrency
are train+validation; this is a reasonable held-out family per §3.6. The listed
seed ranges are currently disjoint (1000–1304, 2000–2302, 3000–3004).

`SplitSpec` validates only duplicate explicit seeds within one entry. It does
not reject repeated seeds across entries, and there is no cross-manifest
validation or test-access guard. More importantly, `SplitSpec.iter_seeded()`
only yields `(scenario_id, seed)`, so it cannot repair the incorrect `Task.split`
field or convey a snapshot root. A future optimizer can therefore accidentally
materialize test entries through the normal train pathway.

**Follow-up:** add domain-level split validation (unique `(scenario_id, seed)`
allocations and policy checks) and a curriculum materializer that passes split
and an internal run ID into generation. Keep test loading inaccessible to the
mutation solver, as §64 requires.

### 3. Preservation scenarios do not verify preservation of the target page

For `preservation`, `_verify_preservation()` adds immutability checks only for
other pages. `_verify_edit()` checks that the target body *contains* the desired
fragment and that its version is exactly `+1`; it does not compare the target's
unrelated sections, headings, formatting, title, owner, or other fields. A
single update replacing the whole target body with the requested fragment will
pass every assertion, including `section_only`, `formatting_intact`, and
`append_without_rewrite`. This contradicts the stated goals and §3.4/§30's
required side-effect and invariant evaluation.

**Follow-up:** generators should record target-page preservation fragments or a
section-level expected body transformation privately; verifier assertions must
check those fields/fragments survive. Add deliberate overwrite/reformatting
oracles that fail the relevant invariant assertions.

### 4. Retrieval (and denied-read) currently rewards a no-op, not retrieval

The retrieval verifier accepts only `initial.resources == final.resources`.
This properly prevents mutation, but proves neither that the agent located the
right page nor that it read current guidance. A runtime that does nothing passes
all retrieval tasks. Denied-read has the same state-only no-op pass condition.
§29 permits an answer artifact when the task intrinsically requires one; these
goals are intrinsically information-retrieval tasks, yet there is no externally
observable answer artifact or independently observable read event.

No agent self-report is trusted—this is good §3.3 practice—but absence of
self-report must not make the task vacuous.

**Follow-up:** either make retrieval produce a deterministic externally stored
answer artifact and verify it, or verify framework-observed API/audit events
without trusting agent text. Specify what success means for denied-read (for
example a verified policy-safe response artifact) rather than treating no work
as success.

### 5. Page history is outside the task verifier's invariant envelope

`state_diff.compare()` handles `page_versions` as a mapping and will report an
updated history entry. It also uses `deepcopy` for changed values, avoiding
output aliasing. But `PageEditVerifier` only holds users/spaces/permissions
constant; it never validates `page_versions`. Since the raw store appends a
history record on every page write, a malformed world/API that updates current
page content/version without append-only history would still pass. Conversely,
extra or forged history mutations outside current page state are not caught.

**Follow-up:** add page-version assertions matching the expected ordinary
`+1`/concurrent `+2` histories and unchanged histories for untouched pages, or
explicitly document why history is not a task invariant. Add compare/predicate
tests for `page_versions`, nested changes, and output non-aliasing.

### 6. Concurrent `+2` is correctly asserted only if a runner performs the missing event

The ordinary edit assertion is replaced with exact target version `+2` for the
concurrent family, and the human fragment must appear in final state. That is
the intended §30 shape. The staged snapshot deliberately has no human edit;
the intended human edit lives in metadata and the comment says a runner injects
it after first read. There is no runner in the current tree, nor a contract
defining how to observe the first read and inject exactly once. Without it,
real rollouts cannot satisfy the verifier; with metadata exposed, agents can
also see the hidden planned human write.

**Follow-up:** Dev-4 should define and test an explicit, framework-owned
concurrency hook (trigger, timing, one-shot behavior, and final snapshot
capture), with its payload private from the runtime.

### 7. Snapshot paths are deterministic but not run-safe

Fixed timestamps and `json.dumps(sort_keys=True)` make a given generated
snapshot byte-stable. The scenario-specific `Random(seed)` use is also good;
literal/dict iteration affects only stable construction at present, while
forbidden IDs and diffs are sorted.

However the default `experiments/.snapshots` is process-shared and each seed
overwrites `snapshots/<scenario>-<seed>.json`. `initial_snapshot_ref` is
relative to an unspecified root, while the generator writes at
`experiments/.snapshots/snapshots/...`. This invites cross-run collisions,
stale artifacts, and incorrect restore roots in parallel evaluations. The
current tests avoid it by injecting `tmp_path`.

**Follow-up:** require a runner-provided, unique run-scoped snapshot directory
and define whether `initial_snapshot_ref` is relative to that directory or is a
fully resolved persisted artifact reference. Test parallel/equal-seed runs.

### 8. Phase 3 tests are representative, not the acceptance proof

The 46 focused tests pass locally. They cover a happy path for each family,
wrong target/collateral writes, concurrent overwrite, denied-write mutation,
ordinary `+3`, unknown family, and generic trajectory non-trust. This is a
useful base.

It does not execute a known-good oracle against every manifest-generated task
(20 train + 12 validation + 5 test), contrary to §72's "all generated tasks"
acceptance wording. It also lacks direct negative tests for: target-page
wholesale rewrite in preservation; concurrent `+1` and `+3`; allowed/denied
permission mode tampering; retrieval mutation; malformed `page_versions`; and
agent-visible metadata isolation. The "wrong oracle" unit test defines a
deliberately bad verifier rather than exercising deliberately wrong task
implementations across all generated cases.

**Follow-up:** add matrix/oracle tests over all manifest pairs using a shared
trusted action harness, then mutate one requirement at a time and assert the
specific required/forbidden/invariant failure.

### 9. Domain module names require a documented loader prefix

`domain.yaml` lists `scenarios.retrieval` and `verifiers.page_edit`, while
`ScenarioRegistry.from_modules()` calls `importlib.import_module()` directly.
The working imports are `domains.confluence.scenarios.retrieval` and
`domains.confluence.verifiers.page_edit`. No domain loader exists yet to join
the manifest entry with the domain package. Dev-4/5 must not pass manifest
strings straight to the registry or imports will fail.

**Follow-up:** establish one domain-loading convention and cover manifest
scenario/verifier discovery end-to-end. The loader should also own the private
verifier registry and snapshot root described above.

## Positive observations

- Task fields match §9 structurally; registries reject duplicate scenario IDs
  and unknown verifier families fail rather than silently falling through.
- Seeded `Random` instances, fixed scenario timestamps, sorted snapshot JSON,
  sorted diff IDs, and immutable snapshot copies provide a strong deterministic
  base (§65).
- Assertions are categorized as required/forbidden/invariant (§28), and
  `PageEditVerifier.verify()` explicitly discards trajectory input. No current
  assertion trusts an agent natural-language self-report (§3.3, §75).
- Ordinary edits use exact `+1`, concurrent edits use exact `+2`, and unknown
  families/configuration fail loud rather than pass by default.
