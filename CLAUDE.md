# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the application (requires ANTHROPIC_API_KEY in .env or exported)
uv run uvicorn app.main:app --reload

# Run all tests
uv run pytest

# Run message passing evaluation tests
uv run pytest evals/test_message_passing.py -v -s
```

## Architecture

This is a **hexagonal agent application** implementing a multi-agent system with message passing between AI agents acting as "prompt objects."

### Request Flow

```
Browser (HTMX) → FastAPI (/agent) → SavedViewsManager (fast path)
                                 → AgentRouter (slow path) → UI Agent
                                                          → Recommender Agent
                                                          → Insights Agent
```

1. **Fast path**: `SavedViewsManager.find_matching_view()` checks for cached user-saved views
2. **Slow path**: `AgentRouter.process_user_message()` routes to UI agent, which may delegate to specialists

### Multi-Agent System (`app/agents/`)

- **AgentRouter** (`router.py`): Coordinates agents, routes inter-agent messages, maintains MessageLog for debugging
- **BaseAgent** (`base_agent.py`): Abstract base providing `message_agent` tool for inter-agent communication
- **UIAgent** (`ui_agent.py`): Handles user interaction, generates HTML, coordinates specialists
- **RecommenderAgent** (`recommender_agent.py`): Book recommendations based on reading history
- **InsightsAgent** (`insights_agent.py`): Analyzes reading patterns and behavior

Agents communicate via semantic messages, not method calls. The `message_agent` tool routes through the router:
```python
await router.route_agent_message(from_agent="ui", to_agent="recommender", message="...")
```

### Tools (`app/tools.py`)

MCP tool definitions for book CRUD operations. Each tool returns structured JSON that agents transform into HTML. Tools: `list_books`, `get_book`, `create_book`, `update_book`, `delete_book`, `search_books`, `get_stats`.

### Skill Files (`app/skills/`)

Markdown files defining agent personalities and UI generation rules:
- `ui.md`: HTML component patterns, HTMX integration, design system
- `recommender.md`: Recommendation strategy and tone
- `insights.md`: Pattern analysis approach

### Saved Views (`app/saved_views.py`)

Progressive UI caching system. Users can save agent-generated views for instant loading:
- Exact phrase match (highest priority) or keyword match (fallback)
- Dynamic views inject fresh data on load via `{{placeholder}}` syntax

### HTTP Adapter (`app/main.py`)

FastAPI endpoints with HTMX integration:
- `GET /` - Main page with BASE_TEMPLATE shell
- `POST /agent` - Message processing (checks saved views first)
- `GET /views/list`, `POST /views/save`, `GET /views/load/{id}` - View management
- `GET /debug/messages`, `GET /debug/agents`, `GET /debug/views` - Debug endpoints

## Data Storage

SQLite database and JSON in `data/`:
- `data/reading_list.db` - SQLite database for books (ACID-compliant persistence)
- `data/saved_views.json` - Cached UI views

## Evaluations

Comprehensive eval suite following [Anthropic's eval guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

### Running Evals

```bash
# All evals (graders + transcript unit tests run fast; agent tests take ~20min)
uv run pytest evals/ -v

# Grader and transcript unit tests (fast, no LLM calls)
uv run pytest evals/test_graders.py evals/test_transcript.py -v

# Tool usage and consistency
uv run pytest evals/test_tool_usage.py -v
uv run pytest evals/test_tool_consistency.py -v -s

# Negative test cases (what agent should NOT do)
uv run pytest evals/test_negative_cases.py -v -s

# Complex multi-step tasks with partial credit scoring
uv run pytest evals/test_complex_tasks.py -v -s

# LLM-graded subjective quality evals (requires ANTHROPIC_API_KEY in .env)
uv run pytest evals/test_llm_graded.py -v -s

# Dataset-driven evals from declarative case definitions
uv run pytest evals/test_dataset_driven.py -v -s

# LLM grader calibration (standalone script, not pytest)
uv run python evals/calibrate_llm_grader.py

# Enable transcript capture to disk
CAPTURE_TRANSCRIPTS=1 uv run pytest evals/test_tool_usage.py -v -s
```

### Eval Architecture

| Component | File(s) | Purpose |
|-----------|---------|---------|
| **Transcript Capture** | `evals/transcript.py` | Records tool calls, agent messages, DB state before/after, timing |
| **Reusable Graders** | `evals/graders.py` | `StateCheck`, `ToolWasCalled`, `ToolNotCalled`, `HTMLContains`, `PartialCredit`, `CompositeGrader` |
| **Declarative Cases** | `evals/datasets/crud_cases.py` | `Case` and `Dataset` classes for data-driven test definitions |
| **LLM Grading** | `evals/test_llm_graded.py` | Claude-based subjective quality assessment with calibration examples |
| **Calibration** | `evals/calibrate_llm_grader.py` | Validates LLM grader against 10 hand-labeled examples (target: >90% agreement) |
| **Shared Fixtures** | `evals/conftest.py` | DB isolation, router instances, transcript capture, `.env` loading |

### Eval Principles

- **State-based outcomes**: Verify database state, not agent UI claims
- **Tool usage verification**: Assert tools are actually called, not just plausible UI generated
- **pass@k / pass^k**: Reliability metrics across k trials (configurable via `EVAL_TRIALS` env)
- **Negative testing**: Verify agent asks for clarification, doesn't hallucinate, doesn't expose internals
- **Partial credit**: Multi-step tasks scored 0.0-1.0 with weighted steps, not just pass/fail
- **LLM grading**: Subjective quality (tone, helpfulness, accessibility) graded by Claude with calibrated rubrics
- **Per-test isolation**: Fresh database state per test via `clean_db`/`seeded_db` fixtures

## Key Patterns

- **All code files start with 2-line ABOUTME comments** explaining the file's purpose
- **Agents output raw HTML** (skill files enforce "never use markdown code fences")
- **HTMX attributes** (`hx-post`, `hx-target`, `hx-vals`, `hx-indicator`) drive UI interactions
- **Tool responses** are structured JSON; agents transform data into HTML presentation
