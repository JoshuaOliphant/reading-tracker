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

Following [Anthropic's eval guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents):

```bash
# Basic tool usage tests
uv run pytest evals/test_tool_usage.py -v

# Consistency tests with pass@k/pass^k metrics
uv run pytest evals/test_tool_consistency.py -v -s

# Run single scenario
uv run pytest "evals/test_tool_consistency.py::TestListBooksConsistency::test_list_books_consistency[basic_show]" -v -s
```

Eval principles:
- **State-based outcomes**: Verify database state, not agent UI claims
- **Tool usage verification**: Assert tools are actually called, not just plausible UI generated
- **pass@k**: Probability of at least 1 success across k trials
- **pass^k**: Probability ALL k trials succeed (reliability metric for production)

## Key Patterns

- **All code files start with 2-line ABOUTME comments** explaining the file's purpose
- **Agents output raw HTML** (skill files enforce "never use markdown code fences")
- **HTMX attributes** (`hx-post`, `hx-target`, `hx-vals`, `hx-indicator`) drive UI interactions
- **Tool responses** are structured JSON; agents transform data into HTML presentation
