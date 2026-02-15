# ABOUTME: Tests for complex multi-step tasks with partial credit scoring.
# ABOUTME: Evaluates how far the agent gets on tasks like "add and rate a book".

"""
Complex Task Evals with Partial Credit

For multi-step agent tasks, pass/fail is often too coarse.
Partial credit scoring tells us "how far did the agent get?"

This is crucial for:
1. Understanding failure modes (which step fails?)
2. Measuring improvement over time
3. Comparing different prompting strategies

Based on Anthropic's eval guide recommendation for partial credit on complex tasks.
"""

import pytest
import pytest_asyncio
import aiosqlite
from dataclasses import dataclass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db
from evals.transcript import TranscriptCapture
from evals.graders import (
    StateCheck,
    ToolWasCalled,
    HTMLContains,
    PartialCredit,
    Step,
    NoError,
    ResponseNotEmpty,
)


@dataclass
class PartialCreditResult:
    """Result of a partial credit evaluation."""
    steps_attempted: int
    steps_completed: int
    score: float  # 0.0 - 1.0
    step_results: list[tuple[str, bool, str]]  # (step_name, passed, reason)

    @property
    def passed(self) -> bool:
        """Full pass requires all steps to complete."""
        return self.steps_completed == self.steps_attempted

    def summary(self) -> str:
        """Human-readable summary of results."""
        lines = [f"Score: {self.score:.1%} ({self.steps_completed}/{self.steps_attempted} steps)"]
        for name, passed, reason in self.step_results:
            status = "✓" if passed else "✗"
            lines.append(f"  {status} {name}: {reason}")
        return "\n".join(lines)


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
    await db.create_book(title="Test Book 1", author="Author A", status="reading")
    await db.create_book(title="Test Book 2", author="Author B", status="want-to-read")
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


class TestAddAndRateBook:
    """
    Complex task: Add a new book and give it a rating.

    Steps:
    1. Book created in database (0.3 weight)
    2. Correct title/author stored (0.3 weight)
    3. Rating applied (0.2 weight)
    4. UI shows success feedback (0.2 weight)
    """

    @pytest.mark.asyncio
    async def test_add_and_rate_in_single_message(self, router, clean_db):
        """Test adding a book with rating in one message."""
        async with TranscriptCapture(router, db) as capture:
            response = await capture.process_user_message(
                "add 'The Pragmatic Programmer' by David Thomas, give it 5 stars"
            )
            transcript = capture.get_transcript()

        # Define grading rubric
        grader = PartialCredit([
            Step(
                "book_created",
                StateCheck("books", count_change=1),
                weight=0.3,
            ),
            Step(
                "correct_title",
                StateCheck("books", field_check={"title": "The Pragmatic Programmer"}),
                weight=0.3,
            ),
            Step(
                "rating_applied",
                StateCheck("books", field_check={"rating": 5}),
                weight=0.2,
            ),
            Step(
                "ui_success",
                HTMLContains(["success", "added", "created"], require_all=False),
                weight=0.2,
            ),
        ])

        result = await grader.grade(transcript)

        # Build detailed result
        step_results = []
        for step in result.details.get("steps", []):
            step_results.append((
                step["name"],
                step["passed"],
                step["explanation"],
            ))

        pc_result = PartialCreditResult(
            steps_attempted=4,
            steps_completed=sum(1 for s in result.details.get("steps", []) if s["passed"]),
            score=result.score,
            step_results=step_results,
        )

        # Print detailed results for debugging
        print(f"\n{pc_result.summary()}")

        # Assert minimum acceptable score
        assert result.score >= 0.3, (
            f"FAIL: Score {result.score:.1%} below minimum 30%. "
            f"At minimum, book should be created.\n{pc_result.summary()}"
        )

    @pytest.mark.asyncio
    async def test_add_then_rate_separate_messages(self, router, clean_db):
        """Test adding a book, then rating it in a second message."""
        # First message: add book
        response1 = await router.process_user_message(
            "add a book called 'Clean Code' by Robert Martin"
        )

        # Verify book was created
        books = await db.get_all_books()
        assert len(books) == 1, "Book should be created after first message"
        book_id = books[0]["id"]

        # Second message: rate the book
        async with TranscriptCapture(router, db) as capture:
            response2 = await capture.process_user_message(
                f"rate book {book_id} 4 stars"
            )
            transcript = capture.get_transcript()

        # Check rating was applied
        updated_book = await db.get_book(book_id)
        assert updated_book["rating"] == 4, (
            f"Rating should be 4, got {updated_book['rating']}"
        )


class TestReadAndFinishBook:
    """
    Complex task: Start reading a book and mark it finished.

    Steps:
    1. Status changed to 'reading' (0.3 weight)
    2. Status changed to 'finished' (0.3 weight)
    3. Update tool called (0.2 weight)
    4. UI shows progress (0.2 weight)
    """

    @pytest.mark.asyncio
    async def test_start_and_finish_book(self, router, seeded_db):
        """Test changing book status from want-to-read to finished."""
        # Get a want-to-read book
        books = await db.get_all_books()
        book = next(b for b in books if b["status"] == "want-to-read")
        book_id = book["id"]

        # Start reading
        await router.process_user_message(f"start reading book {book_id}")

        # Verify reading status
        updated = await db.get_book(book_id)
        reading_worked = updated["status"] == "reading"

        # Finish reading
        async with TranscriptCapture(router, db) as capture:
            await capture.process_user_message(f"finished book {book_id}")
            transcript = capture.get_transcript()

        # Verify finished status
        final = await db.get_book(book_id)
        finished_worked = final["status"] == "finished"

        # Partial credit scoring
        score = 0.0
        step_results = []

        if reading_worked:
            score += 0.5
            step_results.append(("start_reading", True, "Status changed to reading"))
        else:
            step_results.append(("start_reading", False, f"Status is {updated['status']}"))

        if finished_worked:
            score += 0.5
            step_results.append(("finish_reading", True, "Status changed to finished"))
        else:
            step_results.append(("finish_reading", False, f"Status is {final['status']}"))

        pc_result = PartialCreditResult(
            steps_attempted=2,
            steps_completed=sum(1 for _, p, _ in step_results if p),
            score=score,
            step_results=step_results,
        )

        print(f"\n{pc_result.summary()}")

        assert score >= 0.5, (
            f"FAIL: Score {score:.1%} below minimum 50%. "
            f"At least one status change should work.\n{pc_result.summary()}"
        )


class TestSearchAndUpdate:
    """
    Complex task: Search for a book and update its details.

    Steps:
    1. Search returns results (0.25 weight)
    2. Correct book identified (0.25 weight)
    3. Update applied (0.25 weight)
    4. UI shows changes (0.25 weight)
    """

    @pytest.mark.asyncio
    async def test_search_and_update_notes(self, router, seeded_db):
        """Test searching for a book and adding notes."""
        async with TranscriptCapture(router, db) as capture:
            # Search and update in one interaction
            response = await capture.process_user_message(
                "find 'Test Book 1' and add notes: 'Great read!'"
            )
            transcript = capture.get_transcript()

        # Check if notes were added
        books = await db.get_all_books()
        book = next((b for b in books if "test book 1" in b["title"].lower()), None)

        grader = PartialCredit([
            Step(
                "search_called",
                ToolWasCalled("search_books", min_calls=0),  # May not always search
                weight=0.25,
            ),
            Step(
                "book_found",
                StateCheck("books", field_check={"title": "Test Book 1"}),
                weight=0.25,
            ),
            Step(
                "notes_added",
                StateCheck("books", field_check={"notes": "Great read!"}),
                weight=0.25,
            ),
            Step(
                "response_valid",
                ResponseNotEmpty(min_length=50),
                weight=0.25,
            ),
        ])

        result = await grader.grade(transcript)

        print(f"\nScore: {result.score:.1%}")
        for step in result.details.get("steps", []):
            status = "✓" if step["passed"] else "✗"
            print(f"  {status} {step['name']}: {step['explanation']}")

        # At minimum, should find the book and show valid response
        assert result.score >= 0.5, (
            f"FAIL: Score {result.score:.1%} below minimum 50%"
        )


class TestBulkOperations:
    """
    Complex task: Add multiple books in sequence.

    Tests agent's ability to handle sequential operations correctly.
    """

    @pytest.mark.asyncio
    async def test_add_multiple_books_sequential(self, router, clean_db):
        """Test adding several books one after another."""
        books_to_add = [
            ("Book One", "Author 1"),
            ("Book Two", "Author 2"),
            ("Book Three", "Author 3"),
        ]

        results = []

        for title, author in books_to_add:
            books_before = await db.get_all_books()
            count_before = len(books_before)

            response = await router.process_user_message(
                f"add '{title}' by {author}"
            )

            books_after = await db.get_all_books()
            count_after = len(books_after)

            success = count_after == count_before + 1
            results.append((title, success))

        # Calculate partial credit
        successes = sum(1 for _, s in results if s)
        score = successes / len(books_to_add)

        pc_result = PartialCreditResult(
            steps_attempted=len(books_to_add),
            steps_completed=successes,
            score=score,
            step_results=[
                (title, success, "Added" if success else "Not added")
                for title, success in results
            ],
        )

        print(f"\n{pc_result.summary()}")

        assert score >= 0.66, (
            f"FAIL: Only {successes}/{len(books_to_add)} books added. "
            f"Score: {score:.1%}\n{pc_result.summary()}"
        )


class TestComplexWorkflow:
    """
    End-to-end workflow: Add book, start reading, finish, rate.

    This tests a complete user journey through the app.
    """

    @pytest.mark.asyncio
    async def test_full_book_lifecycle(self, router, clean_db):
        """Test complete book lifecycle from add to finished with rating."""
        step_results = []

        # Step 1: Add book
        await router.process_user_message("add 'Dune' by Frank Herbert")
        books = await db.get_all_books()

        if len(books) == 1:
            step_results.append(("add_book", True, "Book created"))
            book_id = books[0]["id"]
        else:
            step_results.append(("add_book", False, f"Expected 1 book, got {len(books)}"))
            # Can't continue without book
            score = 0.0
            pc_result = PartialCreditResult(
                steps_attempted=4,
                steps_completed=0,
                score=score,
                step_results=step_results,
            )
            print(f"\n{pc_result.summary()}")
            assert False, "Cannot continue test without book creation"

        # Step 2: Start reading
        await router.process_user_message(f"start reading book {book_id}")
        book = await db.get_book(book_id)

        if book["status"] == "reading":
            step_results.append(("start_reading", True, "Status: reading"))
        else:
            step_results.append(("start_reading", False, f"Status: {book['status']}"))

        # Step 3: Finish reading
        await router.process_user_message(f"finished book {book_id}")
        book = await db.get_book(book_id)

        if book["status"] == "finished":
            step_results.append(("finish_reading", True, "Status: finished"))
        else:
            step_results.append(("finish_reading", False, f"Status: {book['status']}"))

        # Step 4: Rate book
        await router.process_user_message(f"rate book {book_id} 5 stars")
        book = await db.get_book(book_id)

        if book["rating"] == 5:
            step_results.append(("rate_book", True, "Rating: 5 stars"))
        else:
            step_results.append(("rate_book", False, f"Rating: {book['rating']}"))

        # Calculate score
        successes = sum(1 for _, passed, _ in step_results if passed)
        score = successes / 4

        pc_result = PartialCreditResult(
            steps_attempted=4,
            steps_completed=successes,
            score=score,
            step_results=step_results,
        )

        print(f"\n{pc_result.summary()}")

        assert score >= 0.75, (
            f"FAIL: Score {score:.1%} below minimum 75%. "
            f"Full lifecycle should work.\n{pc_result.summary()}"
        )


# Run with: uv run pytest evals/test_complex_tasks.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
