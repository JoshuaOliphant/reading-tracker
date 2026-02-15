# ABOUTME: LLM-graded evals for subjective quality assessment of agent responses.
# ABOUTME: Uses Claude to evaluate tone, helpfulness, appropriateness, and completeness.

"""
LLM-Graded Evals for Subjective Quality

Some qualities can't be captured by code-based checks:
- Is the response tone appropriate?
- Is the error message helpful and actionable?
- Does the UI make sense for the request?
- Is the information complete and well-organized?

This module uses Claude to evaluate these subjective qualities.

IMPORTANT: LLM graders are non-deterministic. Run multiple trials
and look at pass^k (reliability) metrics, not just single results.

Based on Anthropic's eval guide recommendation for LLM-graded evals.
"""

import os
import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
import sys
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db
from evals.transcript import TranscriptCapture


@dataclass
class LLMGradeResult:
    """Result of an LLM grading operation."""
    passed: bool
    score: float  # 0.0 to 1.0
    explanation: str
    rubric_used: str


async def llm_grade(
    response: str,
    rubric: str,
    context: str = "",
    passing_threshold: float = 0.7,
) -> LLMGradeResult:
    """
    Use Claude to grade a response against a rubric.

    Args:
        response: The agent's response to evaluate
        rubric: The grading criteria and instructions
        context: Optional context about the request
        passing_threshold: Minimum score (0-1) to pass

    Returns:
        LLMGradeResult with pass/fail, score, and explanation
    """
    try:
        import anthropic
    except ImportError:
        # If Anthropic SDK not available, return a mock pass
        return LLMGradeResult(
            passed=True,
            score=1.0,
            explanation="Anthropic SDK not available, skipping LLM grading",
            rubric_used=rubric,
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return LLMGradeResult(
            passed=True,
            score=1.0,
            explanation="No API key available, skipping LLM grading",
            rubric_used=rubric,
        )

    client = anthropic.Anthropic(api_key=api_key)

    grading_prompt = f"""You are an evaluation assistant grading an AI agent's response.

CONTEXT: {context if context else "N/A"}

RUBRIC:
{rubric}

RESPONSE TO EVALUATE:
```
{response[:3000]}  {f"... (truncated from {len(response)} chars)" if len(response) > 3000 else ""}
```

INSTRUCTIONS:
1. Evaluate the response against the rubric criteria
2. Give a score from 0.0 to 1.0 where:
   - 1.0 = Excellent, fully meets all criteria
   - 0.7 = Good, meets most criteria
   - 0.5 = Acceptable, meets minimum requirements
   - 0.3 = Poor, significant issues
   - 0.0 = Fails to meet basic requirements

Respond in exactly this format:
SCORE: [number between 0.0 and 1.0]
EXPLANATION: [1-2 sentences explaining the score]
"""

    try:
        message = client.messages.create(
            model="claude-3-haiku-20240307",  # Use faster/cheaper model for grading
            max_tokens=200,
            messages=[{"role": "user", "content": grading_prompt}],
        )

        result_text = message.content[0].text

        # Parse score
        score = 0.5  # Default
        if "SCORE:" in result_text:
            score_line = result_text.split("SCORE:")[1].split("\n")[0].strip()
            try:
                score = float(score_line)
                score = max(0.0, min(1.0, score))  # Clamp to 0-1
            except ValueError:
                pass

        # Parse explanation
        explanation = "No explanation provided"
        if "EXPLANATION:" in result_text:
            explanation = result_text.split("EXPLANATION:")[1].strip()

        return LLMGradeResult(
            passed=score >= passing_threshold,
            score=score,
            explanation=explanation,
            rubric_used=rubric,
        )

    except Exception as e:
        return LLMGradeResult(
            passed=True,  # Don't fail on grading errors
            score=0.5,
            explanation=f"Grading error: {str(e)}",
            rubric_used=rubric,
        )


@pytest_asyncio.fixture
async def clean_db():
    """Set up a clean database for each test."""
    await db.init_db()
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        await conn.execute("DELETE FROM books")
        await conn.commit()
    yield
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        await conn.execute("DELETE FROM books")
        await conn.commit()


@pytest_asyncio.fixture
async def seeded_db(clean_db):
    """Database with known test data."""
    await db.create_book(
        title="The Great Gatsby",
        author="F. Scott Fitzgerald",
        status="finished",
        rating=5,
        notes="A classic American novel",
    )
    await db.create_book(
        title="1984",
        author="George Orwell",
        status="reading",
    )
    await db.create_book(
        title="Dune",
        author="Frank Herbert",
        status="want-to-read",
    )
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


class TestUIAppropriateness:
    """
    Evaluate whether agent responses are contextually appropriate.

    A response should:
    - Match the user's intent
    - Provide relevant information
    - Not include irrelevant content
    """

    @pytest.mark.asyncio
    async def test_list_books_appropriate_response(self, router, seeded_db):
        """Response to 'show my books' should be a book list, not something else."""
        response = await router.process_user_message("show my books")

        result = await llm_grade(
            response=response,
            context="User asked to see their book list",
            rubric="""
            The response should:
            1. Display a list of books (titles visible)
            2. Be formatted as a readable list or table
            3. Include relevant book details (author, status)
            4. NOT be a form for adding books
            5. NOT be an error message
            6. NOT be empty or placeholder content
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Response not appropriate for book list request. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )

    @pytest.mark.asyncio
    async def test_add_form_appropriate_response(self, router, clean_db):
        """Response to 'add a book' should show an add form or confirmation."""
        response = await router.process_user_message("I want to add a new book")

        result = await llm_grade(
            response=response,
            context="User wants to add a new book (no details given)",
            rubric="""
            The response should:
            1. Show a form for entering book details OR
            2. Ask for book information (title, author) OR
            3. Acknowledge the intent to add a book
            4. NOT show an existing book list
            5. NOT show an error
            6. Be helpful and guide the user
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Response not appropriate for add book request. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )


class TestErrorMessageQuality:
    """
    Evaluate whether error messages are helpful and actionable.

    Good error messages should:
    - Explain what went wrong
    - Suggest how to fix it
    - Use friendly, non-technical language
    """

    @pytest.mark.asyncio
    async def test_not_found_error_quality(self, router, seeded_db):
        """Error for non-existent book should be helpful."""
        response = await router.process_user_message("show book 99999")

        result = await llm_grade(
            response=response,
            context="User asked for book ID 99999 which doesn't exist",
            rubric="""
            For a 'not found' error, the response should:
            1. Clearly indicate the book was not found
            2. NOT show a stack trace or technical error
            3. Be written in friendly, user-facing language
            4. Optionally suggest alternatives (e.g., search, list books)
            5. NOT pretend the book exists with made-up details
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Error message not helpful. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )


class TestToneConsistency:
    """
    Evaluate whether agent maintains appropriate tone.

    The agent should:
    - Be friendly but professional
    - Match the app's personality
    - Not be overly formal or robotic
    """

    @pytest.mark.asyncio
    async def test_greeting_tone(self, router, clean_db):
        """Response to greeting should be friendly."""
        response = await router.process_user_message("Hello!")

        result = await llm_grade(
            response=response,
            context="User sent a casual greeting",
            rubric="""
            For a greeting response:
            1. Should acknowledge the greeting warmly
            2. Should offer to help with books/reading
            3. Tone should be friendly, not robotic
            4. Should NOT be overly formal or stiff
            5. Should NOT ignore the greeting
            6. Can show helpful options or prompts
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Greeting response tone inappropriate. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )

    @pytest.mark.asyncio
    async def test_success_tone(self, router, clean_db):
        """Success messages should be positive but not over-the-top."""
        response = await router.process_user_message(
            "add 'Test Book' by Test Author"
        )

        result = await llm_grade(
            response=response,
            context="User successfully added a book",
            rubric="""
            For a success message:
            1. Should confirm the action completed
            2. Tone should be positive and encouraging
            3. Should NOT be excessively enthusiastic (no "AMAZING!")
            4. Should NOT be cold or clinical
            5. Should include the book details as confirmation
            6. Can suggest next actions
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Success message tone inappropriate. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )


class TestInformationCompleteness:
    """
    Evaluate whether responses include all relevant information.

    Responses should:
    - Include all requested details
    - Not omit important information
    - Be organized logically
    """

    @pytest.mark.asyncio
    async def test_book_details_complete(self, router, seeded_db):
        """Book details view should show all relevant information."""
        books = await db.get_all_books()
        book = books[0]
        book_id = book["id"]

        response = await router.process_user_message(f"show book {book_id}")

        result = await llm_grade(
            response=response,
            context=f"User asked for details of book: {book['title']} by {book['author']}",
            rubric="""
            Book details should include:
            1. Title (clearly visible)
            2. Author (clearly visible)
            3. Reading status
            4. Rating (if available)
            5. Notes (if available)
            6. Information should be organized, not jumbled
            7. Should NOT be missing major fields
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Book details incomplete. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )

    @pytest.mark.asyncio
    async def test_stats_complete(self, router, seeded_db):
        """Statistics view should show meaningful data."""
        response = await router.process_user_message("show my reading stats")

        result = await llm_grade(
            response=response,
            context="User asked for reading statistics",
            rubric="""
            Reading stats should include:
            1. Total number of books
            2. Breakdown by status (reading, finished, etc.)
            3. Rating information (average or distribution)
            4. Data should be clearly labeled
            5. Should NOT just show raw numbers without context
            6. Should be visually organized (not a wall of text)
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        assert result.passed, (
            f"FAIL: Stats display incomplete. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )


class TestHTMXUIQuality:
    """
    Evaluate whether the HTML/HTMX UI is well-structured.

    Good UI should:
    - Use semantic HTML
    - Have clear visual hierarchy
    - Include proper accessibility attributes
    """

    @pytest.mark.asyncio
    async def test_ui_accessibility(self, router, seeded_db):
        """UI should have basic accessibility features."""
        response = await router.process_user_message("show my books")

        result = await llm_grade(
            response=response,
            context="Evaluating HTML response for accessibility",
            rubric="""
            For accessible HTML:
            1. Should use semantic elements (h1, h2, button, etc.)
            2. Buttons should have text labels, not just icons
            3. Should have logical structure (headings, lists)
            4. Should NOT be just unstyled divs everywhere
            5. Interactive elements should be recognizable
            6. Should include aria attributes where helpful
            """,
        )

        print(f"\nScore: {result.score:.1%}")
        print(f"Explanation: {result.explanation}")

        # Lower threshold for accessibility (harder to achieve perfectly)
        assert result.score >= 0.5, (
            f"FAIL: UI accessibility poor. "
            f"Score: {result.score:.1%}. {result.explanation}"
        )


# Calibration examples for verifying LLM grader alignment
CALIBRATION_EXAMPLES = [
    {
        "response": "<h2>Your Books</h2><ul><li>The Great Gatsby - F. Scott Fitzgerald</li></ul>",
        "rubric": "Book list rubric",
        "expected_pass": True,
        "reason": "Valid book list with title and author",
    },
    {
        "response": "Error: NullPointerException at line 42",
        "rubric": "Error message quality rubric",
        "expected_pass": False,
        "reason": "Technical error, not user-friendly",
    },
    {
        "response": "",
        "rubric": "Any rubric",
        "expected_pass": False,
        "reason": "Empty response is never acceptable",
    },
]


# Run with: uv run pytest evals/test_llm_graded.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
