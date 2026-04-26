# Harness Engineering: A Hands-On Curriculum

A 12-lesson curriculum for learning harness engineering by adding reliability
layers to the reading-tracker's multi-agent system. Each lesson adds one
harness layer, moving outward from the bare agent loop. By the end, the same
app is observable, bounded, context-aware, memory-persistent, and
event-sourced.

**Approach**: Learning-first with blog-ready self-contained lessons. Each
lesson stands alone as a shareable article.

**Evaluation strategy**: Eval-driven development with BDD. Each lesson adds
Gherkin scenarios describing desired harness behavior, then implements and
verifies with the existing eval infrastructure.

**Theoretical framework**: Two complementary sources anchor this curriculum.

1. **Sebastian Raschka's "Components of a Coding Agent"** (April 2025) —
   six components: Live Repo Context, Prompt Shape & Cache, Tool Access &
   Use, Context Bloat, Session Memory, Delegation. Adapted to the
   reading-tracker domain via the docs in this repo
   (`docs/harness-improvements.md`, `docs/harness-engineering.md`,
   `docs/event-sourced-context-engineering.md`).

2. **Anthropic's "Scaling Managed Agents: Decoupling the Brain from the
   Hands"** (Lance Martin, Gabe Cemaj, Michael Cohen, April 2026) — the
   three-component decomposition: **Session** (append-only event log),
   **Harness** (the loop calling Claude), **Sandbox** (execution
   environment). Each can be swapped independently. Key principles we'll
   apply: externalized session state for resilience, standardized tool
   interfaces, cattle-not-pets components, and separation of *recoverable
   storage* from *context management strategy*.

### Assumption Staleness: A Core Principle

Anthropic's post surfaces a principle worth making explicit: **harness
workarounds encode assumptions about model limitations, and those
assumptions expire as models improve.** Claude Sonnet 4.5's "context
anxiety" (premature task wrap-up) required context resets — a workaround
that became dead weight when Claude Opus 4.5 no longer exhibited that
behavior.

The implication for this curriculum: prefer SDK-native solutions and
mechanical guardrails over custom workarounds that compensate for specific
model quirks. Design the harness to be minimal and inspectable, so you can
tell when an assumption has expired and remove the dead weight.

This principle shows up most directly in:
- **Lesson 2** (SDK guardrails over custom retry/budget code)
- **Lesson 8** (SDK compaction over custom turn-counting)
- **Lesson 11** (comparing custom routing to SDK subagents — and accepting
  that the SDK version may age better)

---

## Lesson Template

Every lesson follows this structure:

1. **The Concept** — What this harness layer is, why it exists, Raschka's
   framing, and the core analogy (reading list = repo context)
2. **What We're Working With** — Walkthrough of existing code we'll modify,
   explaining what it does and why it's structured this way
3. **The Spec** — BDD scenarios (Given/When/Then) describing desired behavior
4. **The Build** — Implement the concept, run evals to verify
5. **What Changed** — Before/after measurements (tokens, cost, eval pass
   rates, tool call counts)
6. **Takeaway** — One paragraph: when to apply this in your own projects

**Prerequisites**: Each lesson assumes previous lessons are complete. Each
produces a commit (or series of commits) that the next builds on.

---

## Phase 1: Understanding the Loop (Lessons 1-3)

### Lesson 1: The Bare Agent Loop

**Concept**: What an agent harness IS vs what an LLM IS. Raschka's
definitions: the LLM is the engine, the agent is the decision-making loop,
the harness is the surrounding scaffold. Walk the full request path from
HTMX click to HTML response.

**Existing code to walk through**:
- `main.py` — HTTP adapter, the `POST /agent` endpoint
- `router.py` — `AgentRouter`, `MessageLog`, `process_user_message()`
- `ui_agent.py` — The agent loop: `_ensure_connected()`, `process()`,
  `_build_system_prompt()`, `_clean_html()`
- `tools.py` — MCP tool definitions, the `@tool` decorator pattern
- `database.py` — SQLite state, the reading list as "repo"
- `base_agent.py` — Abstract base, `message_agent` tool, agent awareness

**BDD scenarios**: Document current behavior as executable baseline specs.
Capture: response times, token counts (if available), tool call patterns
per request type (show books, add book, get recommendations).

**Build**: No code changes. Write baseline BDD feature files. Write baseline
evals that capture current metrics. This becomes the "before" measurement
for every subsequent lesson.

**Takeaway**: Before improving a harness, instrument it. You can't measure
improvement without a baseline.

**Raschka mapping**: All 6 components — this lesson identifies which exist
and which are missing.

---

### Lesson 2: Bounding the Loop — SDK Guardrails

**Concept**: Raschka Component 4 (Context Bloat) meets resilience. An
unbounded agent loop is a cost and latency risk. Three SDK features provide
mechanical bounds without custom code: `max_turns` (prevent infinite loops),
`max_budget_usd` (prevent cost overruns), `async with` (prevent resource
leaks).

This lesson introduces the **assumption staleness** principle from
Anthropic's "Scaling Managed Agents" post. Custom retry loops, manual turn
counting, and hand-rolled budget tracking are all workarounds that
compensate for SDK limitations — or for model behaviors that may no longer
exist. SDK-native bounds age better because they're maintained alongside
the model. When we get a choice between "write custom code" and "configure
an SDK flag," we'll choose the flag and note why.

**Existing code to walk through**:
- `ClaudeAgentOptions` usage in all three agents
- The `_ensure_connected()` / manual `close()` lifecycle pattern
- What each SDK option does and what happens without it

**BDD scenarios**:
```gherkin
Feature: Agent loop bounds

  Scenario: Agent stops at turn limit
    Given an agent processing a complex multi-step request
    When it reaches 20 turns without completing
    Then it stops gracefully with a partial response
    And the response indicates the turn limit was reached

  Scenario: Agent stops at budget limit
    Given an agent processing an expensive request
    When token spend exceeds $0.50
    Then it stops and reports the budget limit
    And no further API calls are made

  Scenario: Agent resources are cleaned up on error
    Given an agent processing a request
    When an unexpected error occurs mid-processing
    Then the SDK client is properly disconnected
    And no resources are leaked
```

**Build**:
- Upgrade `claude-agent-sdk` from v0.1.22 to latest
- Add `max_turns=20` and `max_budget_usd=0.50` to all `ClaudeAgentOptions`
- Add `thinking={"type": "adaptive"}` to UI agent
- Switch to `async with ClaudeSDKClient(options) as client:` pattern
- Write evals verifying bounds are respected

**Takeaway**: Three lines of config that prevent runaway agents. Always set
bounds before anything else.

**Raschka mapping**: Component 4 (Context Bloat) — bounding is the first
defense against uncontrolled context growth.

---

### Lesson 3: Seeing the Loop — Observability

**Concept**: You can't improve what you can't measure. Token counts per
agent, wall-clock timing per call, trace IDs correlating a user request to
all the inter-agent messages it spawned. Observability is the meta-component
that makes all other harness layers measurable.

**Existing code to walk through**:
- `AgentMessage` dataclass in `router.py` — what it captures today
- `MessageLog` — the append-only log of inter-agent messages
- `/debug/messages`, `/debug/agents`, `/debug/views` endpoints
- `AssistantMessage.usage` — SDK-provided token metadata (new after upgrade)

**BDD scenarios**:
```gherkin
Feature: Agent observability

  Scenario: Token usage is captured per agent call
    Given a user sends a message to the UI agent
    When the agent processes and responds
    Then the message log entry includes input_tokens and output_tokens

  Scenario: Multi-agent traces are correlated
    Given a user request that triggers the recommender via the UI agent
    When I view the debug traces
    Then all messages from that request share the same trace_id
    And the trace shows: user → UI agent → recommender → UI agent → user

  Scenario: Timing is captured per agent call
    Given a user sends a message
    When the response is returned
    Then the message log entry includes duration_ms
    And the duration reflects wall-clock time including tool calls
```

**Build**:
- Extend `AgentMessage` with `duration_ms`, `input_tokens`,
  `output_tokens`, `trace_id`
- Capture `AssistantMessage.usage` from SDK in each agent's `process()`
- Add `time.monotonic()` timing around LLM calls
- Generate `trace_id` in `process_user_message()`, thread through routing
- Add `/debug/traces` endpoint grouping messages by trace ID
- Write evals verifying all metadata fields are populated

**Takeaway**: Instrument first, optimize later. Every subsequent lesson uses
this observability layer to prove its value quantitatively.

**Raschka mapping**: Cross-cutting — supports measurement of all 6
components.

---

## Phase 2: Feeding the Loop (Lessons 4-6)

### Lesson 4: Live Context — The Reading List as Repo Context

**Concept**: Raschka Component 1 (Live Repo Context). A coding agent knows
its git branch, file tree, and recent commits before reasoning. Our agents
should know the reading list state — book count, status distribution,
top-rated titles, recent activity — before seeing the user's message.

The core analogy: books = files, statuses = branches, recent additions =
recent commits, ratings = test results.

**Existing code to walk through**:
- `_build_system_prompt()` in each agent — skill file + awareness, no data
- `recommender_agent.py` skill file saying "use list_books to see what the
  user has read" — forcing a discovery tool call every time
- `database.py` `get_stats()` — the data source for the summary
- How a coding agent's `WorkspaceContext` (from Raschka's reference
  implementation) maps to our `_build_data_context()`

**BDD scenarios**:
```gherkin
Feature: Live reading list context

  Scenario: Agents receive data context in system prompt
    Given a reading list with 14 books across 3 statuses
    When the recommender agent is initialized
    Then its system prompt contains the book count
    And its system prompt contains the status distribution
    And its system prompt contains top-rated titles

  Scenario: Live context reduces tool calls
    Given live context is injected into the system prompt
    When I compare recommendation requests to the baseline (Lesson 1)
    Then the average tool calls per request decreases

  Scenario: Live context improves response quality
    Given the recommender already knows the user's top ratings
    When asked for a recommendation
    Then it references specific books from the reading list
    Without needing to call list_books first
```

**Build**:
- Implement `_build_data_context()` in `BaseAgent`
- Make `_build_system_prompt()` async
- Inject reading list summary into all three agents
- Run recommendation evals before/after
- Compare: tool call count, response quality, latency

**Takeaway**: Pre-loading domain state into the system prompt is the single
highest-impact harness improvement for most agent apps. It reduces tool
calls, improves quality, and lowers latency.

**Raschka mapping**: Component 1 (Live Repo Context) — the foundational
context layer.

---

### Lesson 5: Convention Tests — Mechanical Enforcement

**Concept**: The harness engineering principle: "conventions enforced by
tests, not prose." CLAUDE.md says every Python file needs an ABOUTME header.
That's advisory. A test in the test suite that fails when the header is
missing is mechanical. When the Stop hook runs the test suite, convention
violations become failures the agent must fix before it can stop.

**Existing code to walk through**:
- CLAUDE.md conventions: ABOUTME headers, no mocks, async-first, skill files
  per agent
- The eval suite structure in `evals/` — how tests are organized
- How convention tests differ from functional tests (structural invariants
  vs. behavioral correctness)

**BDD scenarios**:
```gherkin
Feature: Mechanical convention enforcement

  Scenario: ABOUTME headers are required
    Given a Python file in the app/ directory
    When the convention test suite runs
    Then every .py file (except __init__.py) has a 2-line ABOUTME header

  Scenario: No mock imports
    Given the test suite
    When the convention test checks for mock usage
    Then no file imports from unittest.mock or uses MagicMock

  Scenario: Skill files exist for all agents
    Given the agent registry
    When the convention test runs
    Then every registered agent has a corresponding skill file in app/skills/
```

**Build**:
- Create `tests/test_conventions.py` (or `evals/test_conventions.py` to
  match existing structure)
- Write structural tests: ABOUTME headers, no mock imports, skill file
  existence, `__init__.py` consistency
- Add a `Stop` hook to `.claude/settings.json` that runs the test suite
- Verify: break a convention, confirm the Stop hook catches it

**Takeaway**: Convention tests are cheap to write and catch drift that code
review misses. They're the bridge between "we decided X" and "X is always
true."

**Raschka mapping**: Component 3 (Tool Access) extended — conventions about
tool usage, output format, and code structure enforced mechanically.

---

### Lesson 6: Hooks — Intercepting the Loop

**Concept**: Raschka Component 3 (Tool Access). Hooks are hard enforcement
— deterministic checks that fire at specific points in the agent lifecycle.
Four essential hooks: SessionStart (baseline verification), PostToolUse
(lint on every edit), Stop (quality gate), PreToolUse (guardrails).

Three hook types: command (shell scripts, deterministic), prompt (LLM
evaluation, nuanced), http (external services). Anti-patterns: `exit 0`
swallowing errors, unanchored regexes, `&&` chaining independent checks.

**Existing code to walk through**:
- `.claude/settings.local.json` — permissions only, no hooks
- The hook event lifecycle from `docs/harness-engineering.md`
- JSON stdin/stdout protocol for command hooks
- How prompt-based hooks use a separate LLM as evaluator (evaluator
  separation principle)

**BDD scenarios**:
```gherkin
Feature: Harness hooks

  Scenario: Lint runs on every Python file edit
    Given a Python file is edited via the Edit tool
    When the PostToolUse hook fires
    Then ruff checks the modified file
    And lint errors are reported to the agent

  Scenario: Tests must pass before agent stops
    Given the agent has completed its work
    When it tries to stop
    Then the Stop hook runs the test suite
    And if tests fail the agent must fix them before stopping

  Scenario: Destructive git commands are blocked
    Given the agent attempts git push --force
    When the PreToolUse hook fires
    Then the command is blocked with exit code 2
    And the agent receives an explanation

  Scenario: Sensitive files are protected
    Given the agent attempts to edit .env
    When the PreToolUse hook fires
    Then the edit is blocked
    And the agent is told the file is protected

  Scenario: Guardrails fail closed
    Given the guardrail script cannot parse the hook input
    When any tool is attempted
    Then the hook blocks with exit code 2
    Rather than silently allowing the operation
```

**Build**:
- Create `.claude/settings.json` with all four essential hooks
- Write `.claude/hooks/protect-critical.sh` guardrail script (fail-closed,
  anchored regexes, both long and short git flags)
- Add PostToolUse lint hook matching `Edit|Write` for `.py` files
- Add Stop hook running `uv run pytest` as quality gate
- Add SessionStart hook for baseline verification
- Write evals testing each hook fires correctly

**Takeaway**: Hooks are the harness engineer's primary tool. They turn
"Claude should do X" into "Claude cannot proceed without X." Start with
the four essentials, add prompt-based hooks for nuanced quality checks.

**Raschka mapping**: Component 3 (Tool Access) — hooks validate, gate, and
intercept tool usage at every lifecycle point.

---

## Phase 3: Optimizing the Loop (Lessons 7-9)

### Lesson 7: Prompt Architecture — Stable vs Dynamic

**Concept**: Raschka Component 2 (Prompt Shape & Cache Reuse). The system
prompt has a natural split: stable prefix (skill file, tool descriptions,
agent awareness — unchanged across turns) and dynamic context (reading list
snapshot, session summary — rebuilt per request). Caching the stable prefix
reduces input token cost on every subsequent turn.

**Existing code to walk through**:
- `_build_system_prompt()` — currently assembles everything into one string
- Skill files in `app/skills/` — stable content
- `_get_agent_awareness_prompt()` — stable content
- `_build_data_context()` (from Lesson 4) — dynamic content
- How Anthropic's prompt caching works (cache_creation_input_tokens vs
  cache_read_input_tokens in usage metadata)

**BDD scenarios**:
```gherkin
Feature: Prompt caching

  Scenario: Stable prefix is cached across turns
    Given the agent has processed one request
    When a second request arrives with the same skill file
    Then cache_read_input_tokens is greater than zero in the usage metadata

  Scenario: Dynamic context is rebuilt per request
    Given a book is added between two requests
    When the second request is processed
    Then the system prompt reflects the updated book count
    And the stable prefix remains cached

  Scenario: Prompt split reduces token cost
    Given the prompt is split into stable and dynamic parts
    When I compare token costs to the monolithic prompt (Lesson 1 baseline)
    Then average input token cost per request decreases
```

**Build**:
- Split `_build_system_prompt()` into `_build_stable_prefix()` and
  `_build_dynamic_context()`
- Verify caching via `cache_read_input_tokens` in SDK usage metadata
- Compare per-request cost to Lesson 1 baseline
- Measure across a 10-turn session

**Takeaway**: Prompt structure directly affects cost. A well-structured
stable prefix that caches well can cut input token costs significantly.
Think about what changes and what doesn't before assembling your prompt.

**Raschka mapping**: Component 2 (Prompt Shape & Cache Reuse).

---

### Lesson 8: Context Management — Compaction and Sustainability

**Concept**: Raschka Component 4 deep dive. Context windows fill up.
Without management, a 20-turn session accumulates stale tool outputs (the
same 14-book JSON repeated 5 times), old HTML responses, and expired
conversation context. Two defenses: server-side compaction (SDK summarizes
older context) and output clipping (trim large tool results before they
enter the context).

**Existing code to walk through**:
- How conversation history accumulates in the SDK client
- The `list_books` tool returning full JSON every time (context bloat source)
- `MessageLog.truncate_response()` — current 500-char truncation for
  logging only (doesn't affect LLM context)
- `get_context_usage()` (new SDK feature) — query actual context fill level

**BDD scenarios**:
```gherkin
Feature: Context sustainability

  Scenario: Long sessions remain coherent
    Given a 30-turn session with book additions, ratings, and questions
    When server-side compaction is enabled
    Then the agent remembers books from turn 1 at turn 30
    And response quality does not degrade

  Scenario: Large tool outputs are clipped
    Given list_books returns 14 books as full JSON
    When the PostToolUse hook processes the result
    Then the context receives a summary (count, titles, statuses)
    Not the full JSON blob

  Scenario: Context usage is tracked
    Given an ongoing session
    When I query context usage after each turn
    Then I can see the context fill level as a percentage
    And it grows slower with clipping than without
```

**Build**:
- Enable `betas=["compact-2026-01-12"]` in `ClaudeAgentOptions`
- Ensure `response.content` (not just text) is preserved across turns
  (required for compaction blocks to work)
- Add `updatedMCPToolOutput` in PostToolUse hooks to clip large tool results
- Use `get_context_usage()` to track context fill level per turn
- Run a 30-turn eval session comparing with/without compaction
- Log context fill level in observability (Lesson 3 infrastructure)

**Takeaway**: Context is your scarcest resource. Compaction and clipping are
how you make long sessions viable. Monitor context fill level the way you'd
monitor memory usage in a traditional app.

**Raschka mapping**: Component 4 (Context Bloat) — the full treatment.

---

### Lesson 9: Output Validation and Self-Correction

**Concept**: Raschka Component 3 extended to outputs. Evals catch quality
issues post-hoc across many runs. Runtime validation catches them per-request
in production. Both are necessary: evals find systemic patterns, runtime
validation prevents individual bad responses from reaching users. The
self-correction loop: validate → if invalid, retry once with feedback.

**Existing code to walk through**:
- `_clean_html()` in `ui_agent.py` — strips markdown fences, nothing more
- The eval graders in `evals/graders.py` — `HTMLContains`, `ToolWasCalled`,
  `StateCheck`
- The gap: evals check after the fact, nothing checks at runtime
- The risk: HTMX injects raw HTML into the DOM

**BDD scenarios**:
```gherkin
Feature: Runtime output validation

  Scenario: Empty responses trigger self-correction
    Given the agent produces an empty response
    When output validation runs
    Then the agent retries once with feedback
    And the retry produces a valid HTML response

  Scenario: Non-HTML responses are wrapped
    Given the agent responds with plain text (no HTML tags)
    When output validation runs
    Then the response is wrapped in appropriate HTML elements

  Scenario: Tool-call verification for state changes
    Given the user says "add Dune to my list"
    And the agent responds "Added Dune!"
    When tool-call verification runs
    Then create_book was actually called in the message log
    Or a warning is logged about the discrepancy

  Scenario: Self-correction has a bounded retry
    Given the agent produces invalid output
    When the first retry also produces invalid output
    Then a graceful fallback message is returned
    And no further retries are attempted
```

**Build**:
- Add `_validate_output()` to `BaseAgent` (base: empty check)
- Override in `UIAgent` with HTML structure checks
- Add one-retry correction loop in `_process_with_correction()`
- Add tool-call verification at the router level for state-changing requests
- Extend evals with validation-specific test cases
- Measure: eval pass rate before/after

**Takeaway**: Runtime validation is the complement to evals. Evals tell you
about systemic quality. Validation enforces it per-request. A single
bounded retry catches most transient failures without infinite loops.

**Raschka mapping**: Component 3 (Tool Access) — validation and guardrails
on outputs, not just inputs.

---

## Phase 4: Persistence and Delegation (Lessons 10-11)

### Lesson 10: Session Memory — Remembering Across Resets

**Concept**: Raschka Component 5 (Structured Session Memory). Conversation
context is ephemeral — it lives in the SDK client and disappears on
disconnect. But user preferences ("I prefer sci-fi", "nothing over 400
pages") should persist across sessions. The distinction: conversation
context vs. durable state. Two layers: working memory (what matters now)
and persistent memory (what matters always).

**Existing code to walk through**:
- How conversation history lives inside `ClaudeSDKClient`
- `database.py` — currently stores books only, no preferences
- `tools.py` — CRUD tools for books, nothing for preferences
- The recommender skill file — tells the agent to ask about preferences
  but provides no persistence mechanism
- SDK session features: `session_id`, `resume`, `list_sessions`

**BDD scenarios**:
```gherkin
Feature: Cross-session memory

  Scenario: Preferences persist across session resets
    Given the user has told the recommender "I prefer sci-fi"
    And the preference is saved via save_preference
    When the session is reset and a new session begins
    Then the recommender's system prompt includes the sci-fi preference

  Scenario: Preferences improve recommendation quality
    Given stored preferences include "prefer sci-fi" and "max 400 pages"
    When the user asks for a recommendation
    Then the recommendation respects both constraints
    Without the user restating them

  Scenario: SDK session resumption works
    Given a session ID is captured during processing
    When the same session ID is used to resume
    Then conversation context from the previous session is available
```

**Build**:
- Add `user_preferences` table to `database.py`
- Add `save_preference` / `get_preferences` tools to `tools.py`
- Add preferences to `_build_data_context()` (Lesson 4 infrastructure)
- Add `get_preferences` to recommender and insights `allowed_tools`
- Update skill files to reference preferences
- Capture SDK `session_id` for resumption capability
- Eval: recommendation quality across session boundaries

**Takeaway**: Anything the agent should remember across sessions needs
explicit persistence. Conversation context is for the current session.
Durable state is for the user's relationship with the app.

**Raschka mapping**: Component 5 (Structured Session Memory).

---

### Lesson 11: Bounded Delegation — SDK Subagents vs Custom Routing

**Concept**: Raschka Component 6 (Delegation with Bounded Subagents). The
reading-tracker has a hand-built delegation harness: `AgentRouter` manages
agent lifecycle, `message_agent` routes messages, `MessageLog` captures
the trace. The SDK's `AgentDefinition` + `Agent` tool does the same thing
with less code. Building it yourself teaches how orchestration works.
Comparing to the SDK teaches what abstraction buys you.

This lesson also introduces Anthropic's **"decouple the brain from the
hands"** framing. In Managed Agents, each execution environment is a
"hand" exposed through a standardized interface (`execute(name, input) →
string`). This lets Claude reason about multiple execution targets and
lets failed components be replaced without affecting the rest of the
system. Our `message_agent` tool is a primitive version of the same
pattern — each agent is a "hand" with a semantic message interface.
Comparing our custom version to the SDK's `Agent` tool is really comparing
two implementations of the same architectural principle: standardized
tool interfaces enable composable delegation.

**Existing code to walk through (deep dive)**:
- `router.py` — `AgentRouter.__init__()`, `initialize()`, agent registry,
  `process_user_message()`, `route_agent_message()`, `MessageLog`
- `base_agent.py` — `message_agent` tool definition, `_get_agent_awareness_prompt()`,
  how agents discover each other
- `ui_agent.py` — how it decides to delegate (the skill file instructs it)
- The full delegation chain: user → UI agent → `message_agent("recommender")`
  → router → recommender agent → response → router → UI agent → HTML

**BDD scenarios**:
```gherkin
Feature: Bounded delegation

  Scenario: SDK subagents have scoped tools
    Given the recommender is defined as an SDK AgentDefinition
    When the UI agent delegates to it
    Then the recommender has access only to list_books, get_stats,
      get_preferences
    And it cannot call create_book or delete_book

  Scenario: SDK subagents have bounded turns
    Given the recommender AgentDefinition has maxTurns=10
    When it processes a complex recommendation request
    Then it completes within 10 turns

  Scenario: Both implementations produce equivalent results
    Given the same eval test cases
    When run against the custom routing implementation
    And run against the SDK subagent implementation
    Then eval pass rates are within 5% of each other

  Scenario: Trade-offs are documented
    Given both implementations exist on separate branches
    When I compare them
    Then the comparison documents: observability, error handling,
      context isolation, code complexity, lines of code
```

**Build**:
- Create a comparison branch (`git worktree` or feature branch)
- Implement SDK-native subagents with `AgentDefinition`:
  - recommender: scoped tools, bounded turns, own skill file
  - insights: scoped tools, bounded turns, own skill file
- Run the full eval suite on both implementations
- Document trade-offs in a comparison table
- Do NOT merge — keep both branches for reference

**Takeaway**: Build it yourself first to understand the problem space, then
evaluate the SDK alternative. Understanding what an SDK abstracts is as
valuable as understanding what it doesn't. The custom system teaches HOW
orchestration works; the SDK version teaches WHAT the SDK handles for you.

**Raschka mapping**: Component 6 (Delegation & Bounded Subagents).

---

## Phase 5: The Event-Sourced Frontier (Lesson 12)

### Lesson 12: Events and Context as Materialized View

**Concept**: The capstone idea. The LLM context window is a materialized
view projected from an event stream. Every agent interaction is an event
(user message, tool call, response, delegation, state change). Event
sourcing gives principled primitives for managing context: rollups compress
old events semantically (a state-changing "rated Dune 5/5" survives longer
than a read-only "listed 14 books" JSON blob), consumer groups give each
agent its own projection, snapshots provide cache boundaries.

This reframes Raschka's Components 4 (Context Bloat) and 5 (Session Memory)
as projections of a single underlying event stream.

**Architectural validation from Anthropic**: This lesson's framing aligns
directly with the Managed Agents architecture. Anthropic describes the
session as a "context object living outside Claude's context window," with
a `getEvents()` interface that supports "picking up from last read
position, rewinding before specific moments, rereading prior to specific
actions, and selecting positional slices of the event stream." They
explicitly separate *recoverable storage* (the session log) from *context
management strategy* (the harness transformation layer that builds the
context window from events).

This is exactly what a brooklet-backed event store + `ContextProjector`
gives us. Anthropic's architecture is the production-scale version of what
we're building at educational scale. Quote from the blog:

> "Fetched events can be transformed in the harness before passing to the
> context window. This decouples recoverable storage from context
> management strategy."

That decoupling is the key insight. The event log is the source of truth.
The context window is a view built by a projection function. The
projection function is where all the interesting harness engineering lives
— rollups, clipping, tiered fidelity, token budgets, per-agent views.

**Existing code to walk through**:
- `git_audit.py` — the existing event-like pattern (mirrors mutations to
  git commits)
- `evals/transcript.py` — records tool calls, agent messages, DB state
  (another event-like pattern)
- `database.py` mutations — the events that aren't captured as events today
- The event-sourced context engineering doc (`docs/event-sourced-context-engineering.md`)
  — the theoretical framework

**BDD scenarios**:
```gherkin
Feature: Event-sourced context

  Scenario: Book mutations are emitted as events
    Given a user adds a book via create_book
    When the mutation completes
    Then a brooklet event is appended to the "books" topic
    And the event contains action, book_id, title, and metadata

  Scenario: Event stream mirrors SQLite state
    Given 10 book mutations have occurred
    When I replay all events through the sqlite-projector
    Then the projected state matches the actual SQLite database

  Scenario: Tiered rollups compress old context
    Given a 20-turn conversation captured as events
    When the ContextProjector builds context with a token budget
    Then the last 5 turns are at full fidelity
    And turns 6-15 are summarized per-turn
    And turns 16+ are rolled into a session summary
    And total tokens are within the budget

  Scenario: Different agents get different projections
    Given the same event stream
    When the UI agent projects its context
    And the recommender agent projects its context
    Then the UI agent's projection emphasizes recent interaction
    And the recommender's projection emphasizes ratings and preferences
```

**Build**:
- Add brooklet as a dependency (`uv add brooklet`)
- Create `app/event_store.py` — emit events alongside SQLite writes
- Emit `create`, `update`, `delete` events for all book mutations
- Build a basic sqlite-projector that replays events and verifies parity
  with actual SQLite state
- Build a basic `ContextProjector` demonstrating tiered rollups:
  - Tier 0-1: last 5 turns at full fidelity
  - Tier 2: turns 6-15 summarized per-turn
  - Tier 3: turns 16+ session summary
- Show before/after context size for a multi-turn session
- Run evals verifying event parity and rollup correctness

**Takeaway**: Event sourcing isn't just a storage pattern — it's a context
engineering primitive. The "context window as materialized view" framing
applies to any agent harness. Semantic rollups (compressing by event type
and importance) outperform positional compression (by age or size) because
they preserve what matters: state changes and user intent.

**Raschka mapping**: Components 4 (Context Bloat) + 5 (Session Memory)
unified through event sourcing.

---

## Curriculum Summary

| # | Lesson | Raschka Component | Anthropic Principle | Phase | Key Artifact |
|---|--------|-------------------|---------------------|-------|-------------|
| 1 | The Bare Agent Loop | All 6 (audit) | Harness vs. Sandbox boundary | Understanding | Baseline BDD specs + evals |
| 2 | Bounding the Loop | 4 (Context Bloat) | Assumption staleness | Understanding | SDK guardrails config |
| 3 | Seeing the Loop | Cross-cutting | Externalized observability | Understanding | Observability infrastructure |
| 4 | Live Context | 1 (Live Repo Context) | — | Feeding | `_build_data_context()` |
| 5 | Convention Tests | 3 (Tool Access) | — | Feeding | `test_conventions.py` |
| 6 | Hooks | 3 (Tool Access) | Security boundary separation | Feeding | `.claude/settings.json` + hook scripts |
| 7 | Prompt Architecture | 2 (Prompt Shape) | Transformation layer | Optimizing | Stable/dynamic prompt split |
| 8 | Context Management | 4 (Context Bloat) | Recoverable storage ≠ context management | Optimizing | Compaction + clipping |
| 9 | Output Validation | 3 (Tool Access) | Cattle-not-pets on outputs | Optimizing | `_validate_output()` + correction loop |
| 10 | Session Memory | 5 (Session Memory) | Externalized session state | Persistence | `user_preferences` table + tools |
| 11 | Bounded Delegation | 6 (Delegation) | Decouple brain from hands | Persistence | SDK subagent comparison branch |
| 12 | Events & Context | 4 + 5 (unified) | Session as context object | Frontier | brooklet events + `ContextProjector` |

## What's NOT In Scope

These are potential extensions but are explicitly excluded from this
curriculum to keep it focused:

- **Full architectural inversion** (brooklet as sole source of truth,
  SQLite as pure projection) — this is a brooklet development project,
  not a harness engineering lesson
- **Production deployment concerns** (Docker, Fly.io, monitoring) —
  operational, not harness
- **UI/UX improvements** — the HTMX frontend is a vehicle, not the subject
- **Additional agents** (social, Goodreads integration) — feature work,
  not harness
- **Claude Code harness** (rules/, decisions/, project-local skills) —
  covered in `docs/harness-engineering.md` but orthogonal to the agent
  harness curriculum
- **MCP server configuration** (`.mcp.json`) — useful but not core to the
  learning progression
- **Managed Agents service integration** — Anthropic's hosted service is
  referenced as architectural validation for Lesson 12, but we're building
  the concepts ourselves at educational scale, not deploying to the
  production service

## Git Strategy

Each lesson is developed on a feature branch (`harness/lesson-NN-short-name`)
and merged to `main` on completion. This keeps each lesson's changes
isolated for blog reference while building a cumulative codebase. Lesson 11
(SDK subagents comparison) stays on its own branch and is NOT merged — it
exists for comparison only.

## Prerequisites

- Working reading-tracker app (`uv sync`, `uv run pytest` passes)
- `.env` with `ANTHROPIC_API_KEY`
- Familiarity with Python async/await
- Basic understanding of the hexagonal architecture pattern
- Git for version control (each lesson produces commits)
- brooklet library available for Lesson 12 (`uv add brooklet`)
