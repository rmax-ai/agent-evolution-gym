# Dev-1 Core models — verification review

Review target: merged `#[Dev-1] Core models` work on `main` (`5524288` through
`da5da30`). This is a review only; no production files were modified.

## Overall verdict: ISSUE — high

The field shapes and stated enum values largely match the Phase 1 contracts, and the
current suite, Ruff, and type check all pass (21 tests). However, persisted package
hashes cannot detect tampering during normal load, and `Generation` is not actually
immutable beyond direct attribute assignment. Those conflict with the integrity and
lineage roles those artifacts serve. JSON persistence also remains safe only for
already-JSON-compatible dictionary values, despite the public `Any` payload types.

## Domain, task, world, and capability models: OK (minor issue)

`DomainSpec`, `Task`, `WorldSnapshot`, and `Capability` have the exact required fields
and primitive/container types from SPEC §§8.1, 9, 12, and 14. `DomainSpec.from_yaml`
uses `safe_load`; their ordinary JSON round trips are covered.

- **LOW — `AgentPackage.parent_id` has a non-SPEC default.** SPEC §15 declares
  `parent_id: str | None` without a default, making an explicit `null` part of every
  persisted manifest. The implementation uses `parent_id: str | None = None`. That
  silently accepts a missing lineage field and weakens a useful persistence contract.
  Make it required-but-nullable, or explicitly amend the SPEC/contract decision.

## Rollout, trajectory, and verification: ISSUE (medium)

`Rollout`, `RolloutMetrics`, `VerificationResult`, `AssertionResult`, and `RunStatus`
otherwise match SPEC §§26–28 and §31. `RunStatus` values are verbatim. The observable
event taxonomy is complete.

- **MEDIUM — `TrajectoryEvent.type` is closed where the SPEC makes it a string.**
  SPEC §25 specifies `type: str` and supplies a *minimum* taxonomy. Replacing that
  field with `TrajectoryEventType` rejects additional domain/runtime observable events,
  so later consumers cannot persist an extension without first changing this core enum.
  Keep the field `str` and validate/offer the standard values separately, or document
  that the taxonomy is intentionally closed.

- **MEDIUM — JSON conversion is not a clean model round trip for `object | None`.**
  `AssertionResult` serializes unsupported observed values with `str()`. Thus a
  `date`, `Decimal`, or arbitrary object loads back as a string, not the original value;
  an `AssertionResult` containing it is not equal after
  `model_validate(model_dump(mode="json"))`. The test checks only that dumping works.
  SPEC §28 allows `object | None`, while Phase 1 requires persisted models to round
  trip cleanly (§72). Define the persisted observed-value domain as JSON values and
  normalize on validation as well, or state and test the intentional lossy boundary.

## AgentPackage persistence, hashes, and capabilities: ISSUE (high)

The directory layout, artifact models, YAML serialization, path escape prevention, and
basic declared-ID subset check are useful starts and align structurally with SPEC
§§15–18. The following prevent treating the resulting hashes/validation as an integrity
or security boundary.

- **HIGH — `from_directory` erases evidence of an on-disk hash mismatch.** It parses
  the manifest and immediately calls `_set_hashes`, which replaces every persisted
  `sha256` with digests of the current files. A modified knowledge, skill, or MCP file
  loads successfully; calling `verify_hashes` on that loaded object then necessarily
  passes. This makes manifest hashes ineffective for detecting a package changed after
  persistence, contrary to the integrity purpose of the `sha256` fields in SPEC
  §§15–18. Compare persisted and computed hashes before replacement and reject (or
  explicitly report) mismatches. If refresh-on-load is desired, make it a separately
  named operation.

- **HIGH — a tool-directory digest does not bind the directory representation.**
  `_sha256_path` concatenates file contents in sorted order but omits each relative
  filename, type, and delimiter. Different file layouts/content partitions can have the
  same digest; a rename alone is invisible even though Python/MCP imports and runtime
  behavior may change. Hash a canonical sequence of relative path + separator + file
  bytes (and decide how symlinks/executable mode are represented). Add collision-style
  tests for rename and boundary ambiguity.

- **MEDIUM — artifact paths are not confined to their declared layer.** A
  `KnowledgeArtifact(path="mcp/server.py", ...)`, a skill pointing into `knowledge/`,
  `ToolPackage(root=".")`, and `server_entrypoint="package.yaml"` all pass model
  validation; the resolver only prevents leaving the package root. This defeats the
  `knowledge/`, `skills/`, and `mcp/` directory representation required by SPEC §15
  and can produce misleading manifests/hashes. Require relative paths beneath their
  respective directories and require the tool root to be `mcp` (or a declared child).

- **HIGH — capability validation is advisory and only checks manifest labels.** The
  subset check correctly rejects a declared ID absent from the passed domain list, but
  `domain` is optional on `load`/`save`, validation is not tied to construction or
  execution, and it cannot establish that MCP source actually uses only the declared
  capabilities. An author can omit a capability from `declared_capabilities`, call
  `save()`/`load()` without a domain, and invoke a raw API in tool code. SPEC §14 says
  tools may only use the granted capabilities; SPEC §21 requires the capability proxy
  that enforces that at execution. Ensure runner/package lifecycle always supplies the
  task's explicit capability set and implement proxy-side enforcement before treating
  this check as a boundary. Add tests proving an undeclared raw API call is denied at
  the proxy (the static manifest check alone cannot prove it).

## Mutation, diagnosis, and generation: ISSUE (high)

`Mutation`, `MutationBudget`, `ToolMutationType`, `Diagnosis`, and the valid diagnosis
layer values faithfully match SPEC §§20, 33, 35, and 36. Budget defaults and taxonomy
values are tested.

- **HIGH — `Generation` is only shallowly frozen.** `ConfigDict(frozen=True)` blocks
  `generation.package_id = ...`, but `generation.mutation_ids.append(...)` and
  `generation.train_metrics[...] = ...` both succeed. That permits mutation of an
  accepted generation's lineage and metrics, violating the immutable accepted package
  state required by SPEC §45. Use immutable nested representations (for example tuples
  and an immutable mapping/frozen JSON representation), or make defensive deep copies
  and expose no mutable containers. Test nested mutation attempts, not only assignment.

## JSON round-trip and Phase 1 coverage: ISSUE (medium)

- **MEDIUM — all `dict[str, Any]` persisted payloads accept values they cannot
  serialize.** `Task.metadata` and `TrajectoryEvent.payload` (likewise snapshot
  resources, package metadata, verification metadata, and generation metric maps) fail
  `model_dump(mode="json")` for `object()`. Existing tests only use JSON-safe values.
  Either constrain persisted values to a recursive JSON-value type and validate it, or
  apply one documented normalizer consistently to every persisted dict field. This is
  required to substantiate §72's “all persisted models round-trip cleanly” acceptance.

- **MEDIUM — Phase 1 tests do not exercise failure/tamper paths.** Add unit coverage
  for manifest hash mismatch on load, canonical directory-hash behavior, cross-layer
  paths, required parent lineage, arbitrary/non-JSON dict payload handling, lossy
  observed-value policy, and deep generation immutability. Current happy-path tests do
  establish nominal shapes, not these contract guarantees.

## Recommended fast follow-up story

1. Make persisted-value handling explicit: introduce a recursive JSON value type (or a
   single normalizer), apply it to all persisted dictionaries and observed values, and
   specify/test whether lossy values are rejected or canonicalized.
2. Repair package integrity: canonical path-aware tree hashing; load-time comparison of
   stored versus computed digests; strict layer-relative path validation; tamper tests.
3. Make `Generation` deeply immutable and test all nested containers.
4. Define capability enforcement ownership: require task/domain capabilities at the
   runner boundary and implement the §21 proxy denial test. Keep the package's subset
   check as defense in depth, not authorization.
5. Resolve the two contract choices: required `parent_id` and open versus closed
   trajectory event types; update the implementation/tests (or SPEC) accordingly.

