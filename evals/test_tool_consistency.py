# ABOUTME: Consistency evals measuring pass@k and pass^k across multiple trials.
# ABOUTME: Tests agent reliability with parameterized scenarios and statistical analysis.

"""
Consistency Evaluation Tests

Following Anthropic's eval guide principles:
- pass@k: probability of at least 1 success in k trials
- pass^k: probability all k trials succeed (reliability metric)

These tests run multiple trials with varied inputs to measure consistency,
not just capability.
"""

import pytest
import pytest_asyncio
import asyncio
import aiosqlite
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
import json

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db


# Number of trials for consistency testing
NUM_TRIALS = 3  # Keep low for dev; increase for CI


@dataclass
class TrialResult:
    """Result of a single trial."""
    success: bool
    trial_num: int
    message: str
    error: str | None = None
    response_snippet: str = ""


@dataclass
class ConsistencyReport:
    """Aggregate results across trials."""
    total_trials: int
    successes: int
    failures: int
    results: list[TrialResult] = field(default_factory=list)

    @property
    def pass_at_k(self) -> float:
        """Probability of at least 1 success (pass@k)."""
        return 1.0 if self.successes > 0 else 0.0

    @property
    def pass_k(self) -> float:
        """Probability all trials succeed (pass^k) - reliability metric."""
        return self.successes / self.total_trials if self.total_trials > 0 else 0.0

    @property
    def is_reliable(self) -> bool:
        """True if all trials passed (100% pass^k)."""
        return self.successes == self.total_trials


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
    """Database with known test data for each trial."""
    await db.create_book(title="Existing Book", author="Test Author", status="reading", rating=4)
    yield


# ============================================================================
# PARAMETERIZED SCENARIOS - Testing various phrasings and inputs
# ============================================================================

LIST_BOOKS_SCENARIOS = [
    pytest.param("show my books", id="basic_show"),
    pytest.param("list all books", id="list_all"),
    pytest.param("what books do I have", id="question_form"),
    pytest.param("show reading list", id="reading_list"),
    pytest.param("view my library", id="library"),
]

ADD_BOOK_SCENARIOS = [
    pytest.param(
        {"message": "add 'The Great Gatsby' by F. Scott Fitzgerald", "expected_title": "gatsby"},
        id="natural_language"
    ),
    pytest.param(
        {"message": "add a book called Test Novel", "expected_title": "test novel"},
        id="simple_add"
    ),
    pytest.param(
        {"message": "I want to read 'Dune' by Frank Herbert", "expected_title": "dune"},
        id="want_to_read_phrasing"
    ),
    pytest.param(
        {"message": "create book with form data [title=Form Book, author=Form Author, status=reading]",
         "expected_title": "form book"},
        id="form_submission"
    ),
]

DELETE_SCENARIOS = [
    pytest.param("delete book {id}", id="basic_delete"),
    pytest.param("remove book {id}", id="remove_phrasing"),
    pytest.param("delete book number {id}", id="with_number"),
]

STATUS_CHANGE_SCENARIOS = [
    pytest.param(
        {"message": "mark book {id} as finished", "expected_status": "finished"},
        id="mark_finished"
    ),
    pytest.param(
        {"message": "I finished reading book {id}", "expected_status": "finished"},
        id="finished_reading"
    ),
    pytest.param(
        {"message": "start reading book {id}", "expected_status": "reading"},
        id="start_reading"
    ),
    pytest.param(
        {"message": "change book {id} status to want-to-read", "expected_status": "want-to-read"},
        id="change_status"
    ),
]


# ============================================================================
# CONSISTENCY TESTS - Multiple trials per scenario
# ============================================================================

class TestListBooksConsistency:
    """Test consistency of listing books across multiple phrasings and trials."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("message", LIST_BOOKS_SCENARIOS)
    async def test_list_books_consistency(self, message, seeded_db):
        """
        Run multiple trials to verify consistent tool usage.

        A reliable agent should call list_books on EVERY request,
        not just sometimes.
        """
        report = ConsistencyReport(total_trials=NUM_TRIALS, successes=0, failures=0)

        for trial in range(NUM_TRIALS):
            router = AgentRouter()
            success = False
            error = None

            try:
                # Track tool calls
                tool_called = False
                original_fn = db.get_all_books

                async def tracked_fn():
                    nonlocal tool_called
                    tool_called = True
                    return await original_fn()

                # Patch and run
                import unittest.mock as mock
                with mock.patch.object(db, 'get_all_books', tracked_fn):
                    response = await router.process_user_message(message)

                # Eval: Tool must be called
                if tool_called and "Existing Book" in response:
                    success = True
                elif not tool_called:
                    error = "list_books tool was not called"
                else:
                    error = f"Response missing expected book. Got: {response[:200]}..."

            except Exception as e:
                error = str(e)

            result = TrialResult(
                success=success,
                trial_num=trial + 1,
                message=message,
                error=error,
                response_snippet=response[:100] if 'response' in dir() else ""
            )
            report.results.append(result)
            if success:
                report.successes += 1
            else:
                report.failures += 1

        # Report results
        print(f"\n{'='*60}")
        print(f"Scenario: {message}")
        print(f"pass@k: {report.pass_at_k:.0%} (at least 1 success)")
        print(f"pass^k: {report.pass_k:.0%} (reliability - all trials)")
        print(f"{'='*60}")

        for r in report.results:
            status = "✓" if r.success else "✗"
            print(f"  Trial {r.trial_num}: {status} {r.error or 'OK'}")

        # Assert reliability (all trials must pass for production-ready)
        assert report.is_reliable, (
            f"UNRELIABLE: pass^k = {report.pass_k:.0%}. "
            f"Agent succeeded {report.successes}/{report.total_trials} times. "
            f"Failures: {[r.error for r in report.results if not r.success]}"
        )


class TestAddBookConsistency:
    """Test consistency of adding books across scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", ADD_BOOK_SCENARIOS)
    async def test_add_book_consistency(self, scenario, clean_db):
        """
        Verify books are actually persisted across multiple trials.

        State-based eval: check database, not agent claims.
        """
        report = ConsistencyReport(total_trials=NUM_TRIALS, successes=0, failures=0)
        message = scenario["message"]
        expected_title = scenario["expected_title"]

        for trial in range(NUM_TRIALS):
            router = AgentRouter()
            success = False
            error = None

            try:
                # Clear DB for fresh trial
                async with aiosqlite.connect(db.DATABASE_PATH) as conn:
                    await conn.execute("DELETE FROM books")
                    await conn.commit()

                # Run agent
                response = await router.process_user_message(message)

                # STATE EVAL: Check database directly
                books = await db.get_all_books()
                titles_lower = [b["title"].lower() for b in books]

                if any(expected_title.lower() in t for t in titles_lower):
                    success = True
                else:
                    error = f"Book '{expected_title}' not in DB. Found: {titles_lower}"

            except Exception as e:
                error = str(e)

            result = TrialResult(
                success=success,
                trial_num=trial + 1,
                message=message,
                error=error
            )
            report.results.append(result)
            if success:
                report.successes += 1
            else:
                report.failures += 1

        # Report
        print(f"\n{'='*60}")
        print(f"Scenario: {message[:50]}...")
        print(f"Expected in DB: '{expected_title}'")
        print(f"pass@k: {report.pass_at_k:.0%} | pass^k: {report.pass_k:.0%}")
        print(f"{'='*60}")

        for r in report.results:
            status = "✓" if r.success else "✗"
            print(f"  Trial {r.trial_num}: {status} {r.error or 'OK'}")

        assert report.is_reliable, (
            f"UNRELIABLE: {report.successes}/{report.total_trials} trials succeeded"
        )


class TestStatusChangeConsistency:
    """Test consistency of status updates."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", STATUS_CHANGE_SCENARIOS)
    async def test_status_change_consistency(self, scenario, clean_db):
        """
        Verify status changes persist across trials.
        """
        report = ConsistencyReport(total_trials=NUM_TRIALS, successes=0, failures=0)
        message_template = scenario["message"]
        expected_status = scenario["expected_status"]

        for trial in range(NUM_TRIALS):
            router = AgentRouter()
            success = False
            error = None

            try:
                # Create a book with different status
                initial_status = "want-to-read" if expected_status != "want-to-read" else "finished"
                book = await db.create_book(
                    title=f"Trial {trial} Book",
                    author="Test",
                    status=initial_status
                )
                book_id = book["id"]

                # Run agent with book ID
                message = message_template.format(id=book_id)
                response = await router.process_user_message(message)

                # STATE EVAL: Check database
                updated = await db.get_book(book_id)

                if updated and updated["status"] == expected_status:
                    success = True
                else:
                    actual = updated["status"] if updated else "book not found"
                    error = f"Status is '{actual}', expected '{expected_status}'"

            except Exception as e:
                error = str(e)

            result = TrialResult(
                success=success,
                trial_num=trial + 1,
                message=message_template,
                error=error
            )
            report.results.append(result)
            if success:
                report.successes += 1
            else:
                report.failures += 1

        # Report
        print(f"\n{'='*60}")
        print(f"Scenario: {message_template}")
        print(f"Expected status: '{expected_status}'")
        print(f"pass@k: {report.pass_at_k:.0%} | pass^k: {report.pass_k:.0%}")
        print(f"{'='*60}")

        for r in report.results:
            status = "✓" if r.success else "✗"
            print(f"  Trial {r.trial_num}: {status} {r.error or 'OK'}")

        assert report.is_reliable, (
            f"UNRELIABLE: {report.successes}/{report.total_trials} trials succeeded"
        )


# ============================================================================
# AGGREGATE CONSISTENCY REPORT
# ============================================================================

class TestAggregateConsistency:
    """Generate aggregate consistency report across all scenarios."""

    @pytest.mark.asyncio
    async def test_overall_reliability_summary(self, clean_db):
        """
        Run a quick reliability check across key operations.

        This is a smoke test for overall agent reliability.
        """
        operations = [
            ("list_books", "show my books"),
            ("add_book", "add 'Quick Test' by Author"),
            ("search", "search for Quick"),
        ]

        results = {}

        for op_name, message in operations:
            successes = 0
            for _ in range(NUM_TRIALS):
                router = AgentRouter()
                try:
                    # Clear and seed for each trial
                    async with aiosqlite.connect(db.DATABASE_PATH) as conn:
                        await conn.execute("DELETE FROM books")
                        await conn.commit()

                    if op_name != "add_book":
                        await db.create_book(title="Quick Test", author="Test Author")

                    response = await router.process_user_message(message)

                    # Basic success check - response is non-empty HTML
                    if response and len(response) > 50 and "<" in response:
                        successes += 1

                except Exception:
                    pass

            results[op_name] = successes / NUM_TRIALS

        print("\n" + "="*60)
        print("AGGREGATE RELIABILITY REPORT (pass^k)")
        print("="*60)

        for op, rate in results.items():
            bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
            status = "✓" if rate == 1.0 else "⚠" if rate >= 0.5 else "✗"
            print(f"{op:15} [{bar}] {rate:.0%} {status}")

        print("="*60)

        # Overall reliability threshold
        overall = sum(results.values()) / len(results)
        assert overall >= 0.8, f"Overall reliability {overall:.0%} below 80% threshold"


# Run with: uv run pytest evals/test_tool_consistency.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
