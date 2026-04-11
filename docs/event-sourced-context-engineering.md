# Event-Sourced Context Engineering

The LLM context window is a materialized view. Every harness rebuilds it
ad hoc each turn -- concatenating system prompts, tool results, conversation
history, and hoping it fits. Event sourcing gives us principled primitives
for managing what goes in, what stays, and what gets pruned.

## The Core Analogy

| Event Sourcing Concept | Context Engineering Equivalent |
|---|---|
| **Event log** | Full transcript of everything that happened (user messages, tool calls, agent responses, inter-agent messages) |
| **Materialized view** | The context window sent to the LLM on each turn |
| **Projection function** | The logic that builds the prompt from events |
| **Snapshot / compaction** | Summarizing older events into a compact representation |
| **Rollup** | Aggregating many fine-grained events into one coarser summary |
| **Consumer group** | Each agent maintaining its own read position / context window |
| **Retention policy** | Rules for what stays in context and what gets pruned |
| **Event priority / type** | Which events matter more for context (user messages > tool outputs > system chatter) |

## What the Context Window Actually Contains

Every turn, the harness assembles a context window from multiple event
streams:

```
┌─────────────────────────────────────────────────┐
│ CONTEXT WINDOW (materialized view)              │
│                                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ System prompt (stable prefix)               │ │
│ │ - Skill file / personality                  │ │
│ │ - Tool descriptions                         │ │
│ │ - Agent awareness                           │ │
│ └─────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────┐ │
│ │ Data context (changes per request)          │ │
│ │ - Reading list summary / stats              │ │
│ │ - Recent activity from event log            │ │
│ │ - User preferences                          │ │
│ └─────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────┐ │
│ │ Conversation history (changes per turn)     │ │
│ │ - Older turns: ROLLED UP / summarized       │ │
│ │ - Recent turns: full fidelity               │ │
│ │ - Current turn: user message + tool results │ │
│ └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

Each section is a **projection** of an underlying event stream. The
projection function decides fidelity, compression, and ordering.

## Event Rollups for Context Pruning

The key insight: **older context should be more compressed than recent
context**, and rollups are the mechanism.

### What a Rollup Is

In event sourcing, a rollup replaces N fine-grained events with one
coarser summary event that preserves the important state changes while
discarding the details.

For context engineering, this means:

```
Raw events (turn-by-turn):
  [user: "show my books"]
  [tool: list_books → {14 books, full JSON...}]
  [assistant: <table with 14 rows...>]
  [user: "rate Dune 5 stars"]
  [tool: update_book → {id:1, rating:5}]
  [assistant: "Updated Dune to 5/5"]
  [user: "recommend something similar"]
  [tool: list_books → {14 books again...}]
  [agent→recommender: "suggest books like Dune"]
  [recommender→agent: "Try Hyperion, Left Hand of Darkness..."]
  [assistant: <recommendation card HTML>]

Rolled up (for context window):
  [summary: "User viewed 14 books, rated Dune 5/5, got recommendations
   (Hyperion, Left Hand of Darkness). Currently reading: Dune, Project
   Hail Mary, Piranesi."]
```

The rollup preserves **what matters** (state changes, decisions, key
data points) while discarding **what doesn't** (repeated list_books
JSON, intermediate HTML, routing details).

### Rollup Tiers

Different event ages get different compression levels:

```
Tier 0 (current turn):     Full fidelity. Every token preserved.
Tier 1 (last 3-5 turns):   Full fidelity. User needs recent context.
Tier 2 (turns 6-15):       Rolled up per-turn. "User asked X, got Y."
Tier 3 (turns 16+):        Rolled up per-session. "Session summary: ..."
Tier 4 (previous sessions): Rolled up to preferences/patterns only.
```

This is exactly how memory works: vivid recent recall, compressed
older memories, abstract patterns from long ago.

### Rollup as a Projection Function

```python
class ContextProjector:
    """Project events into a context window with tiered rollups."""

    def project(self, events: list[Event], budget_tokens: int) -> str:
        """Build context window from events within a token budget."""

        # Stable prefix (always included, cached)
        prefix = self.build_stable_prefix()

        # Data context (latest snapshot + recent data events)
        data_ctx = self.build_data_context(events)

        # Conversation: tiered rollups based on age and budget
        remaining = budget_tokens - count_tokens(prefix) - count_tokens(data_ctx)
        conversation = self.build_conversation_context(events, remaining)

        return f"{prefix}\n\n{data_ctx}\n\n{conversation}"

    def build_conversation_context(self, events: list, budget: int) -> str:
        turns = self.group_into_turns(events)
        sections = []

        for i, turn in enumerate(reversed(turns)):
            age = len(turns) - i  # 1 = most recent

            if age <= 5:
                # Tier 1: full fidelity
                section = self.render_turn_full(turn)
            elif age <= 15:
                # Tier 2: per-turn rollup
                section = self.rollup_turn(turn)
            else:
                # Tier 3+: accumulate for session rollup
                continue  # handled below

            if count_tokens('\n'.join(sections) + section) > budget:
                break
            sections.append(section)

        # Tier 3: summarize everything older than what fit
        old_turns = turns[:len(turns) - len(sections)]
        if old_turns:
            summary = self.rollup_session(old_turns)
            sections.append(f"[Earlier in this session: {summary}]")

        return '\n'.join(reversed(sections))

    def rollup_turn(self, turn: list[Event]) -> str:
        """Compress a turn to its essential state change."""
        user_msg = next((e for e in turn if e.type == 'user'), None)
        tools_called = [e.tool_name for e in turn if e.type == 'tool_use']
        state_changes = [e for e in turn if e.type == 'state_change']

        parts = []
        if user_msg:
            parts.append(f"User: {user_msg.text[:100]}")
        if tools_called:
            parts.append(f"Tools: {', '.join(tools_called)}")
        if state_changes:
            changes = '; '.join(e.summary for e in state_changes)
            parts.append(f"Changes: {changes}")

        return ' | '.join(parts)
```

### Rollup Strategies by Event Type

Not all events compress equally. Some are more important to retain:

| Event Type | Rollup Strategy | Why |
|---|---|---|
| **User messages** | Keep verbatim in Tier 1-2, summarize intent in Tier 3+ | User intent is the most important context signal |
| **Tool calls (read)** | Drop results, keep "called X" | Read results are stale; the data has been seen |
| **Tool calls (write)** | Keep as state changes | Mutations matter -- "rated Dune 5/5" is permanent context |
| **Tool results (large)** | Drop entirely after Tier 1 | The 14-book JSON blob is the #1 context bloat source |
| **Agent responses (HTML)** | Drop HTML, keep summary | "Showed book list table" vs. 200 lines of HTML |
| **Inter-agent messages** | Summarize delegation chain | "Asked recommender, got 3 suggestions" |
| **System events** | Drop entirely | Rate limits, connection events, etc. -- not useful context |
| **Data snapshots** | Keep latest only, drop previous | Only the current state of the reading list matters |

### The Key Difference from Current Approaches

Current harness approaches to context management:

- **Claude Code's compaction**: Server-side, treats context as opaque text,
  summarizes when approaching token limit. Effective but coarse -- it can't
  know which tool results are stale vs. important.
- **Turn counting**: Reset after N turns. Blunt -- loses everything.
- **Truncation**: Clip long outputs. Preserves recency but loses structure.

Event-sourced rollups are **semantic**: they understand event types, know
which events represent state changes vs. ephemeral reads, and compress
based on meaning rather than position or size.

## Consumer Groups as Per-Agent Context

Each agent needs different context. Event sourcing's consumer groups
model this naturally:

```
Same event stream, different projections:

UI Agent context (needs recent interaction, HTML patterns):
  [latest data snapshot]
  [last 5 turns at full fidelity]
  [rolled-up session summary]

Recommender context (needs reading history, ratings):
  [all books with ratings -- full fidelity, it's small]
  [recent activity summary]
  [user preference events]

Insights context (needs temporal patterns):
  [monthly rollups: "March: added 5 books, finished 2, avg rating 4.1"]
  [genre distribution snapshot]
  [reading velocity trend]
```

Each agent's `ContextProjector` applies different rollup strategies
and retention policies to the same underlying event stream. The UI agent
cares about recent turns; the insights agent cares about long-term trends.

## Rollups as Brooklet Primitives

This maps to concrete brooklet features:

```python
# Define rollup strategies per topic
stream.register_rollup("conversation", strategy=TieredRollup(
    tiers=[
        Tier(age="5 turns", fidelity="full"),
        Tier(age="15 turns", fidelity="per-turn-summary"),
        Tier(age="session", fidelity="session-summary"),
    ]
))

# Each agent consumes with its own projection
ui_context = stream.project(
    topics=["conversation", "books"],
    group="ui-agent",
    budget_tokens=50000,
    rollup="conversation",
)

recommender_context = stream.project(
    topics=["books", "preferences"],
    group="recommender",
    budget_tokens=20000,
    rollup="books-focused",
)
```

### What Brooklet Would Need for This

| Feature | Purpose | Builds On |
|---|---|---|
| **Event type metadata** | Tag events as `user_message`, `tool_call`, `state_change`, etc. | Existing `_src` metadata |
| **Rollup definitions** | Declarative rules for compressing event ranges | New concept |
| **Token-budget-aware projection** | Project events into a string that fits a token budget | New concept -- needs a token counter |
| **Per-consumer projection** | Different rollup strategies per consumer group | Existing consumer groups + rollup definitions |
| **Materialized rollups** | Cache the rolled-up summaries so they're not recomputed every turn | Snapshot markers (already proposed) |

## Connection to Raschka's Components

This reframes every context-related component as an event projection:

| Raschka Component | Event Sourcing Framing |
|---|---|
| **1. Live Repo Context** | Latest snapshot event + recent data-change events |
| **2. Prompt Shape & Cache** | Stable prefix = events that never change. Dynamic part = recent events projected fresh each turn. Cache boundary = snapshot marker. |
| **4. Context Bloat** | Rollups compress old events. Retention policies drop ephemeral events. Token budget caps the materialized view size. |
| **5. Session Memory** | Working memory = latest rollup of the session. Full transcript = the raw event log. Cross-session = events persist across restarts. |

The unifying idea: **context engineering is event stream projection with
a token budget constraint.**

## How This Applies to the Reading Tracker

### Current Flow (no context management)

```
Turn 1: User says "show my books"
  → agent calls list_books → gets 14-book JSON (2000 tokens)
  → generates HTML table (1500 tokens)
  Context: ~4000 tokens

Turn 5: User says "recommend something"
  → Turn 1-4 still in context (~16000 tokens of stale HTML + JSON)
  → agent calls list_books AGAIN → another 2000 tokens
  → calls message_agent(recommender) → 3000 tokens
  Context: ~25000 tokens, mostly stale

Turn 15: User says "what should I read next?"
  → 60000+ tokens of context, 80% is stale tool output and old HTML
  → approaching compaction threshold
  → quality degrades because signal is buried in noise
```

### With Event-Sourced Context

```
Turn 1: User says "show my books"
  → Events: [user_msg, tool:list_books, state:14_books, response:table_html]
  → Context: 4000 tokens (same)

Turn 5: User says "recommend something"
  → Turns 1-4 rolled up: "User viewed books, rated Dune 5/5, updated status"
  → Rollup: ~200 tokens (vs 16000 stale)
  → Fresh data context from latest snapshot: ~500 tokens
  → Current turn at full fidelity: ~3000 tokens
  → Context: ~4000 tokens (vs 25000)

Turn 15: User says "what should I read next?"
  → Session rollup: ~300 tokens
  → Recent 5 turns: ~5000 tokens
  → Data snapshot: ~500 tokens
  → Context: ~6000 tokens (vs 60000+)
  → Signal-to-noise ratio stays high
```

### Implementation Sketch for This Project

```python
# app/context.py

class ReadingTrackerContextProjector:
    """Event-sourced context builder for reading tracker agents."""

    def __init__(self, agent_name: str, token_budget: int = 50000):
        self.agent_name = agent_name
        self.token_budget = token_budget

    async def build_context(self, events: list[dict]) -> str:
        """Project events into agent context within token budget."""

        # 1. Stable prefix (cached, not from events)
        prefix = self._load_skill_file()

        # 2. Data context (from latest data-change events)
        data_ctx = self._project_data_context(events)

        # 3. Conversation (tiered rollups)
        remaining = self.token_budget - self._count(prefix) - self._count(data_ctx)
        conversation = self._project_conversation(events, remaining)

        return f"{prefix}\n\n{data_ctx}\n\n{conversation}"

    def _project_data_context(self, events: list[dict]) -> str:
        """Find latest snapshot or replay recent state-change events."""
        # Find most recent snapshot event
        snapshots = [e for e in events if e.get('action') == 'snapshot']
        if snapshots:
            return self._format_snapshot(snapshots[-1])

        # Fall back to replaying state changes
        state_events = [e for e in events if e.get('type') == 'state_change']
        return self._summarize_state_events(state_events)

    def _project_conversation(self, events: list[dict], budget: int) -> str:
        """Tiered rollups of conversation events."""
        conv_events = [e for e in events if e.get('type') in
                       ('user_message', 'tool_call', 'assistant_response')]
        turns = self._group_into_turns(conv_events)

        # Recent turns: full fidelity
        recent = turns[-5:]
        recent_text = '\n'.join(self._render_full(t) for t in recent)

        # Older turns: rolled up
        older = turns[:-5]
        if older and self._count(recent_text) < budget:
            rollup = self._rollup_turns(older)
            return f"[Earlier: {rollup}]\n\n{recent_text}"

        return recent_text
```

## The Bigger Picture

This idea -- event-sourced context engineering -- isn't specific to the
reading tracker. It's a general pattern for any agent harness:

1. **Every agent interaction is an event** (user message, tool call,
   response, delegation, state change)
2. **The context window is a materialized view** projected from those events
3. **Rollups are the compaction mechanism** (tiered by age, typed by
   importance, bounded by token budget)
4. **Each agent gets its own projection** of the same event stream
   (consumer groups)
5. **Snapshots are cache boundaries** (everything before the snapshot
   is pre-computed; everything after is fresh)

If brooklet can express these primitives natively, it becomes not just
"SQLite of event streaming" but potentially "SQLite of context engineering."
