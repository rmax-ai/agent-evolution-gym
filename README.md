# Agent Evolution Gym

A reproducible environment for automatically constructing and refining deployable
domain-agent capability packages through executable experience.

The world is fixed — task distribution, simulated enterprise world, raw system APIs,
permissions, verifiers. The **Agent Package** is the trainable artifact: domain
knowledge (`knowledge/`), procedural skills (`skills/`), and workflow-level MCP tools
(`mcp/`). The optimization loop executes a task curriculum, verifies outcomes against
deterministic world state, diagnoses failures, and proposes bounded, attributable
package mutations. No model fine-tuning, no harness optimization.

- **Specification:** `SPEC.md` (v0.1, 80 sections — sole source of truth)
- **Design:** `docs/ARCHITECTURE.md` · **Security:** `docs/THREAT_MODEL.md`
- **Roadmap:** `docs/ROADMAP.md` · **Agent conventions:** `AGENTS.md`

**Status:** planning — scaffold + Phase 0a design docs committed; development roadmap
tracked on the GitHub issue board (label-encoded phases `phase:0..6`). Implementation
starts after Phase 3 story breakdown; see `docs/ROADMAP.md` for dev phases 1–8.

License: MIT © 2026 Max Espinoza
