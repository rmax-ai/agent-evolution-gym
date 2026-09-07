# Telemetry (OpenTelemetry) — inert pattern demo

This repo carries the lab's **env-gated telemetry pattern** as a reference
implementation for public projects. It is deliberately inert:

- **Nothing runs unless `TELEMETRY_ENABLED` is set** — and this repo's normal
  execution paths do not set it.
- Dependencies live behind the optional `[telemetry]` extra and are **not**
  installed by default (`uv sync` alone never pulls them).
- The vendored `src/agentgym/telemetry.py` shim imports no OpenTelemetry code
  until `init()` is called, which only happens when enabled.
- The repo contains no endpoint or token strings. Auth for any real sink
  arrives exclusively via environment at call time.

## Environment variables

| Variable | Meaning | Default |
|---|---|---|
| `TELEMETRY_ENABLED` | master gate (`1`/`true`/`yes` enables) | unset → off |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP/HTTP exporter URL | SDK default |
| `OTEL_EXPORTER_OTLP_HEADERS` | e.g. `Authorization=Bearer <token>` | — |
| `OTEL_SERVICE_NAME` | service name override | `unknown` unless passed to `init()` |

## How an instrumented entrypoint looks (adoption guide)

```python
from agentgym import telemetry

def main() -> None:
    telemetry.init("agentgym")          # no-op unless TELEMETRY_ENABLED=1
    ...
    with telemetry.span("agentgym.run", {"experiment": name}) as span:
        ...  # real work
        if span is not None:
            span.set_attribute("outcome", "accepted")
```

Rules that keep public repos safe:

1. Spans carry **primitive attributes only** — ids, handles, scores, costs,
   durations. Never prompts, outputs, or content.
2. Guard post-hoc attributes with `if span is not None`; never raise for
   telemetry; telemetry failure must never break the run.
3. Run instrumented invocations with `uv run --extra telemetry` after an
   environment-only enable script has exported the exporter vars.
4. `telemetry.py` is synced from a lab-internal canonical source — do not edit
   it by hand (ruff per-file ignores exist because upstream style governs).

## Verification

```bash
# Inert by default: no telemetry imports, no network
python -c "from agentgym import telemetry; assert telemetry.init('x') is False"

# Enabled + real sink (lab): run an instrumented command under the lab's
# otel-env, then query the sink for service 'agentgym' spans.
```
