# ABOUTME: Tests for the reusable grader functions.
# ABOUTME: Verifies StateCheck, ToolWasCalled, HTMLContains, and PartialCredit graders.

"""
Grader Tests

Verifies that each grader correctly evaluates agent behavior.
Uses mock transcripts to test grading logic in isolation.
"""

import pytest
from evals.graders import (
    StateCheck,
    ToolWasCalled,
    ToolNotCalled,
    HTMLContains,
    HTMLNotContains,
    PartialCredit,
    Step,
    NoError,
    ResponseNotEmpty,
    CompositeGrader,
)
from evals.transcript import (
    TrialTranscript,
    ToolCallRecord,
    DatabaseSnapshot,
)


def make_transcript(
    tool_calls: list[dict] | None = None,
    html_response: str = "",
    state_before_books: list[dict] | None = None,
    state_after_books: list[dict] | None = None,
    error: str | None = None,
) -> TrialTranscript:
    """Helper to create mock transcripts for testing."""
    transcript = TrialTranscript(
        trial_id="test_trial",
        timestamp="2024-01-01T00:00:00",
        user_message="test message",
        html_response=html_response,
        error=error,
    )

    if tool_calls:
        for tc in tool_calls:
            transcript.tool_calls.append(
                ToolCallRecord(
                    name=tc["name"],
                    args=tc.get("args", {}),
                    result=tc.get("result"),
                )
            )

    if state_before_books is not None:
        transcript.state_before = DatabaseSnapshot(
            timestamp="2024-01-01T00:00:00",
            books=state_before_books,
            stats={},
        )

    if state_after_books is not None:
        transcript.state_after = DatabaseSnapshot(
            timestamp="2024-01-01T00:00:01",
            books=state_after_books,
            stats={},
        )

    return transcript


class TestStateCheck:
    """Tests for StateCheck grader."""

    @pytest.mark.asyncio
    async def test_passes_with_expected_count(self):
        """StateCheck passes when count matches expected."""
        transcript = make_transcript(
            state_after_books=[
                {"id": 1, "title": "Book 1"},
                {"id": 2, "title": "Book 2"},
            ]
        )

        grader = StateCheck("books", expected_count=2)
        result = await grader.grade(transcript)

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_fails_with_wrong_count(self):
        """StateCheck fails when count doesn't match."""
        transcript = make_transcript(
            state_after_books=[{"id": 1, "title": "Book 1"}]
        )

        grader = StateCheck("books", expected_count=5)
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Expected 5 books, got 1" in result.explanation

    @pytest.mark.asyncio
    async def test_passes_with_count_change(self):
        """StateCheck passes when count change matches."""
        transcript = make_transcript(
            state_before_books=[{"id": 1, "title": "Book 1"}],
            state_after_books=[
                {"id": 1, "title": "Book 1"},
                {"id": 2, "title": "New Book"},
            ],
        )

        grader = StateCheck("books", count_change=1)
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_passes_with_field_check(self):
        """StateCheck passes when field value found."""
        transcript = make_transcript(
            state_after_books=[
                {"id": 1, "title": "The Great Book", "author": "Author A"},
            ]
        )

        grader = StateCheck("books", field_check={"title": "The Great Book"})
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_without_state_after(self):
        """StateCheck fails when no state_after snapshot."""
        transcript = make_transcript()  # No state snapshots

        grader = StateCheck("books", expected_count=1)
        result = await grader.grade(transcript)

        assert not result.passed
        assert "No state_after" in result.explanation


class TestToolWasCalled:
    """Tests for ToolWasCalled grader."""

    @pytest.mark.asyncio
    async def test_passes_when_tool_called(self):
        """ToolWasCalled passes when tool was called."""
        transcript = make_transcript(
            tool_calls=[
                {"name": "get_all_books", "result": []},
            ]
        )

        grader = ToolWasCalled("get_all_books")
        result = await grader.grade(transcript)

        assert result.passed
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_fails_when_tool_not_called(self):
        """ToolWasCalled fails when tool wasn't called."""
        transcript = make_transcript(tool_calls=[])

        grader = ToolWasCalled("create_book")
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Expected at least 1 call" in result.explanation

    @pytest.mark.asyncio
    async def test_checks_minimum_calls(self):
        """ToolWasCalled respects min_calls parameter."""
        transcript = make_transcript(
            tool_calls=[
                {"name": "get_all_books", "result": []},
            ]
        )

        grader = ToolWasCalled("get_all_books", min_calls=2)
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Expected at least 2 call(s)" in result.explanation

    @pytest.mark.asyncio
    async def test_checks_maximum_calls(self):
        """ToolWasCalled respects max_calls parameter."""
        transcript = make_transcript(
            tool_calls=[
                {"name": "get_all_books", "result": []},
                {"name": "get_all_books", "result": []},
                {"name": "get_all_books", "result": []},
            ]
        )

        grader = ToolWasCalled("get_all_books", max_calls=2)
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Expected at most 2 call(s)" in result.explanation


class TestToolNotCalled:
    """Tests for ToolNotCalled grader (negative checks)."""

    @pytest.mark.asyncio
    async def test_passes_when_tool_not_called(self):
        """ToolNotCalled passes when tool wasn't called."""
        transcript = make_transcript(
            tool_calls=[{"name": "get_all_books", "result": []}]
        )

        grader = ToolNotCalled("delete_book")
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_when_tool_called(self):
        """ToolNotCalled fails when tool was called."""
        transcript = make_transcript(
            tool_calls=[{"name": "delete_book", "result": None}]
        )

        grader = ToolNotCalled("delete_book")
        result = await grader.grade(transcript)

        assert not result.passed
        assert "should NOT have been called" in result.explanation


class TestHTMLContains:
    """Tests for HTMLContains grader."""

    @pytest.mark.asyncio
    async def test_passes_when_all_patterns_found(self):
        """HTMLContains passes when all patterns present."""
        transcript = make_transcript(
            html_response='<div class="book">The Great Gatsby</div>'
        )

        grader = HTMLContains(["book", "gatsby"])
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_when_pattern_missing(self):
        """HTMLContains fails when pattern not found."""
        transcript = make_transcript(html_response="<div>Hello World</div>")

        grader = HTMLContains(["book", "missing"])
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Only 0/2 patterns found" in result.explanation

    @pytest.mark.asyncio
    async def test_any_mode_passes_with_one_match(self):
        """HTMLContains with require_all=False passes on any match."""
        transcript = make_transcript(html_response="<div>Book list</div>")

        grader = HTMLContains(["book", "missing"], require_all=False)
        result = await grader.grade(transcript)

        assert result.passed


class TestHTMLNotContains:
    """Tests for HTMLNotContains grader (negative checks)."""

    @pytest.mark.asyncio
    async def test_passes_when_patterns_absent(self):
        """HTMLNotContains passes when forbidden patterns absent."""
        transcript = make_transcript(html_response="<div>Book list</div>")

        grader = HTMLNotContains(["error", "exception", "500"])
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_when_pattern_found(self):
        """HTMLNotContains fails when forbidden pattern found."""
        transcript = make_transcript(html_response="<div>Error: Something went wrong</div>")

        grader = HTMLNotContains(["error"])
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Unexpected patterns found" in result.explanation


class TestPartialCredit:
    """Tests for PartialCredit grader."""

    @pytest.mark.asyncio
    async def test_full_credit_when_all_pass(self):
        """PartialCredit gives full credit when all steps pass."""
        transcript = make_transcript(
            tool_calls=[{"name": "create_book", "result": {"id": 1}}],
            state_before_books=[],
            state_after_books=[{"id": 1, "title": "New Book"}],
        )

        grader = PartialCredit([
            Step("tool_called", ToolWasCalled("create_book"), weight=0.5),
            Step("state_changed", StateCheck("books", count_change=1), weight=0.5),
        ])
        result = await grader.grade(transcript)

        assert result.passed
        assert result.score == 1.0
        assert "2/2 steps" in result.explanation

    @pytest.mark.asyncio
    async def test_partial_credit_when_some_fail(self):
        """PartialCredit gives partial credit when some steps fail."""
        transcript = make_transcript(
            tool_calls=[{"name": "create_book", "result": {"id": 1}}],
            state_before_books=[],
            state_after_books=[],  # No change - step will fail
        )

        grader = PartialCredit([
            Step("tool_called", ToolWasCalled("create_book"), weight=0.5),
            Step("state_changed", StateCheck("books", count_change=1), weight=0.5),
        ])
        result = await grader.grade(transcript)

        assert not result.passed  # Not all passed
        assert result.score == 0.5  # Partial credit
        assert "1/2 steps" in result.explanation

    @pytest.mark.asyncio
    async def test_zero_credit_when_all_fail(self):
        """PartialCredit gives zero when all steps fail."""
        transcript = make_transcript(
            tool_calls=[],
            state_before_books=[],
            state_after_books=[],
        )

        grader = PartialCredit([
            Step("tool_called", ToolWasCalled("create_book"), weight=1.0),
        ])
        result = await grader.grade(transcript)

        assert not result.passed
        assert result.score == 0.0


class TestNoError:
    """Tests for NoError grader."""

    @pytest.mark.asyncio
    async def test_passes_without_error(self):
        """NoError passes when no error occurred."""
        transcript = make_transcript()

        grader = NoError()
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_with_error(self):
        """NoError fails when error occurred."""
        transcript = make_transcript(error="Something went wrong")

        grader = NoError()
        result = await grader.grade(transcript)

        assert not result.passed
        assert "Error occurred" in result.explanation


class TestResponseNotEmpty:
    """Tests for ResponseNotEmpty grader."""

    @pytest.mark.asyncio
    async def test_passes_with_content(self):
        """ResponseNotEmpty passes with sufficient content."""
        transcript = make_transcript(html_response="<div>Hello World</div>")

        grader = ResponseNotEmpty(min_length=10)
        result = await grader.grade(transcript)

        assert result.passed

    @pytest.mark.asyncio
    async def test_fails_when_too_short(self):
        """ResponseNotEmpty fails when response too short."""
        transcript = make_transcript(html_response="hi")

        grader = ResponseNotEmpty(min_length=10)
        result = await grader.grade(transcript)

        assert not result.passed
        assert "too short" in result.explanation


class TestCompositeGrader:
    """Tests for CompositeGrader."""

    @pytest.mark.asyncio
    async def test_and_mode_requires_all(self):
        """CompositeGrader with require_all=True needs all to pass."""
        transcript = make_transcript(
            html_response="<div>Book content</div>",
            tool_calls=[{"name": "get_all_books", "result": []}],
        )

        grader = CompositeGrader([
            HTMLContains(["book"]),
            ToolWasCalled("get_all_books"),
        ], require_all=True)

        result = await grader.grade(transcript)
        assert result.passed

        # Now fail one
        grader2 = CompositeGrader([
            HTMLContains(["book"]),
            ToolWasCalled("create_book"),  # Not called
        ], require_all=True)

        result2 = await grader2.grade(transcript)
        assert not result2.passed

    @pytest.mark.asyncio
    async def test_or_mode_needs_one(self):
        """CompositeGrader with require_all=False needs any one to pass."""
        transcript = make_transcript(
            html_response="<div>Book content</div>",
            tool_calls=[],
        )

        grader = CompositeGrader([
            HTMLContains(["book"]),  # Passes
            ToolWasCalled("create_book"),  # Fails
        ], require_all=False)

        result = await grader.grade(transcript)
        assert result.passed


# Run with: uv run pytest evals/test_graders.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
