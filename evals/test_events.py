# ABOUTME: Tests for the brooklet-backed application event stream.
# ABOUTME: Verifies emit_book_event envelope, fail-soft behavior, and tool integration.

"""
Tests for app.events and its integration with app.tools.

Covers:
  - emit_book_event produces to the "books" topic with the expected envelope
  - Brooklet's auto-injected metadata (_ts, _seq, _src) is present
  - Tool CRUD calls emit matching events (created/updated/deleted)
  - Update events carry both before and after snapshots
  - Failures inside emit are swallowed (fail-soft observability)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from app import events, tools


@pytest.fixture
def isolated_stream(tmp_path, monkeypatch):
    """Point the events module at a per-test temp directory."""
    events_dir = tmp_path / "events"
    monkeypatch.setattr(events, "EVENTS_DIR", events_dir)
    events.reset_stream_for_tests()
    yield events_dir
    events.reset_stream_for_tests()


def _consume_all(topic: str, group: str = "test") -> list[dict]:
    return list(events.get_stream().consume(topic, group=group))


# ----------------------------------------------------------------------
# emit_book_event — envelope + metadata
# ----------------------------------------------------------------------

def test_emit_created_produces_expected_envelope(isolated_stream):
    events.emit_book_event("created", book_id=1, before=None, after={"id": 1, "title": "Dune"})

    [ev] = _consume_all("books")
    assert ev["type"] == "created"
    assert ev["id"] == 1
    assert ev["before"] is None
    assert ev["after"] == {"id": 1, "title": "Dune"}
    # Brooklet-injected metadata
    assert "_ts" in ev
    assert ev["_seq"] == 1
    assert ev["_src"] == "tools"


def test_emit_updated_carries_before_and_after(isolated_stream):
    before = {"id": 7, "status": "reading", "rating": None}
    after = {"id": 7, "status": "finished", "rating": 5}
    events.emit_book_event("updated", book_id=7, before=before, after=after)

    [ev] = _consume_all("books")
    assert ev["type"] == "updated"
    assert ev["before"] == before
    assert ev["after"] == after


def test_emit_deleted_has_no_after(isolated_stream):
    before = {"id": 3, "title": "Gone"}
    events.emit_book_event("deleted", book_id=3, before=before, after=None)

    [ev] = _consume_all("books")
    assert ev["type"] == "deleted"
    assert ev["before"] == before
    assert ev["after"] is None


def test_sequence_numbers_monotonic(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1})
    events.emit_book_event("updated", book_id=1, before={"id": 1}, after={"id": 1, "status": "reading"})
    events.emit_book_event("deleted", book_id=1, before={"id": 1})

    seqs = [ev["_seq"] for ev in _consume_all("books")]
    assert seqs == [1, 2, 3]


# ----------------------------------------------------------------------
# Fail-soft: emit never raises
# ----------------------------------------------------------------------

def test_emit_is_fail_soft(isolated_stream, monkeypatch, caplog):
    """A broken stream must never surface as an exception."""
    class BrokenStream:
        def produce(self, *_args, **_kwargs):
            raise RuntimeError("disk exploded")

    monkeypatch.setattr(events, "get_stream", lambda: BrokenStream())

    # Should not raise
    events.emit_book_event("created", book_id=99, after={"id": 99})

    # But should log a warning
    assert any("Failed to emit book event" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# Tool integration — events emitted on CRUD
# ----------------------------------------------------------------------

def _unwrap(response: dict) -> dict:
    """Tools return {'content': [{'type': 'text', 'text': json_str}]}."""
    assert not response.get("is_error"), response
    return json.loads(response["content"][0]["text"])


@pytest_asyncio.fixture
async def clean_db(tmp_path, monkeypatch):
    """Use an isolated SQLite DB per test so tool calls don't touch real data."""
    from app import database as db
    import aiosqlite

    db_path = tmp_path / "reading_list.db"
    monkeypatch.setattr(db, "DATABASE_PATH", db_path)
    await db.init_db()
    yield
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("DELETE FROM books")
        await conn.commit()


@pytest.mark.asyncio
async def test_create_book_tool_emits_created_event(isolated_stream, clean_db):
    resp = _unwrap(await tools.create_book.handler({"title": "Neuromancer", "author": "Gibson"}))
    book_id = resp["book"]["id"]

    [ev] = _consume_all("books")
    assert ev["type"] == "created"
    assert ev["id"] == book_id
    assert ev["before"] is None
    assert ev["after"]["title"] == "Neuromancer"
    assert ev["after"]["author"] == "Gibson"


@pytest.mark.asyncio
async def test_update_book_tool_emits_before_and_after(isolated_stream, clean_db):
    created = _unwrap(await tools.create_book.handler({"title": "Dune", "status": "want-to-read"}))
    book_id = created["book"]["id"]

    _unwrap(await tools.update_book.handler({"id": str(book_id), "status": "reading", "rating": 5}))

    evs = _consume_all("books")
    assert [e["type"] for e in evs] == ["created", "updated"]

    update_ev = evs[1]
    assert update_ev["before"]["status"] == "want-to-read"
    assert update_ev["before"]["rating"] is None
    assert update_ev["after"]["status"] == "reading"
    assert update_ev["after"]["rating"] == 5


@pytest.mark.asyncio
async def test_delete_book_tool_emits_deleted_event(isolated_stream, clean_db):
    created = _unwrap(await tools.create_book.handler({"title": "Ephemeral"}))
    book_id = created["book"]["id"]

    _unwrap(await tools.delete_book.handler({"id": str(book_id)}))

    evs = _consume_all("books")
    assert [e["type"] for e in evs] == ["created", "deleted"]
    assert evs[1]["before"]["title"] == "Ephemeral"
    assert evs[1]["after"] is None


# ----------------------------------------------------------------------
# Agent message events
# ----------------------------------------------------------------------

def test_emit_agent_message_envelope(isolated_stream):
    events.emit_agent_message("ui", "recommender", "what should I read?", response="Try Dune.")

    [ev] = _consume_all("agent.messages")
    assert ev["from"] == "ui"
    assert ev["to"] == "recommender"
    assert ev["message"] == "what should I read?"
    assert ev["response"] == "Try Dune."
    assert ev["_src"] == "agent:ui"  # source identifies the producer agent
    assert ev["_seq"] == 1


def test_agent_message_emit_is_fail_soft(isolated_stream, monkeypatch, caplog):
    class BrokenStream:
        def produce(self, *_args, **_kwargs):
            raise RuntimeError("disk exploded")

    monkeypatch.setattr(events, "get_stream", lambda: BrokenStream())
    events.emit_agent_message("ui", "recommender", "hi", response="ok")
    assert any("Failed to emit agent message" in r.message for r in caplog.records)


def test_books_and_agent_messages_are_separate_topics(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1, "title": "X"})
    events.emit_agent_message("user", "ui", "list books", response="<ul>...</ul>")

    assert len(_consume_all("books", group="g1")) == 1
    assert len(_consume_all("agent.messages", group="g2")) == 1


# ----------------------------------------------------------------------
# read_recent helper
# ----------------------------------------------------------------------

def test_read_recent_returns_empty_for_unknown_topic(isolated_stream):
    # Stream is empty; topic doesn't exist yet.
    assert events.read_recent("books") == []
    assert events.read_recent("nonexistent.topic") == []


def test_read_recent_respects_limit_and_returns_tail(isolated_stream):
    for i in range(5):
        events.emit_book_event("created", book_id=i, after={"id": i, "title": f"Book {i}"})

    recent = events.read_recent("books", limit=3)
    assert len(recent) == 3
    # Tail = the most recent 3 in append order
    assert [e["id"] for e in recent] == [2, 3, 4]


def test_read_recent_does_not_advance_real_consumer_offset(isolated_stream):
    """Two read_recent calls should both return all events — throwaway groups."""
    events.emit_book_event("created", book_id=1, after={"id": 1})
    events.emit_book_event("created", book_id=2, after={"id": 2})

    first = events.read_recent("books", limit=10)
    second = events.read_recent("books", limit=10)
    assert len(first) == 2
    assert len(second) == 2  # would be 0 if we'd reused a consumer group


# ----------------------------------------------------------------------
# Agent-facing tools: get_recent_activity, get_agent_messages
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_recent_activity_returns_newest_first(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1, "title": "Old"})
    events.emit_book_event("created", book_id=2, after={"id": 2, "title": "New"})

    resp = _unwrap(await tools.get_recent_activity.handler({}))
    ids = [e["id"] for e in resp["events"]]
    assert ids == [2, 1]  # newest first


@pytest.mark.asyncio
async def test_get_recent_activity_filters_by_book_id(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1})
    events.emit_book_event("updated", book_id=1, before={"id": 1}, after={"id": 1, "status": "reading"})
    events.emit_book_event("created", book_id=2, after={"id": 2})

    resp = _unwrap(await tools.get_recent_activity.handler({"book_id": 1}))
    assert resp["count"] == 2
    assert all(e["id"] == 1 for e in resp["events"])
    assert resp["filters"]["book_id"] == 1


@pytest.mark.asyncio
async def test_get_recent_activity_filters_by_type(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1})
    events.emit_book_event("updated", book_id=1, before={"id": 1}, after={"id": 1, "status": "finished"})
    events.emit_book_event("deleted", book_id=1, before={"id": 1})

    resp = _unwrap(await tools.get_recent_activity.handler({"type": "updated"}))
    assert resp["count"] == 1
    assert resp["events"][0]["type"] == "updated"


@pytest.mark.asyncio
async def test_get_recent_activity_caps_limit(isolated_stream):
    for i in range(50):
        events.emit_book_event("created", book_id=i, after={"id": i})

    resp = _unwrap(await tools.get_recent_activity.handler({"limit": 5}))
    assert resp["count"] == 5
    # Newest 5 = ids 49..45
    assert [e["id"] for e in resp["events"]] == [49, 48, 47, 46, 45]


@pytest.mark.asyncio
async def test_get_recent_activity_combined_filters(isolated_stream):
    events.emit_book_event("created", book_id=1, after={"id": 1})
    events.emit_book_event("updated", book_id=1, before={"id": 1}, after={"id": 1, "rating": 5})
    events.emit_book_event("updated", book_id=2, before={"id": 2}, after={"id": 2, "rating": 3})

    resp = _unwrap(await tools.get_recent_activity.handler({"book_id": 1, "type": "updated"}))
    assert resp["count"] == 1
    assert resp["events"][0]["id"] == 1
    assert resp["events"][0]["type"] == "updated"


@pytest.mark.asyncio
async def test_get_recent_activity_empty_stream(isolated_stream):
    resp = _unwrap(await tools.get_recent_activity.handler({}))
    assert resp["count"] == 0
    assert resp["events"] == []


@pytest.mark.asyncio
async def test_get_agent_messages_returns_newest_first(isolated_stream):
    events.emit_agent_message("user", "ui", "first", response="r1")
    events.emit_agent_message("ui", "recommender", "second", response="r2")

    resp = _unwrap(await tools.get_agent_messages.handler({}))
    assert resp["count"] == 2
    assert resp["messages"][0]["message"] == "second"
    assert resp["messages"][1]["message"] == "first"


@pytest.mark.asyncio
async def test_get_agent_messages_respects_limit(isolated_stream):
    for i in range(10):
        events.emit_agent_message("user", "ui", f"msg-{i}", response="ok")

    resp = _unwrap(await tools.get_agent_messages.handler({"limit": 3}))
    assert resp["count"] == 3
    # Newest 3 → msg-9, msg-8, msg-7
    assert [m["message"] for m in resp["messages"]] == ["msg-9", "msg-8", "msg-7"]


@pytest.mark.asyncio
async def test_get_recent_activity_book_id_zero_works(isolated_stream):
    """Falsy-but-valid book_id (0) must not be skipped by the filter logic."""
    events.emit_book_event("created", book_id=0, after={"id": 0, "title": "Zero"})
    events.emit_book_event("created", book_id=1, after={"id": 1, "title": "One"})

    resp = _unwrap(await tools.get_recent_activity.handler({"book_id": 0}))
    assert resp["count"] == 1
    assert resp["events"][0]["id"] == 0
