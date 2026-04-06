# Harness Engineering Improvements for the Hexagonal Agent

This document maps harness engineering principles onto this project's hexagonal
multi-agent architecture. Each section identifies a gap, explains why it matters
for this specific application, and specifies where in the codebase the change
belongs.

**Framing**: The hexagonal architecture provides strong structural hygiene --
clean ports, adapters, and boundaries. Harness engineering adds *operational
robustness*: what happens when things go wrong, get slow, or get expensive.
The hexagonal pattern tells us *where* to put harness concerns; harness
engineering tells us *which* concerns to put there.

**Reference**: Sebastian Raschka, ["Components of a Coding Agent"](https://magazine.sebastianraschka.com/p/components-of-a-coding-agent)
(April 2025). See [docs/raschka-coding-agent-components.md](raschka-coding-agent-components.md)
for a structured summary.

---

## Raschka's Six Components vs. This Project

Before diving into specific improvements, here is how Raschka's six canonical
harness components map onto what this project already has and what it lacks.

| # | Raschka Component | This Project Has | This Project Lacks |
|---|---|---|---|
| 1 | **Live Repo Context** | N/A (not a coding agent, but analogous: the DB *is* our "repo") | No workspace summary injected into prompts. Agents don't see a snapshot of the current reading list state before reasoning. |
| 2 | **Prompt Shape & Cache Reuse** | Skill files provide a stable prefix; agent awareness prompt is generated once at connect time. | No explicit prompt caching strategy. System prompt is rebuilt on every `_ensure_connected()` call. No separation of stable vs. changing parts at the SDK level. |
| 3 | **Tool Access & Use** | Strong. MCP server with 7 named tools + `message_agent`. Validation in tools. `allowed_tools` whitelist per agent. | No approval gating (all tools auto-approved via `permission_mode="acceptEdits"`). No path/scope validation beyond basic input checks. |
| 4 | **Context Bloat Minimization** | `MessageLog` truncates responses to 500 chars for logging. | No clipping of tool outputs before they reach the LLM. No transcript compaction. No deduplication of repeated `list_books` results. No token budget tracking. |
| 5 | **Structured Session Memory** | Conversation history lives implicitly inside `ClaudeSDKClient`. `MessageLog` captures inter-agent messages. | No persistent session files. No working memory vs. transcript separation. No cross-session resumption. No explicit "what matters now" distillation. |
| 6 | **Delegation & Bounded Subagents** | Multi-agent delegation via `message_agent` tool. Router mediates all inter-agent calls. | Subagents are full agents with identical permissions -- no read-only mode, no recursion depth limit, no task scoping. An insights agent could theoretically call `message_agent` to UI which calls insights again (infinite loop). |

### What This Mapping Reveals

The project is strongest on **Component 3** (tool access) -- the hexagonal
architecture naturally produces clean tool boundaries. It is weakest on
**Components 4 and 5** (context management and session memory), which are
the components Raschka identifies as most underrated:

> "A lot of apparent 'model quality' is really context quality."

The hexagonal pattern gives excellent *structural* separation but doesn't
inherently address *temporal* concerns: how state evolves across turns, how
context grows and must be compacted, how sessions persist and resume. These
are the harness engineering concerns that complement the hexagonal bones.

---

## Agent SDK Features: Build vs. Built-In

The project uses `claude-agent-sdk` v0.1.22, but only a fraction of its
surface. Many harness concerns proposed below as custom code already have
SDK-level support. This section catalogs what the SDK provides so we can
decide what to **build** vs. what to **adopt**.

### Currently Used

| SDK Feature | Where Used | Notes |
|---|---|---|
| `ClaudeSDKClient` | All agents | `.connect()`, `.query()`, `.receive_response()`, `.disconnect()` |
| `ClaudeAgentOptions` | All agents | `system_prompt`, `mcp_servers`, `allowed_tools`, `permission_mode` |
| `AssistantMessage` / `TextBlock` | All agents | Response streaming and text extraction |
| `@tool` decorator | `tools.py`, `base_agent.py` | Custom MCP tool definitions |
| `create_sdk_mcp_server` | All agents | Bundle tools into MCP server |

### Available But Unused

These SDK features map directly onto harness engineering gaps:

| SDK Feature | Raschka Component | Harness Gap It Addresses | How to Adopt |
|---|---|---|---|
| **`max_turns`** | 4 (Context Bloat) | Prevents runaway agent loops | Add `max_turns=15` to `ClaudeAgentOptions`. Prevents infinite context growth without custom turn-counting code. |
| **`max_budget_usd`** | 4 (Context Bloat) | No cost guardrails | Add `max_budget_usd=0.50` per agent call. SDK stops the agent when budget is exhausted. Eliminates need for custom token tracking for cost control. |
| **`model`** | -- (operational) | Hardcoded model, can't use cheaper models for subagents | Set `model="claude-haiku-4-5"` for recommender/insights agents. Use Opus for UI agent. Raschka notes: "spawn a subagent with the cheaper model for the sub-task." |
| **`thinking`** | -- (quality) | No reasoning control | Add `thinking={"type": "adaptive"}` for complex multi-tool queries. Improves quality on recommendation and insights tasks. |
| **`agents` (subagent definitions)** | 6 (Delegation) | Subagents have identical permissions, no scoping | Replace custom `message_agent` tool with SDK `AgentDefinition`. Each subagent gets its own `tools` list, `prompt`, and scoped permissions. SDK handles spawning and context isolation. |
| **`hooks`** | 2 (Prompt Shape), 3 (Tools) | No tool call logging, no pre/post processing | Use `PostToolUse` hooks for observability (log every tool call with timing). Use `PreToolUse` for validation gates. Use `Stop`/`SubagentStop` for cleanup. |
| **`AssistantMessage.usage`** | -- (observability) | No token tracking | Each `AssistantMessage` includes `usage` dict with `input_tokens`, `output_tokens`. Capture in `AgentMessage` for the debug endpoint. |
| **`RateLimitEvent`** | 1 (Resilience) | No rate limit awareness | Handle `RateLimitEvent` in the response stream. Show "busy" UI instead of failing silently. |
| **`TaskProgressMessage`** | -- (observability) | No subagent progress tracking | When using SDK subagents, receive cumulative usage metrics per subtask. |
| **`output_format`** | 4 (Context Bloat) | Agent output is unstructured HTML string | Use structured output to enforce a schema (e.g., `{"html": str, "tools_called": list}`). Replaces custom output validation with SDK-level guarantees. |
| **`resume` (session resumption)** | 5 (Session Memory) | No cross-session continuity | Capture `session_id` from `SystemMessage` on init. Store in DB. Resume with `ClaudeAgentOptions(resume=session_id)`. SDK handles full transcript replay. |
| **`list_sessions` / `get_session_messages`** | 5 (Session Memory) | No session history | Query past sessions programmatically. Could power a "conversation history" UI feature. |
| **`betas=["compact-2026-01-12"]`** | 4 (Context Bloat) | No context compaction | Enable server-side compaction. SDK automatically summarizes earlier context when approaching 150K tokens. **Critical**: Must append `response.content` (not just text) to preserve compaction blocks. |
| **`context manager` (`async with`)** | 1 (Resilience) | Manual connect/disconnect lifecycle | Replace `_ensure_connected()` + manual `close()` with `async with ClaudeSDKClient(options) as client:`. Guarantees cleanup even on exceptions. |
| **`client.interrupt()`** | 1 (Resilience) | No way to cancel a stuck agent | Use instead of timeout-then-disconnect. Cleaner cancellation. |
| **`setting_sources`** | 1 (Live Context) | No CLAUDE.md integration | Load project-level settings/instructions automatically. |
| **`env`** | -- (operational) | Environment config not passed to agent | Pass `ANTHROPIC_API_KEY` and other env vars explicitly. |
| **MCP management** (`reconnect_mcp_server`, `toggle_mcp_server`, `get_mcp_status`) | 3 (Tools) | No runtime MCP server management | Monitor tool server health. Reconnect on failure instead of crashing. |

### Impact on Improvement Priorities

Many of the custom implementations proposed in the numbered sections below can
be **simplified or replaced** by SDK features:

| Improvement | Custom Build (Original Plan) | SDK Alternative | Recommendation |
|---|---|---|---|
| **1. Resilience** | Custom retry loop, circuit breaker, `asyncio.wait_for` | `max_turns`, `max_budget_usd`, `interrupt()`, `async with`, `RateLimitEvent` | **Hybrid**: Use SDK guardrails for budget/turns. Keep custom timeout at HTTP layer (`main.py`). Drop custom retry -- SDK has built-in retries for API errors. |
| **3. Context mgmt** | Custom turn counting, manual summarization, soft reset | `betas=["compact-2026-01-12"]` for server-side compaction, `max_turns` for loop bounds | **SDK first**: Enable compaction. Only build custom summarization if compaction proves insufficient for this app's patterns. |
| **5. Self-correction** | Custom retry-with-feedback loop | `thinking={"type": "adaptive"}` improves first-pass quality, reducing need for correction | **SDK first**: Enable adaptive thinking. Build correction loop only for specific failure modes (empty HTML). |
| **6. Dynamic registry** | Custom `register_agent()` + dynamic tool descriptions | SDK `agents` dict with `AgentDefinition` | **SDK native**: Replace entire custom multi-agent routing with SDK subagents. The `agents` param + `Agent` tool is the SDK's built-in version of exactly what `message_agent` does manually. |
| **7. Cross-session memory** | Custom DB table + tools | SDK `resume` for session continuity, `list_sessions` for history | **Hybrid**: Use SDK session resumption for within-app continuity. Keep custom preferences table for structured data (genre preferences, page limits) that doesn't fit in conversation context. |

### The Big Architectural Question: SDK Subagents vs. Custom Message Passing

The project's most distinctive feature -- the custom multi-agent message-passing
system (`AgentRouter`, `BaseAgent`, `message_agent` tool) -- overlaps significantly
with the SDK's built-in `agents` parameter and `Agent` tool:

**Current (Custom)**:
```python
# router.py manually creates agents, routes messages
router = AgentRouter()
await router.initialize()  # creates UIAgent, RecommenderAgent, InsightsAgent
response = await router.process_user_message(message)
# UIAgent calls message_agent tool -> router.route_agent_message() -> target.process()
```

**SDK Native Alternative**:
```python
options = ClaudeAgentOptions(
    system_prompt=ui_skill_content,
    allowed_tools=["Read", "Glob", "Agent"] + custom_tools,
    agents={
        "recommender": AgentDefinition(
            description="Book recommendations based on reading history",
            prompt=recommender_skill_content,
            tools=["mcp__app_tools__list_books", "mcp__app_tools__get_stats"]
        ),
        "insights": AgentDefinition(
            description="Reading pattern analysis",
            prompt=insights_skill_content,
            tools=["mcp__app_tools__list_books", "mcp__app_tools__get_stats"]
        ),
    },
    mcp_servers={"app_tools": tools_server},
    max_turns=20,
    max_budget_usd=1.00,
    thinking={"type": "adaptive"},
)
```

**Trade-offs**:

| Concern | Custom Message Passing | SDK Subagents |
|---|---|---|
| **Learning value** | High -- teaches agent orchestration from scratch | Lower -- SDK abstracts away the routing |
| **Observability** | Full control via `MessageLog` | SDK provides `TaskProgressMessage`, `SubagentStop` hooks |
| **Flexibility** | Can add custom routing logic, priority, load balancing | SDK handles spawn/cleanup but less customizable |
| **Bounded delegation** | Must build manually (recursion limits, read-only mode) | SDK scopes each subagent's `tools` list automatically |
| **Context isolation** | Each agent gets fresh context (intentional design) | SDK subagents inherit parent context by default |
| **Maintenance** | More code to maintain | SDK handles lifecycle, error recovery |

**Recommendation**: Keep the custom system as a learning vehicle, but create
a parallel branch that implements the SDK-native approach. Comparing the two
will teach you more about harness engineering than either one alone. The custom
system teaches *how* orchestration works; the SDK version teaches *what the
SDK handles for you* and where the remaining gaps are.

---

## Improvement Roadmap: Learning Path

Given the goal of learning harness engineering through this project, here is a
recommended order that builds understanding incrementally. Each step introduces
one concept, uses a mix of SDK features and custom code, and produces a
measurable before/after difference.

### Phase 1: Foundations (SDK Adoption)

These changes are mostly configuration -- switch from defaults to explicit SDK
features. Low effort, high learning density.

**Step 1: Enable SDK guardrails** (Raschka: Context Bloat + Resilience)
- Add `max_turns=20` and `max_budget_usd=0.50` to all `ClaudeAgentOptions`
- Add `thinking={"type": "adaptive"}` to UI agent
- Switch to `async with ClaudeSDKClient(options) as client:` pattern
- **Learn**: How the SDK constrains agent behavior without custom code
- **Measure**: Check that long conversations stop gracefully instead of running away

**Step 2: Add observability via SDK usage data** (Raschka: operational)
- Capture `AssistantMessage.usage` in every agent's `process()` method
- Extend `AgentMessage` with `input_tokens`, `output_tokens`, `duration_ms`
- Add timing with `time.monotonic()` around calls
- **Learn**: How much each agent costs per request, where time is spent
- **Measure**: `/debug/messages` now shows token counts and timing

**Step 3: Add hooks for tool logging** (Raschka: Tool Access + Prompt Shape)
- Register `PostToolUse` hooks to log every tool invocation
- Register `PreToolUse` hook for the `delete_book` tool to add confirmation
- **Learn**: How SDK hooks intercept the agent loop without modifying agent code
- **Measure**: Tool call audit trail in debug output

### Phase 2: Context Engineering (Custom + SDK)

These require understanding how context flows through the system. Mix of
SDK features and custom code.

**Step 4: Inject live data context** (Raschka: Live Repo Context)
- Call `get_stats()` in `_build_system_prompt()` and append reading list summary
- **Learn**: How workspace context improves agent responses (test with evals)
- **Measure**: Run recommendation evals before/after; compare quality

**Step 5: Enable server-side compaction** (Raschka: Context Bloat)
- Add `betas=["compact-2026-01-12"]` to `ClaudeAgentOptions`
- Ensure `response.content` (not just text) is preserved across turns
- **Learn**: How compaction works, what gets summarized, what's lost
- **Measure**: Run a 50-turn session; verify it doesn't degrade

**Step 6: Separate stable vs. dynamic prompt parts** (Raschka: Prompt Caching)
- Split `_build_system_prompt()` into `_build_stable_prefix()` and
  `_build_dynamic_context()`
- Stable: skill file + tool descriptions + agent awareness
- Dynamic: data snapshot + session summary
- **Learn**: How prompt structure affects caching (verify with `cache_read_input_tokens`)
- **Measure**: Token cost reduction on repeated calls

### Phase 3: Advanced Harness Patterns (Custom Build)

These require building custom infrastructure to understand the concepts deeply.

**Step 7: Build structured session memory** (Raschka: Session Memory)
- Add `user_preferences` table to database
- Add `save_preference` / `get_preferences` tools
- Capture `session_id` from SDK `SystemMessage` for session resumption
- **Learn**: The difference between conversation context and durable state
- **Measure**: Recommendation quality across session resets

**Step 8: SDK subagents vs. custom routing** (Raschka: Delegation)
- Create a branch using `AgentDefinition` + `Agent` tool instead of custom router
- Compare: observability, error handling, context isolation, ease of adding agents
- **Learn**: What the SDK abstracts, what you lose, what you gain
- **Measure**: Side-by-side eval results, code complexity comparison

**Step 9: Self-correction and output validation** (Raschka: Tool Access)
- Add HTML validation in `_validate_output()`
- Add tool-call verification (did `create_book` actually get called?)
- Add one-retry correction loop for empty/invalid responses
- **Learn**: How runtime guardrails differ from eval-time checks
- **Measure**: Eval pass rates before/after

---

### The Gap

`ui_agent.py:119-132` has zero resilience around the LLM call:

```python
async def process(self, message: str) -> str:
    await self._ensure_connected()
    await self.client.query(message)
    # ... stream response, no timeout, no retry
```

`router.py:148-156` catches exceptions but only logs and re-raises. A transient
API error kills the entire request.

### Why It Matters Here

This is a web app. Users click "Send" and wait. A 30-second hang with no
feedback is worse than a fast failure. And LLM APIs do have transient errors --
rate limits, 503s, network blips.

### Where to Apply

**`app/agents/base_agent.py`** -- Add a resilient `_call_llm()` method to BaseAgent:

```python
import asyncio

async def _call_llm_with_resilience(
    self,
    client: ClaudeSDKClient,
    message: str,
    timeout_seconds: float = 60.0,
    max_retries: int = 2,
) -> list[str]:
    """Call LLM with timeout and retry. Returns list of text blocks."""
    for attempt in range(max_retries + 1):
        try:
            await asyncio.wait_for(
                client.query(message),
                timeout=timeout_seconds,
            )
            html_parts = []
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            html_parts.append(block.text)
            return html_parts
        except asyncio.TimeoutError:
            if attempt == max_retries:
                raise TimeoutError(
                    f"Agent '{self.agent_name}' timed out after {timeout_seconds}s"
                )
        except ConnectionError:
            if attempt == max_retries:
                raise
            await asyncio.sleep(2 ** attempt)  # exponential backoff
```

Then each agent's `process()` calls `self._call_llm_with_resilience()` instead
of raw `client.query()` + `client.receive_response()`.

**`app/agents/router.py`** -- Add a simple circuit breaker to `route_agent_message()`:

```python
# Track consecutive failures per agent
self._failure_counts: dict[str, int] = {}
CIRCUIT_BREAK_THRESHOLD = 3

async def route_agent_message(self, from_agent, to_agent, message):
    if self._failure_counts.get(to_agent, 0) >= CIRCUIT_BREAK_THRESHOLD:
        return f"Error: Agent '{to_agent}' is temporarily unavailable"
    try:
        response = await self._agents[to_agent].process(message)
        self._failure_counts[to_agent] = 0
        return response
    except Exception as e:
        self._failure_counts[to_agent] = self._failure_counts.get(to_agent, 0) + 1
        raise
```

**`app/main.py:408-421`** -- Add timeout at the HTTP boundary:

```python
try:
    html = await asyncio.wait_for(
        router.process_user_message(message),
        timeout=90.0,  # outer bound for full multi-agent flow
    )
except asyncio.TimeoutError:
    return '<div class="p-4 ...">Request timed out. Try a simpler query.</div>'
```

---

## 2. Observability: Latency, Cost, and Tracing

### The Gap

`AgentMessage` (`router.py:27-42`) records timestamp but not duration, token
count, or cost. The debug endpoints return a flat list with no correlation
between user requests and the inter-agent messages they spawned.

### Why It Matters Here

With three agents that can chain (user -> UI -> recommender), a slow response
could be the UI agent, the recommender, or the DB. Without timing, you can't
tell. Without token counts, you can't budget or notice context bloat.

### Where to Apply

**`app/agents/router.py`** -- Extend `AgentMessage` with operational metadata:

```python
@dataclass
class AgentMessage:
    timestamp: str
    from_agent: str
    to_agent: str
    message: str
    response: str | None = None
    duration_ms: float | None = None        # wall-clock time
    input_tokens: int | None = None         # from SDK usage metadata
    output_tokens: int | None = None
    trace_id: str | None = None             # correlate user request -> sub-calls
```

Generate `trace_id` in `process_user_message()` and thread it through
`route_agent_message()` so all messages from one user request share the same
trace ID.

**`app/agents/base_agent.py`** -- Capture timing around LLM calls:

```python
import time

start = time.monotonic()
html_parts = await self._call_llm_with_resilience(...)
duration_ms = (time.monotonic() - start) * 1000
```

**`app/main.py`** -- Add a `/debug/traces` endpoint:

```python
@app.get("/debug/traces", response_class=JSONResponse)
async def debug_traces():
    log = router.get_message_log()
    # Group messages by trace_id
    traces = {}
    for m in log.messages:
        tid = m.trace_id or "unknown"
        traces.setdefault(tid, []).append(m.to_dict())
    return {"traces": traces}
```

---

## 3. Context Management: Token Budgets and Summarization

### The Gap

Each agent's `ClaudeSDKClient` accumulates conversation history indefinitely.
There is no summarization, no token budget, and no mechanism to prune context.
The system prompt alone (`ui.md` is 556 lines) is substantial.

### Why It Matters Here

A user adding 50 books in a session builds a long conversation. Eventually the
context window fills, the SDK silently truncates, and the agent loses earlier
instructions or forgets book details.

### Where to Apply

**`app/agents/base_agent.py`** -- Add context budget tracking:

```python
class BaseAgent(ABC):
    MAX_TURNS_BEFORE_RESET = 20  # reset conversation to reclaim context

    def __init__(self, router, agent_name):
        self._turn_count = 0

    async def process(self, message):
        self._turn_count += 1
        if self._turn_count > self.MAX_TURNS_BEFORE_RESET:
            await self._soft_reset()  # disconnect + reconnect, clearing history
            self._turn_count = 0
```

**`app/agents/ui_agent.py`** -- Add a summarization step before reset:

```python
async def _soft_reset(self):
    """Reset conversation but preserve key context."""
    # Capture any in-flight state the agent should remember
    summary_prompt = (
        "Summarize the user's reading list activity so far "
        "in 2-3 sentences. Focus on what books exist and "
        "any preferences expressed."
    )
    # Use current client to get summary before disconnecting
    summary = await self._get_summary(summary_prompt)
    await self.reset()
    # Reconnect, inject summary as first user message
    await self._ensure_connected()
    if summary:
        await self.client.query(f"[Context from earlier: {summary}]")
```

**Future consideration**: Track token usage from the SDK's response metadata
and trigger summarization based on actual token counts rather than turn counts.

---

## 4. Output Validation and Guardrails

### The Gap

`_clean_html()` in `ui_agent.py:134-143` strips markdown fences but does no
structural validation. The agent could return:
- Empty string (no content)
- Broken HTML (unclosed tags)
- JavaScript injection (if the LLM is manipulated)
- Responses that claim actions were taken without actually calling tools

The eval suite checks these post-hoc, but nothing enforces them at runtime.

### Why It Matters Here

This is an HTMX app that injects raw HTML into the DOM. A malformed response
breaks the UI. A hallucinated "Book added!" without a `create_book` tool call
misleads the user.

### Where to Apply

**`app/agents/base_agent.py`** -- Add an output validation hook:

```python
class BaseAgent(ABC):
    def _validate_output(self, html: str) -> str:
        """Validate and sanitize agent output. Override per-agent."""
        if not html or not html.strip():
            return '<p class="text-amber-400">No response generated. Please try again.</p>'
        return html
```

**`app/agents/ui_agent.py`** -- Override with HTML-specific checks:

```python
def _validate_output(self, html: str) -> str:
    html = super()._validate_output(html)
    # Ensure the response is actually HTML, not plain text
    if not any(tag in html for tag in ['<div', '<p', '<span', '<table', '<ul', '<h']):
        html = f'<div class="p-4 text-slate-300">{html}</div>'
    return html
```

**`app/main.py`** -- Add tool-call verification at the HTTP layer for
state-changing operations. When the user says "add [book]" and the response
says "Added!", verify that `create_book` was actually called by checking the
message log:

```python
# After agent processing, for state-changing requests
if any(verb in message.lower() for verb in ["add", "delete", "update", "remove"]):
    log = router.get_message_log()
    recent = log.messages[-1] if log.messages else None
    # Flag if no tool was called (heuristic -- refine as needed)
```

---

## 5. Planning and Self-Correction Loops

### The Gap

The current flow is single-turn: message in, response out. If the agent
generates broken HTML or a wrong answer, there's no retry-with-feedback loop.

### Why It Matters Here

Less critical for simple CRUD ("show my books"), but matters for complex
queries ("recommend books similar to the ones I rated 5 stars and show them
alongside my current reading list"). Multi-step tasks benefit from
plan-then-execute.

### Where to Apply

**`app/agents/base_agent.py`** -- Add an optional self-correction loop:

```python
async def _process_with_correction(
    self, client, message, max_corrections=1
) -> str:
    """Process with optional self-correction on validation failure."""
    html_parts = await self._call_llm_with_resilience(client, message)
    html = "\n".join(html_parts)
    html = self._clean_html(html)
    html = self._validate_output(html)

    # If validation wrapped the output in a fallback, retry once
    if max_corrections > 0 and "No response generated" in html:
        correction = (
            f"Your previous response was empty or invalid. "
            f"Please try again. Original request: {message}"
        )
        html_parts = await self._call_llm_with_resilience(client, correction)
        html = "\n".join(html_parts)
        html = self._clean_html(html)
        html = self._validate_output(html)
    return html
```

This is deliberately lightweight -- one retry, not an unbounded loop. The
hexagonal boundary means the correction logic lives in the agent infrastructure,
not in the HTTP adapter or the tools.

---

## 6. Dynamic Agent Registry

### The Gap

`router.py:98-102` hardcodes three agents:

```python
self._agents = {
    "ui": UIAgent(self),
    "recommender": RecommenderAgent(self),
    "insights": InsightsAgent(self),
}
```

Adding a new agent (e.g., a "social" agent for Goodreads integration) requires
modifying the router, the base agent's tool description, and the awareness
prompt.

### Why It Matters Here

The message-passing paradigm is already built for loose coupling. Making the
registry dynamic completes the decoupling.

### Where to Apply

**`app/agents/router.py`** -- Replace hardcoded agents with a registry:

```python
class AgentRouter:
    def __init__(self):
        self.message_log = MessageLog()
        self._agents: dict[str, Any] = {}
        self._agent_descriptions: dict[str, str] = {}
        self._initialized = False

    def register_agent(self, name: str, agent: BaseAgent, description: str):
        """Register an agent dynamically."""
        self._agents[name] = agent
        self._agent_descriptions[name] = description

    async def initialize(self):
        if self._initialized:
            return
        from .ui_agent import UIAgent
        from .recommender_agent import RecommenderAgent
        from .insights_agent import InsightsAgent

        self.register_agent(
            "ui", UIAgent(self),
            "Handles user interaction, generates HTML UI"
        )
        self.register_agent(
            "recommender", RecommenderAgent(self),
            "Book recommendations based on reading history"
        )
        self.register_agent(
            "insights", InsightsAgent(self),
            "Analyzes reading patterns and behavior"
        )
        self._initialized = True

    def get_agent_descriptions(self) -> dict[str, str]:
        return dict(self._agent_descriptions)
```

**`app/agents/base_agent.py`** -- `_get_agent_awareness_prompt()` already reads
from `router.get_agent_descriptions()`, so it will automatically pick up newly
registered agents. The `message_agent` tool description is the only part that
needs to become dynamic (currently it hardcodes "recommender" and "insights"
in the docstring at `base_agent.py:58-70`):

```python
# Build tool description from live registry
available = router.get_agent_descriptions()
other_agents = {k: v for k, v in available.items() if k != agent_name}
agent_lines = "\n".join(f"- {k}: {v}" for k, v in other_agents.items())

@tool("message_agent", f"Send a message to another agent.\n\nAvailable:\n{agent_lines}", ...)
```

---

## 7. Cross-Session Memory

### The Gap

When a user resets or starts a new session, all conversational context is lost.
The books persist in SQLite, but preferences ("I prefer sci-fi", "don't
recommend anything over 400 pages") disappear.

### Why It Matters Here

The recommender agent would give much better results if it remembered past
preferences across sessions. The insights agent could track trends over time
("you've been reading more this month than last").

### Where to Apply

**`app/database.py`** -- Add a `user_preferences` table:

```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS user_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
""")
```

**`app/tools.py`** -- Add `get_preferences` and `save_preference` tools:

```python
@tool("save_preference", "Save a user preference for future sessions.", {"key": str, "value": str})
async def save_preference(args):
    await db.upsert_preference(args["key"], args["value"])
    return _success({"saved": True})

@tool("get_preferences", "Get all saved user preferences.", {})
async def get_preferences(args):
    prefs = await db.get_all_preferences()
    return _success({"preferences": prefs})
```

**`app/agents/recommender_agent.py`** and **`insights_agent.py`** -- Add
`get_preferences` to their `allowed_tools` list and instruct them in their
skill files to check preferences before generating responses.

---

## 8. Structured Error Taxonomy

### The Gap

Errors are currently strings. `router.py:170` returns
`"Error: Unknown agent '...'"` as plain text. `tools.py` returns
`{"error": "..."}` as JSON. `main.py:413-421` catches all exceptions
identically. There's no way to distinguish retryable from terminal errors.

### Why It Matters Here

The UI agent receives error strings from tools and other agents. Without
structure, it can't decide whether to retry, ask the user for clarification,
or give up. It has to guess from the error text.

### Where to Apply

**`app/agents/router.py`** -- Define error types:

```python
from enum import Enum

class AgentErrorKind(Enum):
    TRANSIENT = "transient"       # retry may help (timeout, rate limit)
    INVALID_INPUT = "invalid"     # user needs to rephrase
    NOT_FOUND = "not_found"       # resource doesn't exist
    INTERNAL = "internal"         # bug, should not happen

@dataclass
class AgentError:
    kind: AgentErrorKind
    message: str
    retryable: bool = False

    def to_dict(self):
        return {"error": self.message, "kind": self.kind.value, "retryable": self.retryable}
```

**`app/tools.py`** -- Use structured errors in tool responses:

```python
def _error(message: str, kind: str = "internal", retryable: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps({
            "error": message, "kind": kind, "retryable": retryable
        })}],
        "is_error": True
    }

# Usage:
return _error(f"Book not found: {args['id']}", kind="not_found")
return _error("Database timeout", kind="transient", retryable=True)
```

---

## Summary: Learning Path at a Glance

| Phase | Step | Raschka Component | SDK vs Custom | Effort |
|---|---|---|---|---|
| **1: Foundations** | 1. SDK guardrails (`max_turns`, `max_budget_usd`, `thinking`) | 4 + Resilience | SDK config | Low |
| | 2. Observability (`usage` data, timing) | Operational | SDK + custom | Low |
| | 3. Hooks (tool logging, delete confirmation) | 3 (Tools) | SDK hooks | Low |
| **2: Context** | 4. Live data context (stats in system prompt) | 1 (Live Context) | Custom | Medium |
| | 5. Server-side compaction | 4 (Context Bloat) | SDK beta | Medium |
| | 6. Prompt cache optimization (stable/dynamic split) | 2 (Prompt Shape) | Custom + SDK | Medium |
| **3: Advanced** | 7. Structured session memory + preferences | 5 (Session Memory) | Custom + SDK | High |
| | 8. SDK subagents vs custom routing (comparison branch) | 6 (Delegation) | SDK native | High |
| | 9. Output validation + self-correction | 3 (Tools) | Custom | Medium |

**Start with Step 1.** It's three lines of config that immediately add
resilience and reasoning quality. Each subsequent step builds on what you
learned before.

---

## Architectural Insight

The hexagonal architecture and harness engineering are complementary lenses:

- **Hexagonal** answers *"where does each concern live?"* -- ports, adapters,
  core. It prevents spaghetti.
- **Harness** answers *"what concerns must exist?"* -- resilience, observability,
  context, guardrails. It prevents fragility.

Raschka's framing adds a third lens:

- **Coding harness** answers *"what does the model need to succeed?"* -- live
  context, compact prompts, validated tools, managed history, persistent
  memory, bounded delegation.

The hexagonal pattern is strong on Component 3 (tool boundaries) and
Component 6 (delegation via message passing). It is weak on Components 4-5
(context and memory), which are temporal concerns that the spatial
port/adapter model doesn't naturally address.

This project has strong hexagonal bones. The improvements above fill in the
harness flesh: making the system not just well-structured, but robust,
observable, and self-correcting.
