# ABOUTME: UI quality evals verifying HTMX attributes, loading indicators, and response structure.
# ABOUTME: Tests agent-generated HTML for proper interactivity patterns.

"""
UI Quality Evaluation Tests

These tests verify that agent-generated HTML:
1. Contains proper HTMX attributes for interactivity
2. Has accessible structure (headings, buttons, etc.)
3. Follows the design system patterns
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
import re

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
    """Database with test data."""
    await db.create_book(title="Test Book", author="Test Author", status="reading", rating=4)
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


class TestHTMXAttributes:
    """Verify HTMX attributes are present in agent-generated HTML."""

    @pytest.mark.asyncio
    async def test_book_list_has_htmx_buttons(self, router, seeded_db):
        """
        Book list should have HTMX-enabled buttons for interaction.
        """
        response = await router.process_user_message("show my books")

        # Should have hx-post for form submissions
        assert "hx-post" in response, (
            "FAIL: Response missing hx-post attribute. "
            "Buttons won't trigger HTMX requests."
        )

        # Should target #content div
        assert 'hx-target="#content"' in response or "hx-target=\"#content\"" in response, (
            "FAIL: Response missing hx-target='#content'. "
            "HTMX won't know where to swap content."
        )

        # Should have hx-vals for passing messages
        assert "hx-vals" in response, (
            "FAIL: Response missing hx-vals attribute. "
            "Buttons won't pass message data to agent."
        )

    @pytest.mark.asyncio
    async def test_add_book_form_has_htmx(self, router, clean_db):
        """
        Add book form should be HTMX-enabled.
        """
        response = await router.process_user_message("add a book")

        # Should have form with hx-post
        assert "<form" in response.lower(), "FAIL: Response missing form element"
        assert "hx-post" in response, "FAIL: Form missing hx-post attribute"

        # Should have required input fields
        assert 'name="title"' in response.lower() or 'name="Title"' in response, (
            "FAIL: Form missing title input field"
        )

        # Should have submit button
        assert 'type="submit"' in response.lower(), "FAIL: Form missing submit button"

    @pytest.mark.asyncio
    async def test_book_detail_has_action_buttons(self, router, seeded_db):
        """
        Book detail view should have action buttons (edit, delete, etc.)
        """
        books = await db.get_all_books()
        book_id = books[0]["id"]

        response = await router.process_user_message(f"show book {book_id}")

        # Should have interactive buttons
        assert "hx-post" in response, "FAIL: Book detail missing interactive buttons"

        # Should have navigation back to list
        has_back = "back" in response.lower() or "list" in response.lower()
        assert has_back, "FAIL: Book detail missing back navigation"


class TestAccessibleStructure:
    """Verify HTML has accessible structure."""

    @pytest.mark.asyncio
    async def test_book_list_has_heading(self, router, seeded_db):
        """
        Book list should have a proper heading.
        """
        response = await router.process_user_message("show my books")

        # Should have h1 or h2 heading
        has_heading = re.search(r'<h[12][^>]*>', response, re.IGNORECASE)
        assert has_heading, (
            "FAIL: Response missing heading element. "
            "Screen readers need headings for navigation."
        )

    @pytest.mark.asyncio
    async def test_buttons_have_accessible_text(self, router, seeded_db):
        """
        Buttons should have descriptive text, not just icons.
        """
        response = await router.process_user_message("show my books")

        # Find all buttons
        buttons = re.findall(r'<button[^>]*>(.*?)</button>', response, re.DOTALL | re.IGNORECASE)

        # At least some buttons should have text content (not just SVG/images)
        text_buttons = [b for b in buttons if re.search(r'[a-zA-Z]{3,}', b)]
        assert len(text_buttons) > 0, (
            "FAIL: All buttons appear to be icon-only. "
            "Need accessible text for screen readers."
        )


class TestDesignSystemCompliance:
    """Verify HTML follows the design system patterns."""

    @pytest.mark.asyncio
    async def test_uses_tailwind_classes(self, router, seeded_db):
        """
        Response should use Tailwind CSS classes.
        """
        response = await router.process_user_message("show my books")

        # Should have common Tailwind patterns
        tailwind_patterns = ["bg-", "text-", "px-", "py-", "rounded", "flex"]
        matches = sum(1 for p in tailwind_patterns if p in response)

        assert matches >= 3, (
            f"FAIL: Response only has {matches}/6 expected Tailwind patterns. "
            "Agent may not be following design system."
        )

    @pytest.mark.asyncio
    async def test_dark_theme_colors(self, router, seeded_db):
        """
        Response should use dark theme colors (slate-900, slate-800, etc.)
        """
        response = await router.process_user_message("show my books")

        # Should use dark slate colors
        dark_colors = ["slate-900", "slate-800", "slate-950"]
        has_dark = any(c in response for c in dark_colors)

        assert has_dark, (
            "FAIL: Response not using dark theme colors. "
            "Should use slate-900, slate-800, or slate-950."
        )

    @pytest.mark.asyncio
    async def test_indigo_accent_color(self, router, seeded_db):
        """
        Primary buttons should use indigo accent color.
        """
        response = await router.process_user_message("show my books")

        # Should have indigo accent (primary button color)
        assert "indigo" in response, (
            "FAIL: Response missing indigo accent color. "
            "Primary actions should use bg-indigo-600."
        )


class TestSuccessAndErrorStates:
    """Verify proper success and error message formatting."""

    @pytest.mark.asyncio
    async def test_book_creation_shows_success(self, router, clean_db):
        """
        Creating a book should show a success message.
        """
        response = await router.process_user_message(
            "add 'Success Test Book' by 'Test Author'"
        )

        # Should indicate success somehow
        success_indicators = ["success", "added", "created", "✓", "✔"]
        has_success = any(s in response.lower() for s in success_indicators)

        assert has_success, (
            "FAIL: Book creation response doesn't indicate success. "
            "User needs feedback that action completed."
        )

    @pytest.mark.asyncio
    async def test_delete_shows_confirmation(self, router, seeded_db):
        """
        Deleting a book should show confirmation.
        """
        books = await db.get_all_books()
        book_id = books[0]["id"]

        response = await router.process_user_message(f"delete book {book_id}")

        # Should confirm deletion
        confirm_indicators = ["deleted", "removed", "success", "✓"]
        has_confirm = any(s in response.lower() for s in confirm_indicators)

        assert has_confirm, (
            "FAIL: Delete response doesn't confirm action. "
            "User needs feedback that book was removed."
        )


# Run with: uv run pytest evals/test_ui_quality.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
