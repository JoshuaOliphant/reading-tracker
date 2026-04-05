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

---

## 1. Resilience: Retries, Timeouts, and Circuit Breakers

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

## Summary: Priority Order

| # | Improvement | Effort | Impact | Why This Order |
|---|---|---|---|---|
| 1 | **Resilience** (timeouts + retries) | Low | High | Users currently get hung requests or raw 500s |
| 2 | **Output validation** | Low | Medium | Prevents broken UI from reaching the browser |
| 3 | **Observability** (timing + traces) | Medium | High | Can't improve what you can't measure |
| 4 | **Error taxonomy** | Low | Medium | Enables smarter retry and error UX |
| 5 | **Context management** | Medium | Medium | Prevents degradation in long sessions |
| 6 | **Self-correction loops** | Medium | Medium | Improves complex query handling |
| 7 | **Dynamic registry** | Low | Low | Completes the hexagonal decoupling |
| 8 | **Cross-session memory** | High | High | Transforms recommendation quality |

---

## Architectural Insight

The hexagonal architecture and harness engineering are complementary lenses:

- **Hexagonal** answers *"where does each concern live?"* -- ports, adapters,
  core. It prevents spaghetti.
- **Harness** answers *"what concerns must exist?"* -- resilience, observability,
  context, guardrails. It prevents fragility.

This project has strong hexagonal bones. The improvements above fill in the
harness flesh: making the system not just well-structured, but robust,
observable, and self-correcting.
