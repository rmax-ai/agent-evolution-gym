# Phase 1 Research Findings — Agent Evolution Gym v0.1

Status: verified 2026-09-06 against live PyPI + maintained skill knowledge (mcp-sdk-ecosystem, verified 2026-09-03). Engineering decisions for implementation; SPEC.md remains ground truth.

## 1. MCP stack: official `mcp` client + FastMCP-generated servers, adapter-isolated

**Live versions (PyPI 2026-09-06):** `mcp` 2.1.1 (official SDK v2, protocol `2026-07-28`), `fastmcp` 4.0.3 (metapackage over `fastmcp-slim` + `mcp-types>=2,<3` — decoupled runtime, no full-SDK dependency).

**Decision:**
- **Client side (runner ↔ generated server):** official `mcp` 2.x — `mcp.client.stdio.stdio_client` + `ClientSession`. Reference client for all runtime/tool interactions (SPEC §23, §25).
- **Server side (generated + baseline MCP tools):** FastMCP 4.x decorator API — simplest deterministic codegen target for the solver's CREATE_TOOL/EDIT_TOOL (SPEC §20, §22): a single `server.py` with `@mcp.tool()` functions and `mcp.run()`.
- **Isolation:** SPEC §22 stage 9 (sandbox startup) + §21 deny list are enforced by the gym, not by the SDK: spawned server subprocess with minimal env, cwd inside the package `mcp/` dir, network policy = capability proxy only (see §3). FastMCP and official mcp coexist in one venv (unlike google-adk which pins `mcp>=1.24,<2` and must never enter this project's env).
- Internal `mcp_adapter` module wraps spawn/session/list-call so domain logic never imports SDK types directly (SPEC §71).

**Pattern (verified API surface):**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async with stdio_client(StdioServerParameters(command=sys.executable, args=["server.py"], cwd=pkg_root, env=minimal_env)) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        res = await session.call_tool("safe_patch_page", {"page_id": 42, "patch": "..."})
```
Pitfalls: stdio handshake requires a clean async context (no blocking calls between `stdio_client` and `initialize`); server startup failure surfaces as EOF during initialize — capture stderr into the rollout trajectory (SPEC §25 `tool.error`); generated code must use only stdlib + fastmcp imports available in the package venv.

## 2. LLM access: OpenAI-compatible chat-completions adapter, structured JSON via json_schema

**Live:** `openai` 3.8.0 (Python ≥3.10). v3.x SDK supports both Responses and Chat Completions.

**Decision:**
- Define an internal `LLMClient` protocol (async `complete(messages, tools=None) -> Message`) implemented over **Chat Completions** (`chat.completions.create`) — the widest OpenAI-compatible surface (OpenAI, DeepSeek, vLLM, local servers). Responses API is NOT assumed.
- Reference agent (SPEC §23) = thin generic tool-calling loop on top of `LLMClient`: system prompt = assembled AgentPackage (knowledge + skills + tool descriptions), loop until done or budget exhausted (SPEC §24), trajectory events emitted at each model/tool boundary (SPEC §25). No task-specific logic.
- Reflective solver (SPEC §68): structured output via `response_format={"type": "json_schema", "json_schema": {...}}` against a Pydantic schema (diagnosis + mutation), with `json_object` + `model_validate` fallback for providers without json_schema support. Schema validation is a hard gate; malformed solver output = rejected candidate round, never silent retry loops.
- **Provider/model are runtime config** (env or experiment config), never code: `AGENTGYM_LLM_BASE_URL`, `_API_KEY`, `_MODEL`. PoC default on this host: DeepSeek chat-completions endpoint (cheap); gym runs on any compatible endpoint. Verify `openai` 3.8.0 client signatures at implementation time — adapter boundary makes churn local.

Pitfalls: tool-call JSON from weaker models arrives malformed — wrap every tool-call parse in try/except → `tool.error` trajectory event, not a crash; never send package `mcp/tests` or verifier content into model context (SPEC §21/§62/§64); budget counters must be enforced client-side, not trusted from usage fields.

## 3. World simulation: FastAPI app + uvicorn loopback for runs; ASGI transport for fast tests; Docker as optional provider

**Live:** `fastapi` 0.141.1, `uvicorn` 0.52.4, `httpx` 0.28.1.

**Decision (host has NO Docker — verified):**
- The Confluence simulator is a **FastAPI app owning an in-memory state store** (pages/versions/users/permissions — SPEC §12, §56). Raw API routes behave like real enterprise APIs: auth via actor header tokens, permission checks, optimistic-concurrency version conflicts, pagination, realistic error bodies, immutable version history (SPEC §13).
- **Gym runs:** world started as `uvicorn` on `127.0.0.1:<ephemeral-port>` per task; MCP tools call it over HTTP (loopback). Fresh world per package evaluation (SPEC §62) = new process/state from the task snapshot.
- **Unit/verifier tests:** `httpx.ASGITransport(app=app)` — no socket, fast, deterministic; used for in-process verifier/world assertions only.
- Snapshot/restore: serialize full state dict to JSON (`WorldSnapshot`, SPEC §12); `restore()` replaces state wholesale — no incremental merge. Version counters live inside page state so restore is total.
- `world_provider: docker` (SPEC §8.1) stays a declared value with `world/docker.py` + `docker-compose.yaml` shipped for containerized execution elsewhere; `process` is the local provider. Unit tests never require Docker (AGENTS.md).

Pitfalls: ASGITransport bypasses real socket behaviour — never test agent tool HTTP paths against it; loopback uvicorn needs `SO_REUSEADDR` hygiene + graceful shutdown between tasks (world.stop() awaited in finally); port collisions avoided via `port=0`.

## 4. Storage: filesystem JSON artifacts (ground truth) + stdlib `sqlite3` (async via `aiosqlite`) index

**Live:** `aiosqlite` 0.22.1, `sqlmodel` 0.0.42. Decision: **no SQLModel** in v0.1.

**Why:** SPEC §53 defines filesystem as the artifact ground truth (`runs/<id>/manifest.json, trajectory.jsonl, initial/final-state.json, verification.json`; `generations/`, `mutations/`) with SQLite only as indexes. SQLModel on Pydantic 2.13 adds version-coupling risk for near-zero gain at six simple tables. Stdlib sqlite3 + aiosqlite keeps the store dependency-light and trivially debuggable.

**Pattern:** `storage/filesystem.py` owns artifact writes (atomic: write tmp + rename; hashes computed for manifest — SPEC §54). `storage/sqlite.py` owns indexes: runs, tasks, packages, generations, mutations, diagnoses, evaluations — created via one schema module, opened per-write (WAL), never the source of truth. All persisted contracts are Pydantic models round-tripped via `model_dump(mode="json")` / `model_validate`.

Pitfalls: don't store trajectories in sqlite (jsonl only); manifest hashes must cover the referenced files (task_hash, package_hash, world_snapshot_hash — SPEC §54) — compute from bytes, not re-serialization; `object | None` fields (SPEC §28) serialize fine with `mode="json"` only if values are JSON-safe — verifier `expected`/`actual` are normalized to JSON-safe before persist.

## 5. Pydantic v2.13 + Python 3.12/3.13 practices (repo conventions)

- **Enums:** `StrEnum` (SPEC §20, §31) — serializes to its string value; keep DB/JSON values stable (`RunStatus.TIMEOUT.value == "timeout"`).
- **Union fields:** `object | None` OK in models (SPEC §28), but validate/normalize to JSON-safe values before persist; use `dict[str, Any]` for payload/metadata fields.
- **Timestamps:** tz-aware `datetime.now(timezone.utc)`, ISO-8601 strings in JSON; never `datetime.utcnow()` (deprecated).
- **Round-trip discipline:** every persisted model gets `model_dump(mode="json")` → `model_validate` round-trip tests (dev phase 1 AC, SPEC §72).
- **Config:** `model_config = ConfigDict(extra="forbid")` on persisted contracts to catch drift early; frozen=True on immutable artifacts (Generation after acceptance — SPEC §45).
- **Version pins for pyproject:** python >=3.12; pydantic>=2.13.5,<3; typer>=0.27; fastapi>=0.141; httpx>=0.28; mcp>=2.1.1,<3; fastmcp>=4.0.3,<5; pyyaml>=6.0.3; structlog>=26.1; pytest>=9.1; pytest-asyncio>=1.4 (asyncio_mode=auto); ruff>=0.16; ty>=0.0.78; aiosqlite>=0.22; uvicorn>=0.52.

## 6. Sources

- PyPI live JSON probes, 2026-09-06 (`~/.hermes/scripts/pypi-versions.py`)
- mcp-sdk-ecosystem skill + `references/mcp-python-sdk-landscape.md` (verified 2026-09-03): spec repo modelcontextprotocol/specification, python-sdk releases
- modelcontextprotocol spec: transports/stdio + client patterns (mcp 2.x)
- httpx ASGITransport docs; FastAPI testclient patterns
- openai python SDK changelog (v3.x) — verify signatures at implementation time
