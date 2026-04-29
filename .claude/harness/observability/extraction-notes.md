# ABOUTME: Notes on which files in this harness are candidates for skill extraction.
# ABOUTME: Created 2026-04-29 after Session 1. Re-read before adding harness to the next project.

## Trigger to extract

Wait until **Brooklet** gets this harness installed. That's the third repetition
(blueprint doc → reading-tracker → Brooklet) and the natural moment to factor out
a `claude-code-observability-harness` skill. Earlier extraction freezes the wrong
defaults — let one more concrete use case stress-test the conventions first.

## Portable across projects (drop-in copy)

These files have zero domain-specific strings. All paths are script-relative or
convention-fixed. Could be installed verbatim into any project.

| File | Notes |
|---|---|
| `install.sh` | Pinned Vector version, platform detection, idempotent |
| `start.sh` | Uses `git rev-parse --show-toplevel` to locate project root |
| `stop.sh` | SIGTERM → SIGKILL graceful shutdown |
| `vector.toml` | Drop-in IF the `.claude/harness/observability/data/jsonl/...` layout is a convention |
| SessionStart hook in `.claude/settings.json` | Just calls `start.sh` |
| `.gitignore` entries for `bin/`, `pids/`, `logs/`, `data/` | Universal |

## Project-specific (template, not copy)

| File | Why it's specific |
|---|---|
| `app/otel.py` | Hardcodes `service.name`. Defines domain metrics (`agent.tokens`, `tool.latency`, `router.messages`) |
| `@_timed` decorator placement in `app/tools.py` | Manual instrumentation per project. Pattern reusable; call sites are not |
| `record_router_message` / `record_agent_tokens` call sites | Wired into the app's specific routing/agent loop |

## Decisions to validate before freezing as conventions

Chosen for reading-tracker — might be accidents, not principles. Let Brooklet
stress-test these before locking them in as skill defaults.

- **Daily-rotation JSONL** files (vs. hourly, vs. single file)
- **3-day cleanup window** in `start.sh`
- **10MB log truncation threshold** — might be too small for chatty apps
- **Vector API port 8686** — Vector default, probably keep
- **OTLP ports 4317 / 4318** — OTLP standards, definitely keep
- **Lightweight mode only** — file sinks, no VictoriaMetrics/VictoriaLogs yet

## Related

- Blueprint: `~/.claude/docs/observability-harness.md`
- Session 1 commit: `4eeb275`
