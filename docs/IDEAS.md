# Ideas Index

A consolidated view of harness engineering ideas for the reading-tracker,
linking to detailed docs and tracking implementation status.

## Guiding Metaphor

The **reading list is this project's equivalent of a code repository.**
A coding agent has git status, file trees, and recent commits as context.
Our agents have book counts, statuses, ratings, and recent reading activity.
Harness engineering is what turns that raw context into useful agent behavior.

**Reference**: Raschka, ["Components of a Coding Agent"](https://magazine.sebastianraschka.com/p/components-of-a-coding-agent) (April 2025)
-- see [raschka-coding-agent-components.md](raschka-coding-agent-components.md)

---

## Storage Architecture

### Current: Three Independent Layers

| Layer | Tool | Purpose | Status |
|---|---|---|---|
| **Query engine** | SQLite | Fast reads, ACID writes, `WHERE` clauses | Implemented (`app/database.py`) |
| **State history** | Git (pygit2) | Snapshots, diffs, branches, undo | Implemented (`app/git_audit.py`) |
| **Event stream** | Brooklet | Individual events, consumer groups, agent session integration | Documented, not implemented |

### Future Vision: Unified Event Sourcing

The three layers aren't peers -- they're one source of truth and two projections:

```
Current:    SQLite (truth) → git (mirror) → brooklet (mirror)
Future:     Brooklet events (truth) → SQLite (materialized view)
                                    → Git snapshots (materialized view)
```

In this model, brooklet's JSONL event log is the only write path. SQLite
is a **materialized view** rebuilt by replaying events (delete the `.db`,
reconstruct from the log). Git snapshots are periodic compaction points
for diffs and branching. Every feature currently split across three tools
(queries, history, diffs, undo, consumer groups) maps to event primitives:

- **Snapshots** = compaction (skip-to-snapshot, archive old events)
- **Diffs** = compare event ranges or snapshots
- **Branches** = fork the event stream
- **Undo** = append a compensating event, reproject
- **Queries** = SQLite projection (same `WHERE` clauses, derived state)

**Evolutionary path**: add brooklet as a mirror first, verify parity, then
gradually invert the architecture. Each step is independently useful and
reversible.

Details: [git-as-user-state-store.md](git-as-user-state-store.md) > "Option E: Unified Event Sourcing"

---

## Harness Components (Raschka's 6)

Mapped to this project with current status and next action.

| # | Component | Project Status | Key Gap | Next Action |
|---|---|---|---|---|
| 1 | **Live Repo Context** | Git audit log provides history; no agent injection yet | Agents start blind every request | Implement `_build_data_context()` in BaseAgent (Step 4) |
| 2 | **Prompt Shape & Cache** | Skill files are a stable prefix | No stable/dynamic split; no cache metrics | Split `_build_system_prompt()` into stable + dynamic (Step 6) |
| 3 | **Tool Access & Use** | 7 MCP tools + `message_agent`; validation in tools | No approval gating; no output clipping | Add SDK hooks for logging + delete confirmation (Step 3) |
| 4 | **Context Bloat** | None | No compaction, no token budget, no dedup | Enable `max_turns` + `max_budget_usd` (Step 1); compaction beta (Step 5) |
| 5 | **Session Memory** | Conversation context is ephemeral | No cross-session persistence; no working memory | Add `user_preferences` table + tools (Step 7) |
| 6 | **Delegation** | Custom multi-agent routing via `AgentRouter` | Subagents have identical permissions; no scoping | Compare SDK `AgentDefinition` vs custom routing (Step 8) |

Details: [harness-improvements.md](harness-improvements.md)

---

## SDK Upgrade Opportunity

Current: `claude-agent-sdk` **v0.1.22** -- Latest: **v0.1.56** (34 versions behind)

Top 5 features to adopt:

| Feature | Version | Harness Component | What It Gives Us |
|---|---|---|---|
| `max_turns` + `max_budget_usd` | existing | Context Bloat | Prevents runaway loops and cost |
| `get_context_usage()` | v0.1.52 | Context Bloat | Know actual context window fill level |
| `AgentDefinition` with `skills`, `memory`, `mcpServers` | v0.1.49 | Delegation | SDK-native subagent scoping |
| `updatedMCPToolOutput` in PostToolUse hooks | v0.1.29 | Context Bloat | Clip tool outputs before LLM sees them |
| `betas=["compact-2026-01-12"]` | v0.1.46+ | Context Bloat | Server-side context compaction |

Full audit: [harness-improvements.md](harness-improvements.md) > "Agent SDK Features: Build vs. Built-In"

---

## Brooklet Integration

[Brooklet](https://github.com/JoshuaOliphant/brooklet) is a JSONL event
streaming library ("the SQLite of event streaming") that complements the
git audit log.

**Why it fits**:
- Consumer groups let each agent (UI, recommender, insights) consume the
  same book-event stream independently at their own pace
- Glob registration can unify app book events with Claude Code session
  JSONL files (`~/.claude/projects/**/*.jsonl`) into one observable stream
- It's the user's own library -- using it here exercises it in a real app

**Why it's not overkill**:
- For the reading tracker alone, slightly overkill (single user, on-demand queries)
- For *learning harness engineering*, exactly right: event sourcing is a
  core harness pattern (Raschka Component 5), and the multi-consumer model
  maps naturally to multi-agent architecture

Details: [git-as-user-state-store.md](git-as-user-state-store.md) > "Option D: Brooklet Event Streaming"

---

## Learning Path

Ordered by learning value -- each step builds on the previous.

### Phase 1: Foundations (SDK adoption, low effort)

- [ ] **Step 1**: SDK guardrails -- `max_turns`, `max_budget_usd`, `thinking`
- [ ] **Step 2**: Observability -- capture `AssistantMessage.usage`, add timing
- [ ] **Step 3**: Hooks -- `PostToolUse` for logging, `PreToolUse` for delete confirmation

### Phase 2: Context Engineering (custom + SDK, medium effort)

- [ ] **Step 4**: Live data context -- `_build_data_context()` in agent system prompts
- [ ] **Step 5**: Server-side compaction -- `betas=["compact-2026-01-12"]`
- [ ] **Step 6**: Prompt cache optimization -- stable/dynamic split

### Phase 3: Advanced Patterns (custom build, higher effort)

- [ ] **Step 7**: Structured session memory -- `user_preferences` table + tools
- [ ] **Step 8**: SDK subagents vs custom routing -- comparison branch
- [ ] **Step 9**: Output validation + self-correction loop

### Already Done

- [x] **Git audit log** -- `app/git_audit.py` mirrors SQLite mutations to git
- [x] **Raschka component mapping** -- full analysis in `docs/harness-improvements.md`
- [x] **SDK feature audit** -- v0.1.22 vs v0.1.56 comparison
- [x] **Brooklet analysis** -- fit assessment and layered storage design
- [x] **Git object model** -- how git stores data internally

---

## Architectural Insight

Three complementary lenses on the same system:

| Lens | Question It Answers | This Project's Strength |
|---|---|---|
| **Hexagonal architecture** | Where does each concern live? (ports, adapters, core) | Strong -- clean tool boundaries, message passing |
| **Harness engineering** | What concerns must exist? (resilience, context, guardrails) | Weak on context (4) and memory (5) |
| **Raschka's coding harness** | What does the model need to succeed? (live context, compact prompts, bounded delegation) | Strong on tools (3) and delegation (6); weak on temporal concerns |

The hexagonal pattern handles *spatial* concerns (where things live).
Harness engineering handles *temporal* concerns (how state evolves across
turns, how context grows and must be compacted, how sessions persist).

The reading-tracker has strong hexagonal bones. The learning path above
fills in the harness flesh.
