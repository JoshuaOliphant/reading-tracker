# ABOUTME: Evals for saved views feature testing static vs data-driven view behavior.
# ABOUTME: Verifies data-driven views fetch fresh data while static views serve cached HTML.

"""
Saved Views Evaluation Tests

These tests verify the saved views system:
1. Static views serve cached HTML exactly
2. Data-driven views inject fresh data at serve time
3. Template placeholders are replaced correctly
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import database as db
from app.saved_views import (
    get_views_manager,
    SavedViewsManager,
    render_data_driven_view,
    render_book_list_html,
    ViewType,
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


@pytest.fixture
def views_manager():
    """Fresh views manager for each test."""
    manager = SavedViewsManager()
    manager._views = {}  # Clear any existing views
    return manager


class TestStaticViews:
    """Test static view behavior - should serve exact cached HTML."""

    def test_static_view_serves_exact_html(self, views_manager):
        """
        Static views should return the exact HTML that was saved.
        """
        original_html = '<div class="test">Exact Content</div>'

        view = views_manager.add_static_view(
            name="Test Static",
            trigger_phrases=["test static"],
            keywords=["test"],
            html=original_html,
        )

        assert view.html_template == original_html, (
            "FAIL: Static view modified the HTML. "
            "Should preserve exact content."
        )
        assert view.is_static, "FAIL: View type should be static"
        assert not view.is_data_driven, "FAIL: View should not be data-driven"

    def test_static_view_no_placeholder_replacement(self, views_manager):
        """
        Static views should NOT replace placeholders.
        """
        html_with_placeholder = '<div>{{BOOK_LIST}}</div>'

        view = views_manager.add_static_view(
            name="Test Static",
            trigger_phrases=["test"],
            keywords=[],
            html=html_with_placeholder,
        )

        # Static view should keep placeholder as-is
        assert "{{BOOK_LIST}}" in view.html_template, (
            "FAIL: Static view should not process placeholders. "
            "Use data-driven views for that."
        )


class TestDataDrivenViews:
    """Test data-driven view behavior - should inject fresh data."""

    @pytest.mark.asyncio
    async def test_data_driven_view_replaces_book_list(self, views_manager, clean_db):
        """
        Data-driven views should replace {{BOOK_LIST}} with actual books.
        """
        # Create test books
        await db.create_book(title="Fresh Book 1", author="Author A")
        await db.create_book(title="Fresh Book 2", author="Author B")

        template = '<div class="list">{{BOOK_LIST}}</div>'

        view = views_manager.add_data_driven_view(
            name="Test Dynamic",
            trigger_phrases=["test dynamic"],
            keywords=[],
            html_template=template,
            tools_needed=["list_books"],
        )

        # Render with fresh data
        books = await db.get_all_books()
        rendered = await render_data_driven_view(view, {"books": books})

        # Should contain actual book titles
        assert "Fresh Book 1" in rendered, (
            "FAIL: Data-driven view didn't include book data. "
            "Template rendering failed."
        )
        assert "Fresh Book 2" in rendered
        assert "{{BOOK_LIST}}" not in rendered, (
            "FAIL: Placeholder not replaced. Template rendering failed."
        )

    @pytest.mark.asyncio
    async def test_data_driven_view_replaces_book_count(self, views_manager, clean_db):
        """
        Data-driven views should replace {{BOOK_COUNT}} with actual count.
        """
        await db.create_book(title="Book 1", author="A")
        await db.create_book(title="Book 2", author="B")
        await db.create_book(title="Book 3", author="C")

        template = '<p>{{BOOK_COUNT}} books total</p>'

        view = views_manager.add_data_driven_view(
            name="Count Test",
            trigger_phrases=["count test"],
            keywords=[],
            html_template=template,
            tools_needed=["list_books"],
        )

        books = await db.get_all_books()
        rendered = await render_data_driven_view(view, {"books": books})

        assert "3 books total" in rendered, (
            f"FAIL: Book count not replaced. Got: {rendered}"
        )
        assert "{{BOOK_COUNT}}" not in rendered

    @pytest.mark.asyncio
    async def test_data_driven_view_reflects_database_changes(self, views_manager, clean_db):
        """
        Critical: Data-driven views must show current database state.

        This catches the stale data bug.
        """
        template = '<div>{{BOOK_COUNT}} books: {{BOOK_LIST}}</div>'

        view = views_manager.add_data_driven_view(
            name="Fresh Data Test",
            trigger_phrases=["fresh test"],
            keywords=[],
            html_template=template,
            tools_needed=["list_books"],
        )

        # Initial render - empty
        books = await db.get_all_books()
        rendered1 = await render_data_driven_view(view, {"books": books})
        assert "0 books" in rendered1

        # Add a book
        await db.create_book(title="New Book", author="Author")

        # Re-render - should show new book
        books = await db.get_all_books()
        rendered2 = await render_data_driven_view(view, {"books": books})
        assert "1 books" in rendered2 or "1 book" in rendered2.replace("1 books", "1 book"), (
            f"FAIL: Count not updated after adding book. Got: {rendered2}"
        )
        assert "New Book" in rendered2, (
            "FAIL: New book not in rendered output. Data not fresh!"
        )


class TestViewMatching:
    """Test trigger phrase and keyword matching."""

    def test_exact_phrase_match(self, views_manager):
        """
        Exact phrase matches should take priority.
        """
        views_manager.add_static_view(
            name="Exact Match",
            trigger_phrases=["show my books"],
            keywords=[],
            html="<div>Exact</div>",
        )

        match = views_manager.find_matching_view("show my books")
        assert match is not None, "FAIL: Exact phrase should match"
        assert match.name == "Exact Match"

    def test_keyword_match(self, views_manager):
        """
        Keyword matches should work when all keywords present.
        """
        views_manager.add_static_view(
            name="Keyword Match",
            trigger_phrases=["exact phrase only"],
            keywords=["books", "list"],
            html="<div>Keywords</div>",
        )

        # Should match when all keywords present
        match = views_manager.find_matching_view("show me the books list please")
        assert match is not None, "FAIL: Keywords 'books' and 'list' should match"

    def test_partial_keywords_no_match(self, views_manager):
        """
        Partial keyword matches should NOT trigger.
        """
        views_manager.add_static_view(
            name="Partial Test",
            trigger_phrases=["exact"],
            keywords=["all", "three", "words"],
            html="<div>Partial</div>",
        )

        # Should not match with only some keywords
        match = views_manager.find_matching_view("just all words")
        assert match is None, (
            "FAIL: Partial keyword match should not trigger. "
            "All keywords must be present."
        )


class TestRenderBookListHTML:
    """Test the book list HTML rendering function."""

    @pytest.mark.asyncio
    async def test_empty_list_shows_message(self, clean_db):
        """
        Empty book list should show a friendly message.
        """
        html = await render_book_list_html([])

        assert "No books yet" in html, "FAIL: Empty state missing friendly message"
        assert "Add" in html, "FAIL: Empty state should suggest adding books"

    @pytest.mark.asyncio
    async def test_books_render_with_details(self, clean_db):
        """
        Books should render with title, author, status, rating.
        """
        books = [
            {
                "id": 1,
                "title": "Test Title",
                "author": "Test Author",
                "status": "reading",
                "rating": 4,
            }
        ]

        html = await render_book_list_html(books)

        assert "Test Title" in html, "FAIL: Book title missing"
        assert "Test Author" in html, "FAIL: Author missing"
        assert "Reading" in html, "FAIL: Status missing"
        # Rating stars
        assert "★" in html, "FAIL: Rating stars missing"

    @pytest.mark.asyncio
    async def test_books_have_click_handlers(self, clean_db):
        """
        Book items should be clickable to show details.
        """
        books = [{"id": 42, "title": "Clickable", "author": "Author", "status": "finished", "rating": None}]

        html = await render_book_list_html(books)

        assert "hx-post" in html, "FAIL: Book items missing click handler"
        assert "show book 42" in html, "FAIL: Click should trigger 'show book {id}'"


# Run with: uv run pytest evals/test_saved_views.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
