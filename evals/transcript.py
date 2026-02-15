# ABOUTME: Transcript capture system for recording complete eval trial information.
# ABOUTME: Captures tool calls, agent messages, database state, and timing for debugging.

"""
Transcript Capture System for Agent Evals

Captures complete trial information for debugging and analysis:
- Tool calls with arguments and results
- Inter-agent message flow
- Database state snapshots (before/after)
- HTML responses
- Timing information

Usage:
    async with TranscriptCapture(router) as capture:
        response = await capture.process_user_message("show my books")
        transcript = capture.get_transcript()
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch


@dataclass
class ToolCallRecord:
    """Record of a single tool call during agent execution."""
    name: str
    args: dict[str, Any]
    result: Any
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentMessageRecord:
    """Record of an inter-agent message."""
    from_agent: str
    to_agent: str
    content: str
    response: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "from": self.from_agent,
            "to": self.to_agent,
            "content": self.content,
            "response": self.response,
            "timestamp": self.timestamp,
        }


@dataclass
class DatabaseSnapshot:
    """Snapshot of database state at a point in time."""
    timestamp: str
    books: list[dict]
    stats: dict

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "books": self.books,
            "stats": self.stats,
        }


@dataclass
class TrialTranscript:
    """Complete record of a single eval trial."""
    trial_id: str
    timestamp: str
    user_message: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    agent_messages: list[AgentMessageRecord] = field(default_factory=list)
    state_before: DatabaseSnapshot | None = None
    state_after: DatabaseSnapshot | None = None
    html_response: str = ""
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "trial_id": self.trial_id,
            "timestamp": self.timestamp,
            "user_message": self.user_message,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "agent_messages": [am.to_dict() for am in self.agent_messages],
            "state_before": self.state_before.to_dict() if self.state_before else None,
            "state_after": self.state_after.to_dict() if self.state_after else None,
            "html_response": self.html_response[:2000] if self.html_response else "",
            "duration_ms": self.duration_ms,
            "error": self.error,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class TranscriptCapture:
    """
    Context manager that captures complete trial transcripts.

    Wraps router.process_user_message() to track all activity.

    Example:
        async with TranscriptCapture(router, db_module) as capture:
            response = await capture.process_user_message("add book X")
            transcript = capture.get_transcript()
    """

    TRANSCRIPTS_DIR = Path("data/eval_transcripts")

    def __init__(self, router, db_module=None, save_to_disk: bool = False):
        """
        Initialize transcript capture.

        Args:
            router: AgentRouter instance
            db_module: Database module for state snapshots (optional)
            save_to_disk: Whether to save transcripts (or use CAPTURE_TRANSCRIPTS env)
        """
        self.router = router
        self.db = db_module
        self.save_to_disk = save_to_disk or os.environ.get("CAPTURE_TRANSCRIPTS") == "1"
        self.transcript: TrialTranscript | None = None
        self._patches: list = []
        self._original_fns: dict = {}

    async def __aenter__(self):
        """Set up capture hooks."""
        self._setup_tool_tracking()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up capture hooks and optionally save transcript."""
        self._cleanup_patches()
        if self.save_to_disk and self.transcript:
            await self._save_transcript()
        return False

    async def process_user_message(self, message: str) -> str:
        """
        Process a user message while capturing full transcript.

        Args:
            message: User's natural language message

        Returns:
            HTML response from agent
        """
        trial_id = f"trial_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        self.transcript = TrialTranscript(
            trial_id=trial_id,
            timestamp=datetime.now().isoformat(),
            user_message=message,
        )

        # Capture state before
        if self.db:
            self.transcript.state_before = await self._capture_db_state()

        start_time = time.perf_counter()

        try:
            response = await self.router.process_user_message(message)
            self.transcript.html_response = response
        except Exception as e:
            self.transcript.error = str(e)
            raise
        finally:
            end_time = time.perf_counter()
            self.transcript.duration_ms = int((end_time - start_time) * 1000)

            # Capture state after
            if self.db:
                self.transcript.state_after = await self._capture_db_state()

            # Capture agent messages from router's log
            if hasattr(self.router, 'get_message_log'):
                log = self.router.get_message_log()
                for msg in log.messages:
                    self.transcript.agent_messages.append(
                        AgentMessageRecord(
                            from_agent=msg.from_agent,
                            to_agent=msg.to_agent,
                            content=msg.message,
                            response=msg.response,
                            timestamp=msg.timestamp,
                        )
                    )

        return response

    def get_transcript(self) -> TrialTranscript | None:
        """Get the captured transcript."""
        return self.transcript

    def _setup_tool_tracking(self):
        """Set up patches to track database tool calls."""
        if not self.db:
            return

        tool_names = [
            'get_all_books', 'get_book', 'create_book',
            'update_book', 'delete_book', 'search_books', 'get_stats'
        ]

        for tool_name in tool_names:
            if hasattr(self.db, tool_name):
                original_fn = getattr(self.db, tool_name)
                self._original_fns[tool_name] = original_fn

                # Create tracked wrapper
                tracked_fn = self._create_tracked_fn(tool_name, original_fn)

                # Apply patch
                patcher = patch.object(self.db, tool_name, tracked_fn)
                patcher.start()
                self._patches.append(patcher)

    def _create_tracked_fn(self, tool_name: str, original_fn):
        """Create a tracked version of a database function."""
        capture = self

        async def tracked_fn(*args, **kwargs):
            start = time.perf_counter()
            result = await original_fn(*args, **kwargs)
            duration = int((time.perf_counter() - start) * 1000)

            if capture.transcript:
                capture.transcript.tool_calls.append(
                    ToolCallRecord(
                        name=tool_name,
                        args={"args": args, "kwargs": kwargs},
                        result=result,
                        duration_ms=duration,
                    )
                )

            return result

        return tracked_fn

    def _cleanup_patches(self):
        """Stop all patches."""
        for patcher in self._patches:
            patcher.stop()
        self._patches.clear()

    async def _capture_db_state(self) -> DatabaseSnapshot:
        """Capture current database state."""
        try:
            # Use original functions to avoid infinite recursion
            get_all = self._original_fns.get('get_all_books', self.db.get_all_books)
            get_stats = self._original_fns.get('get_stats', self.db.get_stats)

            books = await get_all()
            stats = await get_stats()
        except Exception:
            books = []
            stats = {}

        return DatabaseSnapshot(
            timestamp=datetime.now().isoformat(),
            books=books,
            stats=stats,
        )

    async def _save_transcript(self):
        """Save transcript to disk."""
        if not self.transcript:
            return

        self.TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

        filename = f"{self.transcript.trial_id}.json"
        filepath = self.TRANSCRIPTS_DIR / filename

        filepath.write_text(self.transcript.to_json())


def capture_enabled() -> bool:
    """Check if transcript capture is enabled via environment variable."""
    return os.environ.get("CAPTURE_TRANSCRIPTS") == "1"
