# Decisions — Agent Evolution Gym v0.1

Architectural decisions with rationale. SPEC.md remains ground truth; where SPEC
is silent or environment forces a choice, the decision is recorded here.

## D1 — Public repo, MIT
Repo `rmax-ai/agent-evolution-gym`, public, MIT © 2026 Max Espinoza (org convention).

## D2 — World provider: `process` default, `docker` declared (SPEC §8.1, §11)
Dev host has **no Docker** (verified). The Confluence world simulator is a FastAPI
app with an in-memory state store; `world_provider: process` runs it on uvicorn
loopback (ephemeral port) per task. Unit/integration tests use
`httpx.ASGITransport` in-process. `docker-compose.yaml` + `world/docker.py` ship for
containerized execution elsewhere; tests requiring Docker are gated/skipped locally.
Core never hard-couples to Docker (AGENTS.md).

## D3 — MCP: official `mcp` 2.x client + FastMCP 4.x generated servers (SPEC §71)
Runner spawns MCP servers over stdio via `mcp.client.stdio`; baseline and generated
servers are FastMCP apps (single `server.py`, `@mcp.tool()`). Both live in one venv
(mcp 2.1.1 + fastmcp 4.0.3 coexist; google-adk is excluded — pins `mcp<2`). All SDK
interaction behind an internal `mcp_adapter` module. Isolation (SPEC §21/§22) is the
gym's job: subprocess with minimal env + capability proxy; container isolation where
Docker exists.

## D4 — LLM: OpenAI-compatible chat-completions adapter (SPEC §23, §68)
Internal `LLMClient` protocol over `chat.completions.create` (widest compatible
surface). Reference agent = thin generic tool-calling loop. Solver structured output
via `response_format json_schema` + `json_object` fallback, Pydantic-validated.
Provider/model from env (`AGENTGYM_LLM_BASE_URL/API_KEY/MODEL`) — never code. PoC
runs may use the DeepSeek endpoint; final model choice for gym experiments is a
runtime config decision, not a repo decision.

## D5 — Storage: filesystem JSON ground truth + stdlib sqlite3 indexes (SPEC §53)
No SQLModel: filesystem artifacts (runs/, generations/, mutations/) are the ground
truth; SQLite (aiosqlite) only indexes runs/tasks/packages/generations/mutations/
diagnoses/evaluations. Persisted contracts = Pydantic models, `model_dump(mode="json")`.

## D6 — Dev model split (user directive 2026-09-06)
Implementation via Codex `gpt-5.6-luna`, `model_reasoning_effort=max`. High-level
verification via Codex `gpt-5.6-terra` (medium). Planning/research on `terra`/local.

## D7 — Implementation sequence follows SPEC §72 dev phases 1–8 (board-tracked)
Story board = label-encoded epics/stories; per-story gate: ruff → ty → pytest.

## D8 — Reference runtime LLM is deliberately weak/generic
No task-specific logic, no hidden knowledge (SPEC §23). Baseline package must land at
30–60% success (SPEC §72 Phase 4 AC) — if baseline exceeds it, the curriculum needs
harder tasks, not a stronger runtime.
