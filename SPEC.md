Agent Evolution Gym v0.1
Technical Design Specification
Status: Draft for implementation
Primary language: Python 3.12+
Initial execution model: local Docker-based
Primary interface: CLI + Python SDK
Optimization target: externalized Agent Package
Initial domain: enterprise knowledge/workflow operations
Initial tool protocol: MCP


⸻


1. Executive Summary
Agent Evolution Gym is an environment for automatically developing domain-specialized AI agents through repeated task execution, verification, failure analysis, and controlled modification of the agent's external capability substrate.
The system deliberately does not optimize the underlying language model or agent harness.
Instead, it holds the following relatively fixed:
• task distribution;
• simulated enterprise world;
• raw system APIs;
• permissions;
• verification logic;
• execution runtime.
It evolves an external, deployable AgentPackage composed of:
1. domain knowledge;
2. procedural skills/prompts;
3. workflow-level MCP tools.
The core optimization loop is:
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
The objective is not:
Which model or harness performs best?
The objective is:
Given a fixed domain, task distribution, system APIs, and deterministic verifiers, can an automated solver discover the knowledge, procedural skills, and tool abstractions required to turn a general-purpose agent into a reliable domain-specialized agent?
The Agent Package is the primary trainable artifact.


⸻


2. Product Thesis
Modern enterprise agents usually operate on proprietary foundation models that organizations cannot fine-tune directly.
However, their effective behavior depends heavily on external artifacts:
foundation model
      +
system instructions
      +
domain knowledge
      +
procedural skills
      +
tool definitions
      +
workflow abstractions
      =
operational agent
These external components can be modified, tested, versioned, audited, and deployed independently from the model.
Agent Evolution Gym treats those components as trainable parameters.
Conceptually:
[
P = K + S + T
]
where:
• (P) = Agent Package;
• (K) = knowledge;
• (S) = skills/instructions;
• (T) = tool interface.
The world and task distribution define an optimization problem:
[
P^* = \arg\max_P E_{t \sim D}[V(t,P)]
]
subject to:
• safety constraints;
• capability boundaries;
• complexity limits;
• cost limits;
• generalization requirements.
The result should be a portable package that can be attached to a compatible general-purpose agent runtime.


⸻


3. Core Design Principles
3.1 The environment is fixed; the agent package evolves
Raw enterprise systems are part of the world.
MCP workflow abstractions are part of the agent.
Example:
FIXED WORLD

Confluence API
GET /pages/{id}
PUT /pages/{id}
GET /pages/{id}/versions

────────────────────────────────

EVOLVABLE AGENT PACKAGE

MCP tool:
safe_patch_page(page_id, patch)

internally:
read current page
→ inspect version
→ calculate patch
→ detect conflict
→ merge
→ update
→ verify
The optimizer may improve the interface presented to the agent.
It must never modify the underlying simulated enterprise API.


⸻


3.2 Optimize external capability, not model intelligence
The optimization loop may modify:
knowledge/
skills/
mcp/
It must not modify:
foundation model weights
hidden task definitions
verifiers
raw system APIs
environment state generators
permissions
Model and harness details belong to an execution adapter below the conceptual architecture.


⸻


3.3 Verification must be external to the agent
The agent must not decide whether it succeeded.
Verification should preferentially use:
1. final world state;
2. state differences;
3. deterministic assertions;
4. generated artifact validation;
5. policy/invariant checks.
LLM grading should not be required for primary success criteria.


⸻


3.
4 Evaluate side effects, not only desired outcomes
A task may succeed while damaging unrelated state.
Therefore:
required changes
+
forbidden changes
+
global invariants
=
verification result
Example:
✓ requested page section updated
✓ required fact added
✓ concurrent human change preserved
✗ unrelated page modified

Result: FAIL / collateral damage


⸻


3.5 Train and evaluate on distributions, not individual prompts
A domain consists of scenario generators producing task instances.
Do not optimize against a small static collection of examples.
The fundamental unit should be:
ScenarioFamily
      ↓
TaskGenerator
      ↓
many TaskInstances
Example:
"modify a knowledge page while handling concurrency"

variables:
- existing page structure
- target section
- requested change
- concurrent human modification
- page version
- irrelevant distractor pages
- permission state
This can generate hundreds of semantically related tasks.


⸻


3.6 Held-out generalization is mandatory
Every domain must contain:
train
validation
test
The solver gets rich rollout evidence from training tasks.
Validation tasks determine candidate acceptance.
Test tasks must remain hidden from the solver until final evaluation.
Split by scenario structure where possible, not random near-duplicates.


⸻


3.7 Every optimization step must be attributable
Every candidate package must have:
• parent generation;
• exact mutation;
• motivation;
• supporting failure evidence;
• validation delta;
• rejection or acceptance reason.
No opaque "improve prompt" operations.


⸻


4. Non-Goals for v0.1
Do not implement:
• model fine-tuning;
• reinforcement learning on model weights;
• distributed Kubernetes execution;
• hosted benchmark marketplace;
• leaderboard;
• multi-agent workforce optimization;
• graphical workflow editor;
• generic SaaS cloning framework;
• production system access;
• automatic benchmark generation from production;
• unrestricted arbitrary code mutation;
• sophisticated neural reward models;
• full web UI;
• real-time human simulation;
• optimization across different foundation models.
Architectural interfaces may permit these later.
They are explicitly outside v0.1.


⸻


5. System Model
The system has seven main concepts.
Domain
│
├── Task Curriculum
├── World Simulator
├── Raw System APIs
└── Verifiers

AgentPackage
│
├── Knowledge
├── Skills
└── MCP Tools

Solver
│
├── Analyze rollouts
├── Diagnose failures
├── Propose mutations
└── Select candidates

Runner
│
├── Provision world
├── Attach package
├── Run agent
├── Capture trajectory
└── Invoke verifier

Optimizer
│
└── Coordinates generations

Artifact Store
│
├── packages
├── rollouts
├── trajectories
└── evaluation results

Runtime Adapter
└── Connects an arbitrary agent runtime to the gym


⸻


6. High-Level Architecture
                     ┌─────────────────────┐
                     │       Domain        │
                     │                     │
                     │ Task generators     │
                     │ World simulator     │
                     │ Verifiers           │
                     └──────────┬──────────┘
                                │
                         task instances
                                │
                                ▼
                    ┌───────────────────────┐
                    │        Runner         │
                    └──────────┬────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
              ▼                                 ▼
    ┌────────────────────┐           ┌────────────────────┐
    │    AgentPackage    │           │   Static World     │
    │                    │           │                    │
    │ knowledge          │           │ system APIs        │
    │ skills             │           │ identities         │
    │ MCP workflows      │           │ permissions        │
    └─────────┬──────────┘           │ mutable state      │
              │                      └─────────┬──────────┘
│                                │
              └───────────┬────────────────────┘
                          ▼
                    Agent Runtime
                          │
                     interactions
                          │
                          ▼
                  Final World State
                          │
                          ▼
                 ┌─────────────────┐
                 │    Verifier     │
                 └────────┬────────┘
                          │
                trajectory + result
                          │
                          ▼
                 ┌─────────────────┐
                 │     Solver      │
                 │                 │
                 │ diagnose        │
                 │ mutate          │
                 │ evaluate        │
                 └────────┬────────┘
                          │
                          ▼
                  AgentPackage N+1


⸻


7. Repository Structure
Recommended initial repository:
agent-evolution-gym/
│
├── pyproject.toml
├── README.md
├── LICENSE
├── Makefile
│
├── src/
│   └── agentgym/
│       │
│       ├── core/
│       │   ├── domain.py
│       │   ├── task.py
│       │   ├── package.py
│       │   ├── mutation.py
│       │   ├── rollout.py
│       │   ├── verification.py
│       │   ├── trajectory.py
│       │   └── generation.py
│       │
│       ├── runner/
│       │   ├── runner.py
│       │   ├── lifecycle.py
│       │   └── budgets.py
│       │
│       ├── world/
│       │   ├── base.py
│       │   ├── snapshot.py
│       │   ├── capabilities.py
│       │   └── docker.py
│       │
│       ├── runtime/
│       │   ├── base.py
│       │   ├── process.py
│       │   └── reference_agent.py
│       │
│       ├── solver/
│       │   ├── base.py
│       │   ├── diagnosis.py
│       │   ├── mutations.py
│       │   ├── greedy.py
│       │   └── reflection.py
│       │
│       ├── optimizer/
│       │   ├── optimizer.py
│       │   ├── selection.py
│       │   └── pareto.py
│       │
│       ├── verifier/
│       │   ├── base.py
│       │   ├── predicates.py
│       │   └── state_diff.py
│       │
│       ├── storage/
│       │   ├── store.py
│       │   ├── sqlite.py
│       │   └── filesystem.py
│       │
│       └── cli/
│           └── main.py
│
├── domains/
│   └── confluence/
│       │
│       ├── domain.yaml
│       │
│       ├── world/
│       │   ├── docker-compose.yaml
│       │   ├── api/
│       │   ├── models/
│       │   └── fixtures/
│       │
│       ├── scenarios/
│       │   ├── edit_page.py
│       │   ├── concurrency.py
│       │   └── permissions.py
│       │
│       ├── verifiers/
│       │   └── page_edit.py
│       │
│       └── splits/
│           ├── train.yaml
│           ├── validation.yaml
│           └── test.yaml
│
├── packages/
│   └── baseline/
│       ├── package.yaml
│       ├── knowledge/
│       ├── skills/
│       └── mcp/
│
├── experiments/
│
└── tests/
    ├── unit/
    ├── integration/
    ├── domains/
    └── e2e/


⸻


8. Core Data Model
Use Pydantic models for persisted contracts.


⸻


8.1 DomainSpec
from pydantic import BaseModel


class DomainSpec(BaseModel):
    id: str
    version: str

    description: str

    world_provider: str

    scenario_modules: list[str]
    verifier_modules: list[str]

    train_split: str
    validation_split: str
    test_split: str

    capabilities: list[str]
Example:
id: enterprise-confluence
version: "0.1"

description: >
  Stateful simulated knowledge-management environment.

world_provider: docker

scenario_modules:
  - scenarios.edit_page
  - scenarios.concurrent_edit
  - scenarios.permissions

verifier_modules:
  - verifiers.page_edit

train_split: splits/train.yaml
validation_split: splits/validation.yaml
test_split: splits/test.yaml

capabilities:
  - confluence.pages.read
  - confluence.pages.write
  - confluence.search


⸻


9. Task Model
A Task represents one instantiated problem.
class Task(BaseModel):
    id: str
    scenario_id: str
    split: str

    goal: str

    actor_id: str
initial_snapshot_ref: str

    verifier_id: str

    metadata: dict
Example:
id: page-edit-0042
scenario_id: concurrent-page-edit
split: train

goal: >
  Update the "Deployment" section of the Payments Architecture
  page to state that production rollout requires approval from
  the service owner. Preserve all unrelated content.

actor_id: employee-max

initial_snapshot_ref: snapshots/page-edit-0042.json

verifier_id: confluence-safe-page-edit-v1

metadata:
  difficulty: medium
The task prompt must not expose verifier implementation details.


⸻


10. Scenario Generators
Task generation must be programmable.
class ScenarioGenerator(Protocol):

    id: str

    def generate(
        self,
        seed: int,
    ) -> Task:
        ...
A scenario generator creates:
• initial world state;
• user/actor identity;
• task goal;
• distractors;
• expected state transitions;
• verifier configuration.
Example parameter space:
ConcurrentEditScenario(
    page_structure=random_structure(),
    requested_section=random_target(),
    concurrent_change=random_concurrent_edit(),
    permission_mode=random_permission_mode(),
)
The generator should produce semantically different cases, not surface-level text permutations.


⸻


11. World Model
The World represents the enterprise simulation.
class World(Protocol):

    async def start(self) -> None:
        ...

    async def restore(
        self,
        snapshot: WorldSnapshot,
    ) -> None:
        ...

    async def snapshot(self) -> WorldSnapshot:
        ...

    async def capabilities(self) -> list["Capability"]:
        ...

    async def stop(self) -> None:
        ...


⸻


12. WorldSnapshot
Snapshots must make executions reproducible.
class WorldSnapshot(BaseModel):
    id: str
    domain_id: str
    schema_version: str

    timestamp: str

    resources: dict
For the initial Confluence domain:
{
  "pages": {},
  "page_versions": {},
  "users": {},
  "permissions": {}
}
The first implementation may persist snapshots as JSON.
Later implementations may use database dumps.


⸻


13. Raw System APIs
Raw APIs are the stable environmental interface.
Example:
GET  /api/pages/{id}
GET  /api/pages
POST /api/pages/search
PUT  /api/pages/{id}
GET  /api/pages/{id}/versions
These APIs should behave like real enterprise APIs:
• authentication;
• authorization;
• version conflicts;
• pagination;
• realistic error responses;
• partial failures;
• latency where relevant;
• immutable audit history.
Do not expose convenience operations merely to make agents successful.
The simulator represents the underlying system, not the desired solution.


⸻


14. Capability Boundary
Every task execution receives an explicit capability set.
class Capability(BaseModel):
    id: str
    system: str
    operation: str
Example:
confluence.pages.read
confluence.pages.write
confluence.search
The Agent Package may only build MCP tools using those capabilities.
An evolved tool must never gain new privileges.


⸻


15. AgentPackage
This is the trainable unit.
class AgentPackage(BaseModel):
    id: str
    version: str
    generation: int

    parent_id: str | None

    knowledge: list["KnowledgeArtifact"]
    skills: list["SkillArtifact"]
    tools: "ToolPackage"

    metadata: dict
Directory representation:
package/
├── package.yaml
├── knowledge/
├── skills/
└── mcp/


⸻


16. Knowledge Artifacts
Knowledge represents declarative information.
Examples:
domain concepts
business terminology
system semantics
policies
troubleshooting information
known constraints
Contract:
class KnowledgeArtifact(BaseModel):
    path: str
    sha256: str
    tags: list[str]
Knowledge should preferably remain Markdown in v0.1.
The optimizer can mutate:
ADD_DOCUMENT
EDIT_DOCUMENT
DELETE_DOCUMENT
SPLIT_DOCUMENT
MERGE_DOCUMENT
Avoid embedding or retrieval optimization initially.
Load all knowledge directly when package size permits.


⸻


17. Skill Artifacts
Skills represent procedural knowledge.
Recommended representation:
skills/
└── safely-edit-page/
    └── SKILL.md
Example structure:
# Safely Edit Existing Page

## When to use
Use when modifying an existing knowledge page.

## Inputs

- target page
- requested modification

## Procedure

1. Retrieve current page and version.
2. Identify exact edit region.
3. Preserve unrelated content.
4. Apply the smallest possible patch.
5. If version changed, re-read before update.
6. Verify final page state.

## Failure handling

If a version conflict occurs:
1. fetch latest page;
2. reconcile requested change;
3. retry once.

## Completion

The requested change is present and unrelated content is intact.
Supported mutations:
CREATE_SKILL
EDIT_SKILL
DELETE_SKILL
GENERALIZE_SKILL
MERGE_SKILLS
For v0.1, implement only:
CREATE_SKILL
EDIT_SKILL
DELETE_SKILL


⸻


18. ToolPackage
Tools are deterministic capabilities exposed to the agent through MCP.
class ToolPackage(BaseModel):
    root: str
    server_entrypoint: str

    sha256: str

    declared_capabilities: list[str]
Directory:
mcp/
├── server.py
├── tools/
└── tests/
Example baseline tools:
get_page
search_pages
update_page
A later generation may contain:
get_page_structure
preview_page_patch
apply_page_patch_safely


⸻


19. Tool Evolution Principle
The optimizer may learn to transform repeated reasoning into deterministic tooling.
Example repeated trajectory:
get_page
→ inspect version
→ calculate replacement
→ update_page
→ get_page
→ verify
Potential synthesized tool:
safe_patch_page
Internally:
read
→ validate
→ patch
→ update
→ verify
This should reduce:
• model reasoning burden;
• tool calls;
• latency;
• recurrent failure probability.
Tool creation should occur only when there is trajectory evidence that a stable deterministic operation exists.


⸻


20. Tool Mutation Types
class ToolMutationType(StrEnum):
    CREATE_TOOL = "create_tool"
    EDIT_TOOL = "edit_tool"
    DELETE_TOOL = "delete_tool"
Future:
COMPOSE_TOOLS
SPLIT_TOOL
GENERALIZE_TOOL
Do not implement these automatically in v0.1.
⸻


21. MCP Security Boundary
Generated MCP code must operate in an isolated container.
Architecture:
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
Generated MCP code must not directly access:
• verifier;
• task ground truth;
• underlying database;
• task fixtures;
• host filesystem;
• Docker socket;
• package history;
• test split;
• optimizer state.
Network access must be limited to the declared world API gateway.


⸻


22. MCP Validation Pipeline
Every MCP mutation must pass:
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
Failure at stages 1–9 immediately rejects the candidate.


⸻


23. Runtime Adapter
Although harness comparison is not the research goal, some runtime must execute tasks.
Keep this deliberately thin.
class RuntimeAdapter(Protocol):

    async def run(
        self,
        goal: str,
        package: AgentPackage,
        environment: "EnvironmentConnection",
        event_sink: "EventSink",
        budget: "ExecutionBudget",
    ) -> "RuntimeResult":
        ...
v0.1 should ship with one reference runtime.
Potential implementation:
generic tool-calling model loop
Do not optimize it.
Do not place task-specific logic inside it.


⸻


24. Execution Budget
class ExecutionBudget(BaseModel):
    max_wall_seconds: int = 300
    max_model_turns: int = 50
    max_tool_calls: int = 100
    max_tokens: int | None = None
Budget violations are distinct outcomes.


⸻


25. Trajectory
The Gym records interactions at observable boundaries.
class TrajectoryEvent(BaseModel):
    sequence: int
    timestamp: str

    type: str

    actor: str

    payload: dict
Minimum event taxonomy:
run.started

agent.started

model.request
model.response

tool.call
tool.result
tool.error

world.api.request
world.api.response

artifact.created

agent.error
agent.completed

verification.assertion
verification.completed

run.completed
Do not require private chain-of-thought.
Persist observable messages, tool actions, system responses, and state transitions.


⸻


26. Rollout
A Rollout is one execution of one task using one Agent Package.
class Rollout(BaseModel):
    id: str

    task_id: str
    package_id: str

    initial_state_ref: str
    final_state_ref: str

    trajectory_ref: str

    verification: "VerificationResult"

    metrics: "RolloutMetrics"


⸻


27. Rollout Metrics
class RolloutMetrics(BaseModel):
    wall_seconds: float

    model_turns: int
    tool_calls: int

    input_tokens: int | None
    output_tokens: int | None

    estimated_cost: float | None


⸻


28. Verification Model
class AssertionResult(BaseModel):
    id: str
    passed: bool

    category: str

    expected: object | None
    actual: object | None

    message: str


class VerificationResult(BaseModel):
    passed: bool

    score: float

    assertions: list[AssertionResult]

    required_changes_passed: bool
    forbidden_changes_passed: bool
    invariants_passed: bool

    metadata: dict


⸻


29. Verifier Protocol
class Verifier(Protocol):

    async def verify(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        trajectory: "Trajectory",
    ) -> VerificationResult:
        ...
The verifier should not depend on the agent's natural-language final answer unless the task intrinsically requires an answer artifact.


⸻


30. State-Diff Verification
Define:
diff = compare(initial_state, final_state)
The verifier checks:
required changes
forbidden changes
resource invariants
Example:
assert final.pages[target].body == expected_body

assert final.pages[target].version == initial.pages[target].version + 1

assert unchanged(
    initial.pages[unrelated_id],
    final.pages[unrelated_id],
)

assert preserved(
    concurrent_human_change,
    final.pages[target],
)


⸻


31. Failure Taxonomy
Do not encode every unsuccessful run as FAIL.
class RunStatus(StrEnum):
    PASS = "pass"
    TASK_FAIL = "task_fail"
    PARTIAL = "partial"

    AGENT_ERROR = "agent_error"
    TOOL_ERROR = "tool_error"
    ENVIRONMENT_ERROR = "environment_error"
    VERIFIER_ERROR = "verifier_error"

    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"

    POLICY_VIOLATION = "policy_violation"
Only genuine task execution results should influence task-performance optimization.
Infrastructure failures should be tracked separately.


⸻


32. Solver
The Solver analyzes rollouts and proposes mutations.
class Solver(Protocol):

    async def diagnose(
        self,
        package: AgentPackage,
        rollouts: list[Rollout],
    ) -> list["Diagnosis"]:
        ...

    async def propose(
        self,
        package: AgentPackage,
        diagnosis: "Diagnosis",
        budget: "MutationBudget",
    ) -> list["Mutation"]:
        ...


⸻


33. Diagnosis
Diagnosis is a first-class artifact.
class Diagnosis(BaseModel):
    id: str

    task_ids: list[str]

    summary: str

    suspected_layer: str

    confidence: float

    evidence: list[str]

    suggested_mutation_type: str
Valid layers:
knowledge
skill
tool
unknown
Example:
summary: >
  The agent repeatedly fails to preserve concurrent page edits
  because the primitive update_page workflow assumes the version
  observed at read time is still current.

suspected_layer: tool

confidence: 0.88

evidence:
  - task page-17 failed with version conflict
  - task page-29 overwrote concurrent edit
  - task page-41 performed the same fragile sequence

suggested_mutation_type: create_tool


⸻


34. Diagnostic Heuristics
The first solver should reason along these lines.
Missing knowledge
Indicators:
• agent searches repeatedly for the same domain fact;
• incorrect assumptions about business semantics;
• missing policy or terminology;
• correct tool usage but wrong interpretation.
Likely mutation:
knowledge


⸻


Missing procedure
Indicators:
• all required capabilities exist;
• agent knows relevant facts;
• ordering or recovery strategy repeatedly fails;
• different runs produce inconsistent procedures.
Likely mutation:
skill


⸻
Missing tool abstraction
Indicators:
• repeated multi-call sequence appears across trajectories;
• deterministic transformations repeatedly consume reasoning;
• repeated errors occur between the same API operations;
• operation requires concurrency/retry/validation discipline;
• high tool-call count around stable workflow.
Likely mutation:
MCP tool


⸻


35. Mutation Model
class Mutation(BaseModel):
    id: str

    package_id: str

    layer: str
    operation: str

    target: str | None

    rationale: str

    evidence_refs: list[str]

    patch: str
All mutations must be materialized as explicit diffs.


⸻


36. Mutation Budget
Prevent uncontrolled package growth.
class MutationBudget(BaseModel):
    max_files_changed: int = 3

    max_added_lines: int = 200
    max_deleted_lines: int = 200

    allow_tool_creation: bool = True

    max_new_tools: int = 1
    max_new_skills: int = 1
Candidates exceeding the budget are rejected.


⸻


37. Optimization Evidence
The solver should receive structured evidence rather than raw logs alone.
class OptimizationEvidence(BaseModel):
    failures: list[Rollout]
    successes: list[Rollout]

    failure_clusters: list["FailureCluster"]

    aggregate_metrics: dict

    rejected_mutations: list["RejectedMutationSummary"]
Remember rejected mutations so the solver does not repeat known-bad strategies.


⸻


38. Failure Clustering
Before proposing mutations, group related failures.
Simple v0.1 method:
1. summarize each failure;
2. classify failure layer;
3. cluster using structured tags;
4. prioritize by frequency × severity.
Avoid vector database infrastructure initially.
Example:
cluster A
  14 failures
  concurrency handling

cluster B
  8 failures
  incorrect search query construction

cluster C
  3 failures
  permission misunderstanding
Optimize cluster A first.


⸻


39. Candidate Generation
For each selected diagnosis:
current package
+
failure evidence
+
successful contrasting examples
+
rejected mutation history
+
mutation budget
        ↓
candidate mutation
The solver should generate multiple candidates only when budget permits.
v0.1:
1–3 candidates per optimization step


⸻


40. Candidate Validation
Use sequential gates.
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
Never run the full validation suite for syntactically broken candidates.


⸻


41. Acceptance Policy
Do not accept a candidate merely because training score improved.
Minimum constraints:
validation success >= baseline validation success

policy violations == 0

collateral damage <= baseline collateral damage

infrastructure errors == 0
Then require at least one meaningful improvement:
success rate
cost
latency
tool calls
package complexity


⸻


42. Multi-Objective Evaluation
Represent candidate quality as:
[
Q(P) =
(
success,
safety,
generalization,
cost,
latency,
complexity
)
]
Do not immediately collapse this into one scalar.
Maintain the underlying dimensions.
For v0.1 use a deterministic acceptance policy.
Later introduce Pareto search.


⸻


43. Package Complexity Metrics
Track:
knowledge_tokens
skill_tokens
skill_count
tool_count
MCP source LOC
MCP dependencies
average exposed tools per task
The optimizer should be discouraged from solving every case through bespoke artifacts.


⸻


44. Regression Attribution
After every accepted mutation, compare:
before package
vs
after package
for every validation scenario.
Persist:
newly passing tasks
newly failing tasks
unchanged passes
unchanged failures
Example:
+12 newly passing
-2 newly failing
74 unchanged passing
9 unchanged failing
Those two regressions must remain visible even if aggregate performance improves.


⸻


45. Generation
A generation is an immutable accepted Agent Package state.
class Generation(BaseModel):
    number: int

    package_id: str
    parent_package_id: str | None

    mutation_ids: list[str]

    train_metrics: dict
    validation_metrics: dict

    created_at: str
Lineage:
g0
│
├─ g1 add concurrency skill
│   │
│   └─ g2 create safe_patch_page tool
│       │
│       └─ g3 simplify skill
│
└─ rejected branch


⸻


46. Rejected Mutation Memory
Store:
class RejectedMutationSummary(BaseModel):
    mutation_id: str

    diagnosis_id: str

    summary: str

    rejection_reason: str

    regressions: list[str]
Feed relevant rejection history into future solver calls.


⸻


47. Meta-Consolidation
Every N accepted generations, run package consolidation.
Recommended default:
N = 5
The consolidation solver should inspect:
duplicate knowledge
obsolete rules
overlapping skills
unused skills
overlapping tools
unnecessarily specialized tools
Allowed operations:
remove
merge
generalize
simplify
Any consolidation candidate must pass the same validation suite.


⸻


48. Optimizer
The Optimizer coordinates the complete evolution loop.
class Optimizer:

    async def optimize(
        self,
        domain: Domain,
        initial_package: AgentPackage,
        config: OptimizationConfig,
    ) -> AgentPackage:
        ...


⸻


49. Optimization Algorithm v0.1
Pseudo-code:
package = initial_package

for generation in range(config.max_generations):

    train_rollouts = runner.run_split(
        domain.train,
        package,
    )

    evidence = analyze(train_rollouts)

    diagnoses = solver.diagnose(
        package,
        evidence,
    )

    diagnosis = prioritize(diagnoses)

    candidates = solver.propose(
        package,
        diagnosis,
        config.mutation_budget,
    )

    accepted = None

    for candidate in candidates:

        if not structural_validate(candidate):
            reject(candidate)
            continue

        if not static_validate(candidate):
            reject(candidate)
            continue

        candidate_package = apply(package, candidate)

        smoke = evaluate_smoke(candidate_package)

        if not smoke.valid:
            reject(candidate)
            continue

        validation = evaluate_validation(
            candidate_package
        )

        if acceptance_policy(
            baseline=package,
            candidate=candidate_package,
            validation=validation,
        ):
            accepted = candidate_package
            break

        reject(candidate)

    if accepted is None:
        maybe_expand_diagnosis()
        continue

    package = accepted

return package


⸻


50. Stop Conditions
Optimization stops when any condition is met:
max generations reached
target validation success reached
no accepted mutation for N iterations
budget exhausted
package complexity threshold exceeded
manual stop
Recommended defaults:
max_generations = 20
stagnation_limit = 5


⸻


51. Experiment Configuration
Example:
experiment:
  id: confluence-evolution-001

domain:
  path: domains/confluence

package:
  path: packages/baseline

optimization:
  max_generations: 20

  candidate_count: 3

  mutation_budget:
    max_files_changed: 3
    max_added_lines: 200
    max_new_tools: 1
    max_new_skills: 1

acceptance:
  require_no_safety_regression: true
  require_no_collateral_regression: true

  improvement_metrics:
    - success_rate
    - tool_calls
    - latency


⸻


52. CLI
Minimum CLI:
agentgym domain validate domains/confluence
agentgym package validate packages/baseline
agentgym run \
    --domain domains/confluence \
    --task page-edit-0042 \
    --package packages/baseline
agentgym eval \
    --domain domains/confluence \
    --split validation \
    --package packages/baseline
agentgym optimize \
    --config experiments/confluence-evolution-001.yaml
agentgym generations list \
    experiments/confluence-evolution-001
agentgym diff \
    packages/generation-4 \
    packages/generation-5
⸻


53. Storage
Use filesystem + SQLite in v0.1.
Filesystem:
runs/
├── run-id/
│   ├── manifest.json
│   ├── trajectory.jsonl
│   ├── initial-state.json
│   ├── final-state.json
│   └── verification.json

generations/
├── 000/
├── 001/
└── ...

mutations/
SQLite indexes:
runs
tasks
packages
generations
mutations
diagnoses
evaluations
Do not introduce external databases initially.


⸻


54.
Run Manifest
Each run must record enough information to reproduce it.
{
  "task_id": "...",
  "task_hash": "...",

  "package_id": "...",
  "package_hash": "...",

  "domain_version": "...",

  "world_snapshot_hash": "...",

  "runtime": {
    "name": "...",
    "version": "..."
  },

  "model": {
    "provider": "...",
    "identifier": "..."
  },

  "seed": 42
}
Model information is recorded for reproducibility even though it is not the optimization target.


⸻


55. Observability
Every optimization report should expose:
generation
validation success
train success
tool calls
latency
token usage
package size

accepted mutation
affected failure cluster
new passes
new regressions
Example:
Generation 7

Validation:
  success        81% → 89%
  tool calls     13.2 → 8.1
  latency        22s → 17s
  violations     0 → 0

Mutation:
  CREATE_TOOL safe_patch_page

Evidence:
  14 concurrency-related failures

Regression:
  +9 passing
  -1 failing


⸻


56. First Domain: Enterprise Confluence Simulator
The first domain should remain deliberately narrow.
Goal:
Evolve an agent capable of safely locating, understanding, editing, and maintaining enterprise knowledge pages.
Simulated resources:
users
spaces
pages
versions
permissions
Initial APIs:
search_pages
get_page
get_page_versions
create_page
update_page
Optional later:
comments
labels
attachments
Do not implement these initially unless required by scenarios.


⸻


57. Initial Confluence Scenario Families
Implement approximately 20–30 task templates across five families.
Family A — Retrieval
Examples:
find correct page
distinguish similar page titles
find page inside correct space
retrieve latest version


⸻


Family B — Basic editing
add section
update paragraph
replace obsolete value
append structured content


⸻


Family C — Preservation
modify one section while preserving everything else
retain page formatting
avoid editing neighboring page


⸻


Family D — Concurrency
page changed after read
version conflict
preserve concurrent human edit
retry safely


⸻


Family E — Permissions
readable but non-editable page
space-level restriction
request impossible under current identity
avoid unauthorized fallback


⸻


58. Example Evolution
Baseline package:
knowledge/
  confluence-basics.md

skills/
  none

mcp/
  search_pages
  get_page
  update_page
Observed failures:
concurrent edits overwritten
large page rewrites
incorrect target section
too many search calls
Generation 1:
knowledge/
  page-version-semantics.md
Generation 2:
skills/
  safely-edit-page/SKILL.md
Generation 3:
mcp/
  preview_page_patch
Generation 4:
mcp/
  safe_patch_page
Generation 5 consolidation:
remove redundant version instructions from
multiple skills because safe_patch_page now
enforces the behavior deterministically
This is the desired learning dynamic.
Knowledge can eventually migrate into procedure.
Procedure can eventually migrate into deterministic tooling.


⸻


59. Important Research Signal: Knowledge → Skill → Tool
Track whether repeated optimization produces this progression:
failure
  ↓
declarative knowledge
  ↓
procedural skill
  ↓
deterministic tool abstraction
Example:
"remember to check page versions"
           ↓
skill procedure for concurrency
           ↓
safe_patch_page tool
This transition may represent increasing operational maturity.
The Gym should preserve this lineage.


⸻


60. Tool Usage Telemetry
Record tool sequences so repeated subgraphs can be discovered.
Example:
search_pages
get_page
get_page_versions
update_page
get_page
Aggregate:
sequence frequency
success correlation
failure correlation
average latency
average tokens around sequence
Later this evidence can trigger tool-synthesis proposals.


⸻


61. Automated Tool-Making Heuristic
Initial heuristic:
Propose a new tool when:
same tool sequence appears >= 5 times

AND

sequence length >= 3

AND

operation is mostly deterministic

AND

sequence appears across >= 2 scenario families

AND

failure/cost evidence suggests abstraction is useful
Do not create a tool solely because a sequence is frequent.
Require a concrete expected benefit.


⸻


62. Safety Model
The optimizer itself is potentially adversarial to the benchmark if unconstrained.
Explicitly prevent:
reading verifier source at runtime
reading expected final state
reading hidden task metadata
direct database access
modifying initial snapshots
modifying raw APIs
network access outside allowed systems
writing outside AgentPackage
persisting state between tasks unless allowed
Each package evaluation runs in a fresh world.


⸻


63. Overfitting Controls
Use:
1. held-out validation;
2. hidden test split;
3. scenario-level splitting;
4. mutation complexity penalties;
5. package-size metrics;
6. regression attribution;
7. task regeneration with new seeds;
8. periodic evaluation on unseen scenario combinations.
A candidate must not access validation or test ground truth.


⸻


64. Test Split Policy
During optimization:
train:
full trajectory
full verifier feedback

validation:
task outcome
assertion-level feedback may be available to acceptance system
but not mutation solver by default

test:
completely inaccessible
Optional stricter mode:
solver receives only aggregate validation score


⸻


65. Determinism
Perfect reproducibility is impossible with probabilistic models, but environmental reproducibility is mandatory.
Pin:
world snapshot
task seed
package version
API implementation
verifier version
runtime configuration
model identifier
Run multiple epochs for important evaluations.
⸻


66. Evaluation Statistics
For each package report:
success rate
pass@1
consistency across repeated runs

average wall time
average tool calls
average tokens

policy violation rate
collateral modification rate

package complexity
Later add:
pass^k
for consistency-sensitive evaluation.


⸻


67. Runtime Failures vs Package Failures
Never attribute environmental failures to the package.
Example:
HTTP simulator crashes
→ ENVIRONMENT_ERROR

generated MCP throws exception
→ TOOL_ERROR

agent selects wrong page
→ TASK_FAIL

agent hits wall-time limit
→ TIMEOUT
Optimization datasets should filter or separately handle infrastructure failures.


⸻


68. Reference Solver v0.1
Implement a simple LLM-powered reflective solver.
Inputs:
current package summary
failure cluster
representative failed trajectories
representative successful trajectories
validation metrics
rejected mutation memory
mutation budget
Output structured JSON:
{
  "diagnosis": {
    "layer": "skill",
    "summary": "..."
  },
  "mutation": {
    "operation": "CREATE_SKILL",
    "path": "skills/safe-page-edit/SKILL.md",
    "content": "..."
  }
}
Require schema validation.


⸻


69. Future Optimizer Adapters
Design for future:
GEPA-style reflective search
evolutionary search
MCTS workflow search
Bayesian optimization
human-designed mutations
RL controller
Core Gym must not depend on a particular optimizer.


⸻


70. Python Protocol Summary
Core conceptual API:
class Domain(Protocol):
    async def sample_tasks(
        self,
        split: str,
        count: int,
    ) -> list[Task]:
        ...


class WorldFactory(Protocol):
    async def create(
        self,
        task: Task,
    ) -> World:
        ...


class RuntimeAdapter(Protocol):
    async def run(
        self,
        task: Task,
        package: AgentPackage,
        world: World,
    ) -> RuntimeResult:
        ...


class Verifier(Protocol):
    async def verify(
        self,
        task: Task,
        initial: WorldSnapshot,
        final: WorldSnapshot,
        trajectory: Trajectory,
    ) -> VerificationResult:
        ...


class Solver(Protocol):
    async def diagnose(
        self,
        package: AgentPackage,
        rollouts: list[Rollout],
    ) -> list[Diagnosis]:
        ...

    async def propose(
        self,
        package: AgentPackage,
        diagnosis: Diagnosis,
    ) -> list[Mutation]:
        ...


class Optimizer(Protocol):
    async def optimize(
        self,
        domain: Domain,
        package: AgentPackage,
    ) -> AgentPackage:
        ...


⸻


71. Dependency Recommendations
v0.1:
Python 3.12
Pydantic
Typer
FastAPI
httpx
pytest
Docker / Docker Compose
SQLite
SQLModel or sqlite3
structlog
PyYAML
MCP:
Use the official or a mature Python MCP SDK, but isolate it behind an internal adapter.
Avoid coupling domain logic to one MCP implementation.


⸻


72. Development Phases
Phase 1 — Core
Implement:
Task
DomainSpec
WorldSnapshot
AgentPackage
Rollout
VerificationResult
Mutation
Generation
Acceptance:
All persisted models round-trip cleanly and are covered by unit tests.


⸻


Phase 2 — Static Confluence World
Implement:
users
spaces
pages
versions
permissions

REST APIs
snapshot/restore
Acceptance:
The world can be deterministically restored from a snapshot.


⸻


Phase 3 — Task + Verifier
Implement at least:
5 scenario generators
20+ concrete tasks
state-based verifiers
Acceptance:
Known-good oracle implementation passes all generated tasks.
Deliberately incorrect implementations fail expected assertions.


⸻


Phase 4 — Baseline Agent Package
Implement:
minimal knowledge
primitive MCP
no advanced skills
Acceptance:
Baseline agent succeeds on some but not all tasks.
A 100% baseline is undesirable because evolution cannot be demonstrated.
Target initial success:
30–60%


⸻


Phase 5 — Rollout Infrastructure
Implement:
Runner
trajectory logging
run manifests
metrics
failure taxonomy
Acceptance:
Any failed rollout can be reconstructed from stored artifacts.


⸻


Phase 6 — Skill/Knowledge Evolution
Implement:
diagnosis
knowledge mutations
skill mutations
held-out validation
generation lineage
rejection memory
Acceptance:
The optimizer can produce at least one validated improvement over the baseline package.


⸻


Phase 7 — MCP Evolution
Implement:
CREATE_TOOL
EDIT_TOOL
DELETE_TOOL

MCP sandbox
static checks
capability proxy
contract tests
Acceptance:
The solver can synthesize a workflow tool without gaining undeclared environment access.


⸻


Phase 8 — Generalization Experiment
Run evolution across:
train
validation
hidden test
Acceptance:
Demonstrate improvement on hidden tasks, not only training examples.


⸻


73. Initial Success Criteria for the PoC
The project is successful if it demonstrates all of the following:
1. A general agent starts with a deliberately weak Agent Package.
2. The environment exposes only realistic low-level APIs.
3. The agent executes a non-trivial distribution of enterprise tasks.
4. Deterministic verifiers identify both desired outcomes and collateral damage.
5. The solver can inspect failed training rollouts.
6. It can modify knowledge or skills.
7. It can validate the modification against held-out tasks.
8. At least one accepted package improves validation performance.
9. The solver can create or improve one MCP workflow tool.
10. The resulting tool improves either:
• success rate;
• reliability;
• latency;
• cost;
• tool-call count.
1. Improvement transfers to hidden test instances.
2. All generations remain reproducible and auditable.


⸻


74. Stretch Goal
Demonstrate emergent abstraction.
For example, training failures suggest creating:
edit_deployment_section_safely
but broader validation causes the solver to replace it with:
safe_patch_page
The second tool should solve more scenario families with less package complexity.
This would show that the optimizer can discover reusable operational abstractions rather than simply memorize benchmark cases.


⸻


75. Architecture Invariants
These should be encoded in tests.
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


⸻


76. Suggested First Implementation Sequence
Do not start with optimization.
Build in this order:
1. Confluence simulator

2. deterministic snapshots

3. scenario generator

4. verifier

5. primitive MCP

6. baseline runtime

7. trajectory recorder

8. evaluation CLI

9.
AgentPackage persistence

10. knowledge mutation

11. skill mutation

12. validation acceptance loop

13. failure clustering

14. MCP mutation

15. meta-consolidation
This minimizes uncertainty.
If the simulator and verifier are wrong, optimization results are meaningless.


⸻


77. Example End-to-End Run
Task:
Update the architecture page so the Deployment section says
production changes require service-owner approval.

A colleague edits another paragraph between your read and write.
Initial package:
knowledge:
  generic Confluence documentation

skills:
  none

tools:
  get_page
  search_pages
  update_page
Rollout:
search_pages
→ get_page v4
→ reason
→ update_page(v4)
→ conflict
→ update_page again incorrectly
→ finishes
Verifier:
requested change: PASS

concurrent human edit preserved: FAIL

unexpected modification: FAIL

overall: FAIL
Diagnosis:
layer: procedure/tool

reason:
agent lacks a reliable optimistic-concurrency workflow
Mutation:
CREATE_SKILL safely-edit-existing-page
Candidate validation:
success 52% → 68%

accepted
Subsequent rollouts repeatedly perform:
read
check version
patch
update
verify
Solver later proposes:
CREATE_TOOL safe_patch_page
Validation:
success     68% → 84%
tool calls  9.8 → 5.1
latency     21s → 14s
violations   0 → 0
Accepted.
After several generations, the procedural skill becomes shorter because concurrency correctness has migrated into deterministic tooling.
This is the intended evolution pattern.


⸻


78. Long-Term Architecture
After v0.1:
real production failures
        ↓
trajectory anonymization
        ↓
scenario extraction
        ↓
simulation generation
        ↓
Agent Evolution Gym
        ↓
new Agent Package
        ↓
regression evaluation
        ↓
staged deployment
Potential future domains:
merchant support
compliance operations
incident response
IT support
employee onboarding
finance operations
knowledge management
customer support
software engineering
One shared optimizer should eventually be able to specialize a general agent for each domain.


⸻


79. Research Questions
The implementation should enable experiments answering:
RQ1
Can external agent artifacts be optimized sufficiently to produce large domain-performance improvements without model fine-tuning?
RQ2
How much improvement comes from:
knowledge
vs
skills
vs
tools
RQ3
Can the solver correctly diagnose which layer is responsible for a failure?
RQ4
When should procedural knowledge be converted into deterministic tooling?
RQ5
Do evolved artifacts transfer between compatible agent runtimes or foundation models?
RQ6
Does package complexity grow indefinitely, or can consolidation produce simpler and more general solutions?
RQ7
Can optimization improve hidden scenario families rather than merely memorizing training tasks?


⸻


80. Final Definition
Agent Evolution Gym is:
A reproducible environment for automatically constructing and refining deployable domain-agent capability packages through executable experience.
Its fixed substrate consists of:
task distribution
+
simulated world
+
raw system APIs
+
permissions
+
verifiers
Its trainable substrate consists of:
knowledge
+
procedural skills
+
workflow MCP tools
Its learning mechanism is:
execute
→ observe
→ verify
→ diagnose
→ mutate
→ validate
→ retain
The intended output is not a benchmark score.
The output is a better Agent Package.
That distinction should remain the central architectural principle throughout implementation.
