# ABOUTME: Application event stream backed by brooklet — a file-native JSONL log.
# ABOUTME: Emits domain events (book lifecycle) and agent events to data/events/.

"""
Application events using brooklet (the "SQLite of event streaming").

The Stream is a singleton rooted at data/events/. Any part of the app can
import emit_* functions and produce events; any number of consumers (the
debug endpoint, eval transcripts, future analytics) can read them with
independent offsets per consumer group.

Brooklet auto-injects envelope metadata on every event:
    _ts   — ISO 8601 timestamp
    _seq  — monotonic sequence number
    _src  — producer identifier (defaults to topic name)

So our payloads only carry domain data, not metadata.

Design choices:
  - Single topic "books" for the full book lifecycle. Consumers see create /
    update / delete in the order they happened, on one subscription. Filtering
    by "type" is a cheap dict lookup.
  - Before + after payload on updates. Self-describing — consumers can tell
    what changed without re-querying the DB, which supports activity feeds,
    audit trails, reading-velocity analysis, and streak tracking from one stream.
  - Emits are fail-soft. The event log is an observability concern, not a
    correctness one; a broken stream must not break user-facing book ops.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import brooklet

logger = logging.getLogger(__name__)

# Stream directory lives next to the SQLite DB — same "data lives in data/" convention.
EVENTS_DIR = Path("data/events")

# Single topic for all book lifecycle events. Nested-path names like "domain/books"
# are supported by brooklet, but flat is fine until we have a second aggregate.
BOOKS_TOPIC = "books"

# Inter-agent message topic. Nested name pairs nicely with future agent.* topics
# (e.g. agent.tool_calls, agent.errors) without colliding with domain topics.
AGENT_MESSAGES_TOPIC = "agent.messages"

_stream: brooklet.Stream | None = None


def get_stream() -> brooklet.Stream:
    """Lazy-init the module-level stream. Safe to call repeatedly."""
    global _stream
    if _stream is None:
        EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        _stream = brooklet.open(EVENTS_DIR)
    return _stream


def reset_stream_for_tests() -> None:
    """Clear the cached stream so tests can point EVENTS_DIR elsewhere."""
    global _stream
    _stream = None


def emit_book_event(
    action: str,
    book_id: int,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    """Emit a book lifecycle event to the brooklet stream.

    Args:
        action: "created" | "updated" | "deleted"
        book_id: primary key of the affected book
        before: state before the change (None on create)
        after:  state after the change  (None on delete)

    Envelope (brooklet auto-injects _ts, _seq, _src):
        {"type": action, "id": book_id, "before": ..., "after": ...}

    Never raises. A failure here logs a warning and returns — the event log
    is observability, not correctness.
    """
    try:
        get_stream().produce(
            BOOKS_TOPIC,
            {"type": action, "id": book_id, "before": before, "after": after},
            source="tools",
        )
    except Exception as exc:  # noqa: BLE001 — fail-soft by design
        logger.warning("Failed to emit book event (%s id=%s): %s", action, book_id, exc)


def emit_agent_message(
    from_agent: str,
    to_agent: str,
    message: str,
    response: str | None = None,
) -> None:
    """Emit an inter-agent message to the brooklet stream.

    Called from AgentRouter alongside the in-memory MessageLog. Same fail-soft
    contract as emit_book_event — the event log must never break agent flow.

    The response field can be None (message just sent), or filled in once the
    target agent replies. Today we emit one event per completed exchange (so
    response is populated); if we later need request/response correlation
    across topics, we'll add a request_id field.
    """
    try:
        get_stream().produce(
            AGENT_MESSAGES_TOPIC,
            {"from": from_agent, "to": to_agent, "message": message, "response": response},
            source=f"agent:{from_agent}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to emit agent message (%s→%s): %s", from_agent, to_agent, exc)


def read_recent(topic: str, limit: int = 50) -> list[dict[str, Any]]:
    """Read recent events from a topic with a throwaway consumer group.

    Each call uses a fresh group name so it doesn't advance any real consumer's
    offset — safe for debug endpoints, polling UIs, and ad-hoc inspection.
    Returns an empty list if the topic doesn't exist yet.

    For long-lived consumers (analytics, derived views), call get_stream() and
    use a stable group name so offsets persist across restarts.
    """
    stream = get_stream()
    if topic not in list(stream.topics()):
        return []
    consumer = stream.consume(topic, group=f"ephemeral-{uuid.uuid4().hex[:8]}")
    all_events = list(consumer)
    return all_events[-limit:] if limit else all_events
