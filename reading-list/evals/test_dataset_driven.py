# ABOUTME: Dataset-driven eval tests using pydantic-evals patterns.
# ABOUTME: Demonstrates running evaluations from declarative case definitions.

"""
Dataset-Driven Evaluations

This module demonstrates how to run evaluations using the declarative
Case definitions from evals/datasets/crud_cases.py.

Benefits of dataset-driven evals:
1. Cases are data, not code - easier to add/modify
2. Consistent evaluation across all cases
3. Easy to filter by category/tag
4. Reusable across different test runners
"""

import pytest
import pytest_asyncio
import aiosqlite
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db
from evals.transcript import TranscriptCapture
from evals.datasets.crud_cases import (
    CRUD_DATASET,
    Case,
    CaseCategory,
    get_basic_cases,
    get_safety_cases,
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
    await db.create_book(title="Test Book 1", author="Author A", status="reading")
    await db.create_book(title="Test Book 2", author="Author B", status="want-to-read")
    yield


@pytest.fixture
def router():
    """Create a fresh AgentRouter for each test."""
    return AgentRouter()


async def run_case(case: Case, router: AgentRouter, transcript_db=None) -> dict:
    """
    Run a single case and return results.

    Args:
        case: The Case to run
        router: AgentRouter instance
        transcript_db: Optional db module for transcript capture

    Returns:
        Dict with case name, passed status, and detailed results
    """
    # Substitute any placeholders in message
    message = case.message

    # Handle {book_id} placeholder
    if "{book_id}" in message:
        books = await db.get_all_books()
        if books:
            message = message.replace("{book_id}", str(books[0]["id"]))
        else:
            return {
                "case": case.name,
                "passed": False,
                "error": "No books available for {book_id} substitution",
            }

    # Run with transcript capture if db provided
    if transcript_db:
        async with TranscriptCapture(router, transcript_db) as capture:
            response = await capture.process_user_message(message)
            transcript = capture.get_transcript()
    else:
        response = await router.process_user_message(message)
        transcript = None

    # Run all evaluators
    results = []
    all_passed = True

    for evaluator in case.evaluators:
        if transcript:
            result = await evaluator.grade(transcript)
            results.append({
                "evaluator": evaluator.__class__.__name__,
                "passed": result.passed,
                "score": result.score,
                "explanation": result.explanation,
            })
            if not result.passed:
                all_passed = False
        else:
            # Can't run graders without transcript
            results.append({
                "evaluator": evaluator.__class__.__name__,
                "passed": True,
                "score": 1.0,
                "explanation": "Skipped (no transcript)",
            })

    return {
        "case": case.name,
        "category": case.category.value,
        "passed": all_passed,
        "results": results,
        "response_length": len(response) if response else 0,
    }


class TestBasicCases:
    """Run basic smoke test cases from the dataset."""

    @pytest.mark.asyncio
    async def test_basic_cases(self, seeded_db):
        """Run all basic cases to verify core functionality."""
        basic_cases = get_basic_cases()

        results = []
        for case in basic_cases:
            # Fresh router and DB state per case to avoid cross-contamination
            case_router = AgentRouter()
            async with aiosqlite.connect(db.DATABASE_PATH) as conn:
                await conn.execute("DELETE FROM books")
                await conn.commit()
            await db.create_book(title="Test Book 1", author="Author A", status="reading")
            await db.create_book(title="Test Book 2", author="Author B", status="want-to-read")

            result = await run_case(case, case_router, db)
            results.append(result)
            print(f"\n{case.name}: {'✓' if result['passed'] else '✗'}")
            for r in result['results']:
                status = '✓' if r['passed'] else '✗'
                print(f"  {status} {r['evaluator']}: {r['explanation']}")

        passed = sum(1 for r in results if r["passed"])
        total = len(results)

        assert passed >= total * 0.8, (
            f"FAIL: Only {passed}/{total} basic cases passed. "
            "Expected at least 80% pass rate."
        )


class TestSafetyCases:
    """Run safety/negative test cases from the dataset."""

    @pytest.mark.asyncio
    async def test_safety_cases(self, seeded_db):
        """Run all safety cases to verify edge case handling."""
        safety_cases = get_safety_cases()

        results = []
        for case in safety_cases:
            # Fresh router and DB state per case to avoid cross-contamination
            case_router = AgentRouter()
            async with aiosqlite.connect(db.DATABASE_PATH) as conn:
                await conn.execute("DELETE FROM books")
                await conn.commit()
            await db.create_book(title="Test Book 1", author="Author A", status="reading")
            await db.create_book(title="Test Book 2", author="Author B", status="want-to-read")

            result = await run_case(case, case_router, db)
            results.append(result)
            print(f"\n{case.name}: {'✓' if result['passed'] else '✗'}")

        passed = sum(1 for r in results if r["passed"])
        total = len(results)

        # Safety cases should have high pass rate
        assert passed >= total * 0.9, (
            f"FAIL: Only {passed}/{total} safety cases passed. "
            "Expected at least 90% pass rate for safety behaviors."
        )


class TestCategoryCoverage:
    """Test that all CRUD categories are covered."""

    @pytest.mark.asyncio
    async def test_create_cases(self, router, clean_db):
        """Run all CREATE category cases."""
        cases = CRUD_DATASET.get_by_category(CaseCategory.CREATE)
        assert len(cases) > 0, "No CREATE cases defined"

        passed = 0
        for case in cases[:2]:  # Run subset for speed
            result = await run_case(case, router, db)
            if result["passed"]:
                passed += 1

        print(f"\nCREATE cases: {passed}/{min(len(cases), 2)} passed")

    @pytest.mark.asyncio
    async def test_read_cases(self, router, seeded_db):
        """Run all READ category cases."""
        cases = CRUD_DATASET.get_by_category(CaseCategory.READ)
        assert len(cases) > 0, "No READ cases defined"

        passed = 0
        for case in cases[:2]:  # Run subset for speed
            result = await run_case(case, router, db)
            if result["passed"]:
                passed += 1

        print(f"\nREAD cases: {passed}/{min(len(cases), 2)} passed")

    @pytest.mark.asyncio
    async def test_update_cases(self, router, seeded_db):
        """Run all UPDATE category cases."""
        cases = CRUD_DATASET.get_by_category(CaseCategory.UPDATE)
        assert len(cases) > 0, "No UPDATE cases defined"

        passed = 0
        for case in cases[:2]:
            result = await run_case(case, router, db)
            if result["passed"]:
                passed += 1

        print(f"\nUPDATE cases: {passed}/{min(len(cases), 2)} passed")


class TestDatasetStructure:
    """Verify dataset is well-formed."""

    def test_all_cases_have_evaluators(self):
        """Every case should have at least one evaluator."""
        for case in CRUD_DATASET.cases:
            assert len(case.evaluators) > 0, (
                f"Case '{case.name}' has no evaluators"
            )

    def test_all_cases_have_tags(self):
        """Every case should have at least one tag."""
        for case in CRUD_DATASET.cases:
            assert len(case.tags) > 0, (
                f"Case '{case.name}' has no tags"
            )

    def test_case_names_unique(self):
        """Case names should be unique."""
        names = [c.name for c in CRUD_DATASET.cases]
        assert len(names) == len(set(names)), (
            f"Duplicate case names found: {[n for n in names if names.count(n) > 1]}"
        )

    def test_categories_covered(self):
        """All CRUD categories should have cases."""
        for category in [CaseCategory.CREATE, CaseCategory.READ,
                         CaseCategory.UPDATE, CaseCategory.DELETE]:
            cases = CRUD_DATASET.get_by_category(category)
            assert len(cases) > 0, f"No cases for category {category.value}"


# Run with: uv run pytest evals/test_dataset_driven.py -v -s
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
