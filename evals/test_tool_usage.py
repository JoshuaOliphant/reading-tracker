# ABOUTME: Eval tests verifying agents actually call tools, not just generate plausible UI.
# ABOUTME: Uses pydantic-evals patterns: tool usage verification, state-based outcomes.

"""
Tool Usage Evaluation Tests

These tests verify that agents actually call the appropriate tools
rather than generating UI from conversation memory.

Key principles from Anthropic's eval guide:
1. Grade outcomes, not exact sequences
2. Verify state changes (database), not just agent claims
3. Use code-based evaluators for tool verification
"""

import pytest
import pytest_asyncio
import asyncio
import aiosqlite
from pathlib import Path
from unittest.mock import patch, AsyncMock
from dataclasses import dataclass
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db


@dataclass
class ToolCall:
    """Record of a tool call for evaluation."""
    name: str
    args: dict[str, Any]
    result: Any


class ToolCallTracker:
    """Tracks tool calls made during agent execution."""

    def __init__(self):
        self.calls: list[ToolCall] = []

    def record(self, name: str, args: dict[str, Any], result: Any):
        self.calls.append(ToolCall(name=name, args=args, result=result))

    def was_called(self, tool_name: str) -> bool:
        """Check if a tool was called at least once."""
        return any(c.name == tool_name for c in self.calls)

    def call_count(self, tool_name: str) -> int:
        """Count how many times a tool was called."""
        return sum(1 for c in self.calls if c.name == tool_name)

    def get_calls(self, tool_name: str) -> list[ToolCall]:
        """Get all calls to a specific tool."""
        return [c for c in self.calls if c.name == tool_name]

    def clear(self):
        self.calls.clear()


# Global tracker for tests
tool_tracker = ToolCallTracker()


@pytest_asyncio.fixture
async def clean_db():
    """Set up a clean database for each test."""
    await db.init_db()
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        await conn.execute("DELETE FROM books")
        await conn.commit()

    yield

    # Cleanup after test
    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
        await conn.execute("DELETE FROM books")
        await conn.commit()


@pytest_asyncio.fixture
async def seeded_db(clean_db):
    """Database with known test data."""
    await db.create_book(title="Test Book 1", author="Author A", status="finished", rating=5)
    await db.create_book(title="Test Book 2", author="Author B", status="reading")
    await db.create_book(title="Test Book 3", author="Author C", status="want-to-read")
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    tool_tracker.clear()
    return AgentRouter()


class TestListBooksToolUsage:
    """
    Verify that viewing books actually calls list_books tool.

    This is the core issue: agents might generate plausible UI
    without fetching fresh data from the database.
    """

    @pytest.mark.asyncio
    async def test_show_books_calls_list_books(self, router, seeded_db):
        """
        CRITICAL: When user asks to see books, agent MUST call list_books.

        This eval catches the bug where agent generates UI from memory
        instead of fetching current data.
        """
        # Track which tools are called
        original_list_books = db.get_all_books
        calls = []

        async def tracked_list_books():
            result = await original_list_books()
            calls.append({"tool": "list_books", "result_count": len(result)})
            return result

        with patch.object(db, 'get_all_books', tracked_list_books):
            response = await router.process_user_message("show my books")

        # EVAL: Tool must have been called
        assert len(calls) > 0, (
            "FAIL: Agent did not call list_books tool. "
            "It may be generating UI from conversation memory instead of fetching fresh data."
        )

        # EVAL: Response should contain books from database
        assert "Test Book 1" in response or "test book 1" in response.lower(), (
            "FAIL: Response doesn't contain expected book. "
            f"Got: {response[:500]}..."
        )

    @pytest.mark.asyncio
    async def test_consecutive_list_calls_fetch_fresh_data(self, router, seeded_db):
        """
        Verify that each 'show books' request fetches fresh data.

        This catches caching issues where the agent might use stale data.
        """
        calls = []
        original_fn = db.get_all_books

        async def tracked_fn():
            result = await original_fn()
            calls.append(len(result))
            return result

        with patch.object(db, 'get_all_books', tracked_fn):
            # First request
            await router.process_user_message("show my books")
            first_call_count = len(calls)

            # Add a book directly to DB (simulating external change)
            await db.create_book(title="New Book", author="New Author")

            # Second request - should fetch fresh data
            await router.process_user_message("show my books")

        # EVAL: Both requests should have triggered list_books
        assert len(calls) >= 2, (
            f"FAIL: Expected at least 2 list_books calls, got {len(calls)}. "
            "Agent may be caching book list instead of fetching fresh data."
        )


class TestCreateBookToolUsage:
    """Verify that adding books actually calls create_book and persists."""

    @pytest.mark.asyncio
    async def test_add_book_persists_to_database(self, router, clean_db):
        """
        STATE-BASED EVAL: After adding a book, it must exist in the database.

        Don't trust the agent's UI claim - verify actual database state.
        """
        # Count books before
        books_before = await db.get_all_books()
        count_before = len(books_before)

        # Ask agent to add a book
        response = await router.process_user_message(
            "add a book called 'The Eval Test' by 'Test Author'"
        )

        # STATE EVAL: Book must exist in database
        books_after = await db.get_all_books()
        count_after = len(books_after)

        assert count_after > count_before, (
            f"FAIL: No new book in database. Before: {count_before}, After: {count_after}. "
            "Agent may have shown success UI without actually calling create_book tool."
        )

        # Verify the specific book was created
        titles = [b["title"] for b in books_after]
        assert any("eval test" in t.lower() for t in titles), (
            f"FAIL: Expected book 'The Eval Test' not found. Titles: {titles}"
        )

    @pytest.mark.asyncio
    async def test_add_book_form_submission_persists(self, router, clean_db):
        """
        Verify form-based book creation actually persists.

        This tests the form handling path, not just natural language.
        """
        books_before = await db.get_all_books()

        # Simulate form submission (how main.py sends it)
        message = "create book with form data [title=Form Test Book, author=Form Author, status=reading]"
        response = await router.process_user_message(message)

        books_after = await db.get_all_books()

        # STATE EVAL
        assert len(books_after) > len(books_before), (
            "FAIL: Form submission did not create book in database."
        )


class TestDeleteBookToolUsage:
    """Verify that deleting books actually removes them from database."""

    @pytest.mark.asyncio
    async def test_delete_book_removes_from_database(self, router, seeded_db):
        """
        STATE-BASED EVAL: After deleting a book, it must be gone from database.
        """
        # Get a book ID to delete
        books_before = await db.get_all_books()
        book_to_delete = books_before[0]
        book_id = book_to_delete["id"]

        # Ask agent to delete
        response = await router.process_user_message(f"delete book {book_id}")

        # STATE EVAL: Book must be gone
        books_after = await db.get_all_books()
        remaining_ids = [b["id"] for b in books_after]

        assert book_id not in remaining_ids, (
            f"FAIL: Book {book_id} still exists after delete request. "
            "Agent may have shown success UI without calling delete_book tool."
        )


class TestSearchToolUsage:
    """Verify search actually queries the database."""

    @pytest.mark.asyncio
    async def test_search_calls_search_tool(self, router, seeded_db):
        """
        Verify search queries actually hit the database.
        """
        calls = []
        original_fn = db.search_books

        async def tracked_fn(query):
            result = await original_fn(query)
            calls.append({"query": query, "results": len(result)})
            return result

        with patch.object(db, 'search_books', tracked_fn):
            response = await router.process_user_message("search for Author A")

        # EVAL: Search tool must have been called
        assert len(calls) > 0, (
            "FAIL: Agent did not call search_books tool. "
            "It may be filtering from memory instead of querying database."
        )


class TestUpdateBookToolUsage:
    """Verify updates actually modify the database."""

    @pytest.mark.asyncio
    async def test_update_status_persists(self, router, seeded_db):
        """
        STATE-BASED EVAL: Status change must be reflected in database.
        """
        books = await db.get_all_books()
        book = next(b for b in books if b["status"] == "reading")
        book_id = book["id"]

        # Ask to mark as finished
        response = await router.process_user_message(f"mark book {book_id} as finished")

        # STATE EVAL: Status must have changed
        updated_book = await db.get_book(book_id)

        assert updated_book["status"] == "finished", (
            f"FAIL: Book status is '{updated_book['status']}', expected 'finished'. "
            "Agent may have shown success UI without calling update_book tool."
        )


# Run with: uv run pytest evals/test_tool_usage.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
