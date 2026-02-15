# reading-list

**A test application exploring the hexagonal agent architecture pattern** -- where AI agents dynamically generate HTMX UI through a ports-and-adapters design.

This is an experimental project for validating the idea that LLM agents can serve as the core application logic in a hexagonal architecture, producing HTML directly while tools handle data operations. The reading list app itself is intentionally simple; the interesting parts are the agent coordination patterns and the comprehensive eval suite built on [Anthropic's agent eval best practices](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).

## Setup

```bash
# Install dependencies
uv sync

# Set API key
export ANTHROPIC_API_KEY=your_key_here

# Run the application
uv run uvicorn app.main:app --reload
```

Open http://localhost:8000 in your browser.

## Architecture

This application uses the hexagonal (ports-and-adapters) pattern with a multi-agent system:

- **Agents** (`app/agents/`): Multi-agent system with message passing
  - `router.py`: Coordinates agents, routes inter-agent messages
  - `ui_agent.py`: Handles user interaction, generates HTML
  - `recommender_agent.py`: Book recommendations
  - `insights_agent.py`: Reading pattern analysis
- **Tools** (`app/tools.py`): Data operations (CRUD)
- **Database** (`app/database.py`): SQLite persistence layer
- **HTTP Adapter** (`app/main.py`): FastAPI endpoints with HTMX
- **Skill Files** (`app/skills/`): Agent personalities and UI patterns

## Evaluations

Following [Anthropic's eval guide](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents), this project includes comprehensive agent evaluations.

### Running Evals

```bash
# Run all evals
uv run pytest evals/ -v

# Run specific eval suites
uv run pytest evals/test_tool_usage.py -v      # Tool call verification
uv run pytest evals/test_negative_cases.py -v  # Safety behaviors
uv run pytest evals/test_complex_tasks.py -v   # Multi-step tasks with partial credit
uv run pytest evals/test_consistency.py -v     # pass@k/pass^k metrics

# Enable transcript capture for debugging
CAPTURE_TRANSCRIPTS=1 uv run pytest evals/ -v
```

### Eval Types

| Eval Type | File | Purpose |
|-----------|------|---------|
| Tool Usage | `test_tool_usage.py` | Verify agents call tools, not just generate plausible UI |
| Consistency | `test_tool_consistency.py` | Measure reliability with pass@k/pass^k metrics |
| Negative Cases | `test_negative_cases.py` | Test what agents should NOT do |
| Complex Tasks | `test_complex_tasks.py` | Partial credit scoring for multi-step workflows |
| LLM-Graded | `test_llm_graded.py` | Claude evaluates tone, completeness, appropriateness |
| Dataset-Driven | `test_dataset_driven.py` | Declarative test cases using pydantic-evals patterns |

### Key Principles

1. **State-based outcomes**: Verify database state, not agent UI claims
2. **Tool verification**: Assert tools are called, not just UI generated
3. **Partial credit**: Score complex tasks step-by-step (not just pass/fail)
4. **Negative testing**: Test what agents should NOT do
5. **Feedback loop**: Use eval failures to improve agent prompts

### Transcript Capture

For debugging eval failures, enable transcript capture:

```bash
CAPTURE_TRANSCRIPTS=1 uv run pytest evals/test_negative_cases.py -v
```

Transcripts are saved to `data/eval_transcripts/` and include:
- Tool calls with arguments and results
- Inter-agent message flow
- Database state before/after
- Timing information

### Eval Feedback Loop

Evals create a feedback loop for improving agent behavior:

```
1. Run evals → Discover failures
2. Analyze transcripts → Understand what went wrong
3. Update agent prompts → Add missing guidance
4. Re-run evals → Verify improvement
5. Commit both → Eval + prompt changes together
```

### Reusable Graders

The `evals/graders.py` module provides composable grading functions:

```python
from evals.graders import StateCheck, ToolWasCalled, PartialCredit, Step

# Verify database state
grader = StateCheck("books", count_change=1)

# Verify tool was called
grader = ToolWasCalled("create_book")

# Partial credit for multi-step tasks
grader = PartialCredit([
    Step("book_created", StateCheck("books", count_change=1), weight=0.4),
    Step("tool_called", ToolWasCalled("create_book"), weight=0.3),
    Step("ui_success", HTMLContains(["success"]), weight=0.3),
])
```

## Development

```bash
# Run tests
uv run pytest

# Run specific test file
uv run pytest evals/test_negative_cases.py -v -s

# Type checking (if configured)
uv run mypy app/
```

## Project Structure

```
reading-list/
├── app/
│   ├── agents/          # Multi-agent system
│   ├── skills/          # Agent personality/prompt files
│   ├── database.py      # SQLite persistence
│   ├── tools.py         # CRUD operations
│   └── main.py          # FastAPI endpoints
├── evals/
│   ├── datasets/        # Declarative test cases
│   ├── graders.py       # Reusable grading functions
│   ├── transcript.py    # Trial capture system
│   ├── conftest.py      # Shared fixtures
│   └── test_*.py        # Evaluation tests
└── data/
    ├── reading_list.db  # SQLite database
    └── eval_transcripts/ # Captured transcripts (when enabled)
```
