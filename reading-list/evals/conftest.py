# ABOUTME: Shared pytest fixtures for the eval suite.
# ABOUTME: Provides database isolation, router instances, and transcript capture.

"""
Shared Fixtures for Agent Evals

Centralizes common fixtures so test files can focus on test logic.
Fixtures provided:
- clean_db: Clean database state
- seeded_db: Database with known test data
- router: Fresh AgentRouter instance
- transcript_capture: TranscriptCapture context manager

Enable transcript saving via: CAPTURE_TRANSCRIPTS=1
"""

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
import aiosqlite

# Ensure app module is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents import AgentRouter
from app import database as db
from evals.transcript import TranscriptCapture


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest_asyncio.fixture
async def clean_db():
    """
    Set up a clean database for each test.

    Ensures database exists, clears all data, yields for test,
    then cleans up after.
    """
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
    """
    Database with known test data.

    Provides 3 books in different states for comprehensive testing:
    - Finished book with rating
    - Currently reading book
    - Want-to-read book
    """
    await db.create_book(
        title="Test Book 1",
        author="Author A",
        status="finished",
        rating=5,
        notes="A great book",
    )
    await db.create_book(
        title="Test Book 2",
        author="Author B",
        status="reading",
    )
    await db.create_book(
        title="Test Book 3",
        author="Author C",
        status="want-to-read",
    )
    yield


@pytest_asyncio.fixture
async def empty_db(clean_db):
    """
    Explicitly empty database (alias for clean_db with clearer intent).
    """
    yield


# ============================================================================
# ROUTER FIXTURES
# ============================================================================

@pytest.fixture
def router():
    """
    Create a fresh AgentRouter for each test.

    Returns an uninitialized router - it will auto-initialize
    on first process_user_message() call.
    """
    return AgentRouter()


@pytest_asyncio.fixture
async def initialized_router():
    """
    Create and initialize an AgentRouter.

    Use this when you need to inspect router state before sending messages.
    """
    router = AgentRouter()
    await router.initialize()
    yield router
    await router.close()


# ============================================================================
# TRANSCRIPT CAPTURE FIXTURES
# ============================================================================

@pytest.fixture
def capture_enabled():
    """
    Check if transcript capture is enabled via environment.

    Returns True if CAPTURE_TRANSCRIPTS=1 is set.
    """
    return os.environ.get("CAPTURE_TRANSCRIPTS") == "1"


@pytest_asyncio.fixture
async def transcript_capture(router):
    """
    TranscriptCapture instance for capturing trial transcripts.

    Usage:
        async def test_something(transcript_capture):
            async with transcript_capture as capture:
                response = await capture.process_user_message("show books")
                transcript = capture.get_transcript()

    Transcripts are saved to data/eval_transcripts/ if CAPTURE_TRANSCRIPTS=1.
    """
    capture = TranscriptCapture(
        router=router,
        db_module=db,
        save_to_disk=os.environ.get("CAPTURE_TRANSCRIPTS") == "1",
    )
    yield capture


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_books():
    """
    Sample book data for testing.

    Returns a list of book dicts that can be inserted into the database.
    """
    return [
        {
            "title": "The Great Gatsby",
            "author": "F. Scott Fitzgerald",
            "status": "finished",
            "rating": 5,
            "notes": "A classic",
        },
        {
            "title": "1984",
            "author": "George Orwell",
            "status": "finished",
            "rating": 4,
        },
        {
            "title": "Dune",
            "author": "Frank Herbert",
            "status": "reading",
        },
        {
            "title": "Project Hail Mary",
            "author": "Andy Weir",
            "status": "want-to-read",
        },
    ]


@pytest_asyncio.fixture
async def rich_db(clean_db, sample_books):
    """
    Database with richer test data (4 books with varied content).

    Good for testing search, recommendations, and stats.
    """
    for book in sample_books:
        await db.create_book(**book)
    yield


# ============================================================================
# EVAL CONFIGURATION
# ============================================================================

# Number of trials for consistency tests
NUM_TRIALS = int(os.environ.get("EVAL_TRIALS", "3"))

# Minimum pass rate for reliability (pass^k)
MIN_RELIABILITY = float(os.environ.get("EVAL_MIN_RELIABILITY", "1.0"))


@pytest.fixture
def eval_config():
    """
    Configuration for eval runs.

    Adjustable via environment variables:
    - EVAL_TRIALS: Number of trials per scenario (default 3)
    - EVAL_MIN_RELIABILITY: Minimum pass^k threshold (default 1.0)
    """
    return {
        "num_trials": NUM_TRIALS,
        "min_reliability": MIN_RELIABILITY,
        "capture_transcripts": os.environ.get("CAPTURE_TRANSCRIPTS") == "1",
    }
