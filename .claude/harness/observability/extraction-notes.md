# ABOUTME: Notes on which files in this harness are candidates for skill extraction.
# ABOUTME: Created 2026-04-29 after Session 1. Re-read before adding harness to the next project.

## Extraction: DONE (2026-06-01)

Skill extracted to `~/.claude/skills/claude-code-observability-harness/`.

Correction to the original plan: this note assumed the order was
`blueprint → reading-tracker → Brooklet` and said to wait until Brooklet got the
harness. That was wrong — **Brooklet already had it first and more completely**
(real order: blueprint → Brooklet (full: VictoriaLogs/VictoriaMetrics + transforms +
buffers + status.sh + no-op-when-absent otel module) → reading-tracker (lite: JSONL
file sinks only)). The two implementations together were the stress-test, so the skill
generalizes from both: it is **mode-parameterized** (`lite` = Vector+JSONL only, the
reading-tracker variant; `full` = + Victoria backends, the Brooklet variant) and keeps
the instrumentation-scanning phase that proposes domain instruments per project.

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

## Skill design: instrumentation scanning phase

The interesting half of the skill is an agent that scans the target codebase and
proposes instrumentation locations before writing anything. Three distinct point types,
each with its own detection signals:

**Tool call sites** (where `@_timed` goes):
- Files named `tools.py`, `*_tools.py`, `*_commands.py`
- Functions decorated with `@tool`, `@mcp.tool`, `@router.tool`, `@app.tool`, etc.
- FastAPI route handlers (`@app.get`, `@app.post`) also qualify
- Signature: `async def name(args: dict)` or `async def name(request: ...)`

**Router/dispatch sites** (where `record_router_message` goes):
- Classes/functions with names: `route`, `dispatch`, `handle_message`, `process`, `forward`
- Code that inspects a message and branches to different handlers
- The narrowest point where "message enters, destination is chosen"

**Agent result sites** (where `record_agent_tokens` goes):
- Call sites returning `ResultMessage`, `ModelResponse`, or any object with `.usage`
- `usage.input_tokens` / `usage.output_tokens` as field name signals
- Anthropic SDK: `client.messages.create(...)` or `await agent.run(...)` resolution points

**Workflow:** scan → structured proposal ("found 7 tools in tools.py, 1 router in
router.py, 2 LLM call sites in base_agent.py") → wait for confirmation → apply.
Don't apply blindly; patterns in Brooklet may differ enough that a silent write would
be wrong.

## Decisions to validate before freezing as conventions

Chosen for reading-tracker — might be accidents, not principles. Let Brooklet
stress-test these before locking them in as skill defaults.

- **Daily-rotation JSONL** files (vs. hourly, vs. single file)
- **3-day cleanup window** in `start.sh`
- **10MB log truncation threshold** — might be too small for chatty apps
- **Vector API port 8686** — Vector default, probably keep
- **OTLP ports 4317 / 4318** — OTLP standards, definitely keep
- **Lightweight mode only** — file sinks, no VictoriaMetrics/VictoriaLogs yet

## Verification (2026-06-01)

Pipeline verified end-to-end before any Brooklet install.

- **Transport:** direct OTLP emit → Vector `:4318` → dated JSONL in `data/jsonl/{traces,metrics}/` within seconds of force-flush.
- **Real app instrumentation:** one live `POST /agent` ("list books") fired every call site with correct labels:
  - `tool.latency{tool=list_books}` — `@_timed` in `app/tools.py`
  - `agent.tokens{agent=ui, duration_ms=...}` — `record_agent_tokens`
  - `router.messages{from=user, to=ui}` — `record_router_message`
  - span `router.user_message` — `otel.span()` in router
- The empty JSONL dirs noted after Session 1 were just an unexercised app, not a wiring bug.

**Gap closed in this session:** logs were the one missing signal. `vector.toml` wires a
`logs_jsonl` sink, but nothing emitted OTLP log records — Python `logging` was never bridged
to OTel. Added a `LoggingHandler` bridge in `app/otel.py:configure()` so stdlib logs flow to
the `otlp.logs` input. Decide during extraction whether the bridge is a skill default or opt-in.

## Related

- Blueprint: `~/.claude/docs/observability-harness.md`
- Session 1 commit: `4eeb275`
