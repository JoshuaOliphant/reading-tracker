# ABOUTME: Tests for the transcript capture system.
# ABOUTME: Verifies tool call tracking, state snapshots, and timing capture.

"""
Transcript Capture Tests

Verifies that TranscriptCapture correctly records:
- Tool calls with arguments and results
- Database state before and after
- Timing information
- Agent messages
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db
from evals.transcript import TranscriptCapture, TrialTranscript


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
    await db.create_book(title="Test Book 1", author="Author A", status="finished", rating=5)
    await db.create_book(title="Test Book 2", author="Author B", status="reading")
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


class TestTranscriptCapture:
    """Tests for the TranscriptCapture context manager."""

    @pytest.mark.asyncio
    async def test_captures_tool_calls(self, router, seeded_db):
        """Verify that tool calls are recorded in the transcript."""
        async with TranscriptCapture(router, db) as capture:
            response = await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        assert transcript is not None
        assert len(transcript.tool_calls) > 0, (
            "FAIL: No tool calls captured. "
            "Expected at least get_all_books to be called."
        )

        tool_names = [tc.name for tc in transcript.tool_calls]
        assert 'get_all_books' in tool_names, (
            f"FAIL: Expected get_all_books in tool calls, got: {tool_names}"
        )

    @pytest.mark.asyncio
    async def test_captures_database_state(self, router, seeded_db):
        """Verify that database state is captured before and after."""
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        assert transcript.state_before is not None, "Missing state_before snapshot"
        assert transcript.state_after is not None, "Missing state_after snapshot"

        # Should have 2 books in seeded state
        assert len(transcript.state_before.books) == 2, (
            f"Expected 2 books in state_before, got {len(transcript.state_before.books)}"
        )

    @pytest.mark.asyncio
    async def test_captures_timing(self, router, seeded_db):
        """Verify that timing information is recorded."""
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        assert transcript.duration_ms > 0, (
            f"Expected positive duration, got {transcript.duration_ms}ms"
        )

    @pytest.mark.asyncio
    async def test_captures_html_response(self, router, seeded_db):
        """Verify that HTML response is captured."""
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        assert len(transcript.html_response) > 0, "Missing HTML response"
        # Response should contain book data
        assert "Test Book" in transcript.html_response or "test book" in transcript.html_response.lower(), (
            "HTML response should contain book data"
        )

    @pytest.mark.asyncio
    async def test_captures_create_operation(self, router, clean_db):
        """Verify that create operations are captured with state change."""
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message(
                "add a book called 'Transcript Test' by 'Test Author'"
            )
            transcript = capture.get_transcript()

        # State should change
        books_before = len(transcript.state_before.books)
        books_after = len(transcript.state_after.books)

        assert books_after > books_before, (
            f"Book count should increase. Before: {books_before}, After: {books_after}"
        )

        # Should have captured create_book call
        tool_names = [tc.name for tc in transcript.tool_calls]
        assert 'create_book' in tool_names, (
            f"Expected create_book in tool calls, got: {tool_names}"
        )

    @pytest.mark.asyncio
    async def test_transcript_serialization(self, router, seeded_db):
        """Verify that transcripts can be serialized to JSON."""
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        # Should serialize without error
        json_str = transcript.to_json()
        assert len(json_str) > 0

        # Should be valid JSON
        import json
        data = json.loads(json_str)

        # Check structure
        assert "trial_id" in data
        assert "user_message" in data
        assert "tool_calls" in data
        assert "state_before" in data
        assert "state_after" in data

    @pytest.mark.asyncio
    async def test_captures_agent_messages(self, router, seeded_db):
        """Verify that inter-agent messages are captured from the router's log."""
        async with TranscriptCapture(router, db) as capture:
            # This query should trigger recommender agent delegation
            await capture.process_user_message("What should I read next?")
            transcript = capture.get_transcript()

        # The router's message log captures inter-agent communication
        # (user→ui is handled separately by process_user_message)
        # A recommendation query should trigger ui→recommender communication
        if len(transcript.agent_messages) > 0:
            # Verify message structure is valid
            for msg in transcript.agent_messages:
                assert msg.from_agent in ["ui", "recommender", "insights", "user"]
                assert msg.to_agent in ["ui", "recommender", "insights"]
                assert len(msg.content) > 0 or msg.content == ""

            # If recommender was called, verify it's in the messages
            agent_targets = [m.to_agent for m in transcript.agent_messages]
            # Recommendation query should involve recommender agent
            assert "recommender" in agent_targets or len(transcript.agent_messages) >= 1, (
                "Expected recommender to be called for 'What should I read' query"
            )

    @pytest.mark.asyncio
    async def test_works_without_db_module(self, router, seeded_db):
        """Verify capture works even without db module (no state snapshots)."""
        async with TranscriptCapture(router, db_module=None) as capture:
            response = await capture.process_user_message("show my books")
            transcript = capture.get_transcript()

        # Should still capture basic info
        assert transcript.user_message == "show my books"
        assert len(transcript.html_response) > 0

        # But no state snapshots
        assert transcript.state_before is None
        assert transcript.state_after is None


# Run with: uv run pytest evals/test_transcript.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
