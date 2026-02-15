# ABOUTME: Evals for natural language CRUD operations via the chat interface.
# ABOUTME: Tests various phrasings users might use to interact with their reading list.

"""
Natural Language Evaluation Tests

These tests verify the agent understands various natural language phrasings
for CRUD operations, not just exact trigger phrases.

Derived from Playwright testing of actual chat interactions.
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db


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
        title="The Midnight Library",
        author="Matt Haig",
        status="want-to-read",
        rating=None
    )
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


class TestNaturalLanguageCreate:
    """Test various phrasings for adding books."""

    @pytest.mark.asyncio
    async def test_add_with_quotes(self, router, clean_db):
        """
        User: add "Book Title" by Author Name
        """
        await router.process_user_message('add "Test Book" by Test Author')

        books = await db.get_all_books()
        titles = [b["title"].lower() for b in books]

        assert any("test book" in t for t in titles), (
            f"FAIL: Book not created from quoted title. Found: {titles}"
        )

    @pytest.mark.asyncio
    async def test_add_informal_phrasing(self, router, clean_db):
        """
        User: I want to read Project Hail Mary by Andy Weir
        """
        await router.process_user_message("I want to read Project Hail Mary by Andy Weir")

        books = await db.get_all_books()
        titles = [b["title"].lower() for b in books]

        assert any("project hail mary" in t for t in titles), (
            f"FAIL: Agent didn't understand 'I want to read X'. Found: {titles}"
        )

    @pytest.mark.asyncio
    async def test_add_simple_command(self, router, clean_db):
        """
        User: add Dune by Frank Herbert
        """
        await router.process_user_message("add Dune by Frank Herbert")

        books = await db.get_all_books()
        titles = [b["title"].lower() for b in books]

        assert any("dune" in t for t in titles), (
            f"FAIL: Simple 'add X by Y' not understood. Found: {titles}"
        )


class TestNaturalLanguageRead:
    """Test various phrasings for viewing books."""

    @pytest.mark.asyncio
    async def test_show_my_books(self, router, seeded_db):
        """Standard phrasing that may hit saved view."""
        response = await router.process_user_message("show my books")
        assert "Midnight Library" in response or "midnight library" in response.lower()

    @pytest.mark.asyncio
    async def test_list_my_books(self, router, seeded_db):
        """Alternate phrasing: list instead of show."""
        response = await router.process_user_message("list my books")
        assert "Midnight Library" in response or "midnight library" in response.lower()

    @pytest.mark.asyncio
    async def test_question_form(self, router, seeded_db):
        """Question phrasing: what books do I have?"""
        response = await router.process_user_message("what books do I have?")
        assert "Midnight Library" in response or "midnight library" in response.lower()

    @pytest.mark.asyncio
    async def test_view_reading_list(self, router, seeded_db):
        """Alternate phrasing: view my reading list."""
        response = await router.process_user_message("view my reading list")
        assert "Midnight Library" in response or "midnight library" in response.lower()


class TestNaturalLanguageUpdate:
    """Test various phrasings for updating books."""

    @pytest.mark.asyncio
    async def test_started_reading(self, router, seeded_db):
        """
        User: I started reading The Midnight Library
        """
        await router.process_user_message("I started reading The Midnight Library")

        books = await db.get_all_books()
        book = next((b for b in books if "midnight" in b["title"].lower()), None)

        assert book is not None, "Book not found"
        assert book["status"] == "reading", (
            f"FAIL: Status not updated to 'reading'. Got: {book['status']}"
        )

    @pytest.mark.asyncio
    async def test_finished_reading(self, router, seeded_db):
        """
        User: I finished The Midnight Library
        """
        # First set to reading
        await db.update_book(1, status="reading")

        await router.process_user_message("I finished The Midnight Library")

        books = await db.get_all_books()
        book = next((b for b in books if "midnight" in b["title"].lower()), None)

        assert book is not None, "Book not found"
        assert book["status"] == "finished", (
            f"FAIL: Status not updated to 'finished'. Got: {book['status']}"
        )

    @pytest.mark.asyncio
    async def test_give_rating(self, router, seeded_db):
        """
        User: give The Midnight Library 5 stars
        """
        await router.process_user_message("give The Midnight Library 5 stars")

        books = await db.get_all_books()
        book = next((b for b in books if "midnight" in b["title"].lower()), None)

        assert book is not None, "Book not found"
        assert book["rating"] == 5, (
            f"FAIL: Rating not set to 5. Got: {book['rating']}"
        )

    @pytest.mark.asyncio
    async def test_rate_book(self, router, seeded_db):
        """
        User: rate The Midnight Library 4 stars
        """
        await router.process_user_message("rate The Midnight Library 4 stars")

        books = await db.get_all_books()
        book = next((b for b in books if "midnight" in b["title"].lower()), None)

        assert book is not None, "Book not found"
        assert book["rating"] == 4, (
            f"FAIL: Rating not set to 4. Got: {book['rating']}"
        )


class TestNaturalLanguageSearch:
    """Test various phrasings for searching books."""

    @pytest.mark.asyncio
    async def test_search_for_author(self, router, seeded_db):
        """
        User: search for Matt Haig
        """
        response = await router.process_user_message("search for Matt Haig")

        assert "Midnight Library" in response or "midnight library" in response.lower(), (
            "FAIL: Search didn't find book by author"
        )
        # Should indicate it's search results
        assert "search" in response.lower() or "found" in response.lower() or "result" in response.lower()

    @pytest.mark.asyncio
    async def test_find_books(self, router, seeded_db):
        """
        User: find books by Matt Haig
        """
        response = await router.process_user_message("find books by Matt Haig")

        assert "Midnight Library" in response or "midnight library" in response.lower(), (
            "FAIL: 'find books' phrasing not understood"
        )


class TestNaturalLanguageDelete:
    """Test various phrasings for deleting books."""

    @pytest.mark.asyncio
    async def test_delete_by_title(self, router, seeded_db):
        """
        User: delete The Midnight Library
        """
        books_before = await db.get_all_books()
        assert len(books_before) == 1

        await router.process_user_message("delete The Midnight Library")

        books_after = await db.get_all_books()
        assert len(books_after) == 0, (
            f"FAIL: Book not deleted. Still have {len(books_after)} books"
        )

    @pytest.mark.asyncio
    async def test_remove_book(self, router, seeded_db):
        """
        User: remove The Midnight Library from my list
        """
        books_before = await db.get_all_books()
        assert len(books_before) == 1

        await router.process_user_message("remove The Midnight Library from my list")

        books_after = await db.get_all_books()
        assert len(books_after) == 0, (
            f"FAIL: 'remove X from my list' not understood. Still have {len(books_after)} books"
        )


class TestComplexInteractions:
    """Test multi-step natural language interactions."""

    @pytest.mark.asyncio
    async def test_full_crud_flow(self, router, clean_db):
        """
        Test complete flow: add, update, rate, delete.
        """
        # CREATE
        await router.process_user_message('add "Flow Test Book" by Test Author')
        books = await db.get_all_books()
        assert len(books) == 1, "Create failed"

        # UPDATE STATUS
        await router.process_user_message("I started reading Flow Test Book")
        books = await db.get_all_books()
        assert books[0]["status"] == "reading", "Status update failed"

        # UPDATE RATING
        await router.process_user_message("give Flow Test Book 4 stars")
        books = await db.get_all_books()
        assert books[0]["rating"] == 4, "Rating update failed"

        # DELETE
        await router.process_user_message("delete Flow Test Book")
        books = await db.get_all_books()
        assert len(books) == 0, "Delete failed"


# Run with: uv run pytest evals/test_natural_language.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
