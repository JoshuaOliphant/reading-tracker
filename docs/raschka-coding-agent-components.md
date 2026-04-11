# Components of a Coding Agent -- Sebastian Raschka

Source: https://magazine.sebastianraschka.com/p/components-of-a-coding-agent
Date: April 4, 2025

## Key Definitions

- **LLM**: the raw model
- **Reasoning model**: an LLM optimized to output intermediate reasoning traces
  and to verify itself more
- **Agent**: a loop that uses a model plus tools, memory, and environment
  feedback
- **Agent harness**: the software scaffold around an agent that manages context,
  tool use, prompts, state, and control flow
- **Coding harness**: a special case of an agent harness; a task-specific
  harness for software engineering that manages code context, tools, execution,
  and iterative feedback

> "The LLM is the engine, a reasoning model is a beefed-up engine, and an
> agent harness helps us [use] the model."

> "Strictly speaking, the agent is the model-driven decision-making loop,
> while the harness is the surrounding software scaffold that provides
> context, tools, and execution support."

## The Six Components

### 1. Live Repo Context

Collect "stable facts" about the workspace upfront before doing any work:
Git branch, status, project docs (README, AGENTS.md), repo layout. The agent
is not starting from zero on every prompt.

### 2. Prompt Shape and Cache Reuse

Split the prompt into:
- **Stable prefix** (instructions, tool descriptions, workspace summary) --
  cached and reused across turns
- **Changing session state** (short-term memory, recent transcript, latest
  user request) -- rebuilt each turn

Smart runtimes don't rebuild everything as one giant undifferentiated prompt
on every turn.

### 3. Tool Access and Use

Pre-defined list of named tools with clear inputs and boundaries. The flow:
1. Model emits a structured action
2. Harness validates it ("Is this a known tool? Are args valid? Does this
   need approval? Is the path inside the workspace?")
3. Optionally asks for user approval
4. Executes the tool
5. Feeds bounded result back into the loop

> "The harness is giving the model less freedom, but it also improves the
> usability at the same time."

### 4. Minimizing Context Bloat

Two compaction strategies:
- **Clipping**: shorten long snippets, large tool outputs, memory notes,
  transcript entries
- **Transcript reduction/summarization**: compress full session history,
  keeping recent events richer and compressing older events more aggressively

Also: deduplicate older file reads so the model doesn't keep seeing the same
content.

> "A lot of apparent 'model quality' is really context quality."

### 5. Structured Session Memory

Two layers of state:
- **Working memory**: small, distilled, explicitly maintained summary of what
  matters across turns (current task, important files, recent notes)
- **Full transcript**: complete history of user requests, tool outputs, LLM
  responses -- resumable across sessions, stored as JSON on disk

The compact transcript (for prompt reconstruction) and working memory (for
task continuity) have different jobs.

### 6. Delegation with Bounded Subagents

Split side questions into bounded subtasks. The subagent inherits enough
context to be useful but runs inside tighter boundaries (e.g., read-only,
restricted recursion depth, scoped task).

The design problem is not just how to spawn a subagent but how to *bind* one.

## Key Insight

> "Since the vanilla versions of LLMs nowadays have very similar capabilities,
> the harness can often be the distinguishing factor that makes one LLM work
> better than another."

The harness shapes most of the user experience compared to prompting the
model directly. A good coding harness can make a reasoning and non-reasoning
model feel much stronger than it does in a plain chat box.

## Reference Implementation

Mini Coding Agent: https://github.com/rasbt/mini-coding-agent

Six components annotated in code:
1. `WorkspaceContext` -- Live Repo Context
2. `build_prefix`, `memory_text`, `prompt` -- Prompt Shape and Cache Reuse
3. `build_tools`, `run_tool`, `validate_tool`, `approve`, `parse`, `path`,
   `tool_*` -- Structured Tools, Validation, and Permissions
4. `clip`, `history_text` -- Context Reduction and Output Management
5. `SessionStore`, `record`, `note_tool`, `ask`, `reset` -- Transcripts,
   Memory, and Resumption
6. `tool_delegate` -- Delegation and Bounded Subagents
