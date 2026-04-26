# ABOUTME: Activity feed FAST PATH — non-LLM render of the books topic.
# ABOUTME: Mirrors the saved-views fast path; the UI agent handles richer slicing.

"""
Activity feed (fast path).

This module is the no-LLM rendering of the books event stream. It powers
the `/activity` HTTP endpoint and the "Activity" nav button — instant load,
no agent call, default style.

Three-tier rendering across the app:

  1. Saved views   — instant, no LLM, no even-tool call (cached HTML or
                     tiny template + DB query). See app/saved_views.py.
  2. /activity     — instant, no LLM, default style. THIS MODULE.
  3. Agent route   — LLM-driven. Custom slicing ("filter by Dune",
                     "only finished books"), custom phrasing, full
                     skill-driven render. The agent calls the
                     get_recent_activity tool (app/tools.py) and renders
                     using app/skills/ui.md guidance.

The agent path is the primary one for any non-trivial query. Keep this
fast path's renderer simple and predictable — it's the fallback, not the
star.

Design:
  - Pure rendering: event dict in, string out. No I/O, no DB re-queries.
    The before/after envelope from emit_book_event is self-describing.
  - Reverse chronological: newest first.
  - HTML matches the dark theme defined in app/skills/ui.md.
"""

from __future__ import annotations

import html
from typing import Any

from app import events

# Max events to render in the feed. Brooklet reads are O(file size) for now;
# this is fine for the prototype.
DEFAULT_LIMIT = 20


# ---------------------------------------------------------------------------
# Per-event line renderer  ←  La Boeuf's contribution lives here
# ---------------------------------------------------------------------------
#
# The activity feed needs to turn a raw event into a human-readable line.
# Event shapes (from app/events.py emit_book_event):
#
#   created:  {"type": "created", "id": 1, "before": None,
#              "after": {"id": 1, "title": "Dune", "author": "Herbert",
#                        "status": "want-to-read", "rating": None, "notes": ""}}
#
#   updated:  {"type": "updated", "id": 1,
#              "before": {..., "status": "reading", "rating": None},
#              "after":  {..., "status": "finished", "rating": 5}}
#
#   deleted:  {"type": "deleted", "id": 1,
#              "before": {..., "title": "Dune"}, "after": None}
#
# Plus brooklet-injected envelope: _ts (ISO timestamp), _seq, _src.
#
# The renderer should return a single short string describing what happened.
# Examples (these are just my suggestions — your call on tone, format, what
# to surface):
#
#   "Added 'Dune' by Herbert"
#   "Started reading 'Dune'"
#   "Finished 'Dune' and rated it 5/5"
#   "Updated notes on 'Dune'"
#   "Removed 'Dune' from your list"
#
# Design questions worth thinking about:
#
#   - For an UPDATE with multiple fields changed (status + rating), do you
#     emit one line ("Finished 'Dune' and rated it 5/5") or treat them as
#     separate beats? One line per event keeps the feed clean.
#
#   - Status transitions are the most interesting beat. Want-to-read → reading
#     is "started reading"; reading → finished is "finished". A demotion
#     (finished → reading) is rare but possible — how to phrase it?
#
#   - Rating changes (None → 5, or 3 → 5) — is "rated it 5/5" enough, or do
#     you want "changed rating from 3 to 5"?
#
#   - The renderer DOES NOT need to escape HTML — render_event_html() wraps
#     this output and handles escaping. Keep this function string-in, string-out.
#
# Constraint: keep this function pure. No I/O, no DB queries, no `events.`
# imports. The event envelope is self-describing by design.

def render_event_line(event: dict[str, Any]) -> str:
    """Render a single book event as a human-readable line.

    TODO (La Boeuf): implement. ~10-20 lines. See design notes above.

    Examples of acceptable behavior:
        created  → "Added 'Dune' by Herbert"
        status   → "Started reading 'Dune'"
        rating   → "Rated 'Dune' 5/5"
        finished → "Finished 'Dune' and rated it 5/5"
        deleted  → "Removed 'Dune' from your list"
    """
    raise NotImplementedError("Implement the per-event renderer — see TODO above.")


# ---------------------------------------------------------------------------
# HTML wrapping (keep this; not a contribution point)
# ---------------------------------------------------------------------------

def _format_timestamp(iso_ts: str) -> str:
    """Render the brooklet _ts field as a short, readable label."""
    # ISO 8601 like "2026-04-24T21:53:38.615435+00:00" — trim sub-seconds and TZ
    # for a cleaner look. Browser timezone conversion is a future polish.
    if "T" not in iso_ts:
        return iso_ts
    date_part, time_part = iso_ts.split("T", 1)
    time_part = time_part.split(".")[0].split("+")[0]
    return f"{date_part} {time_part}"


def _render_event_html(event: dict[str, Any]) -> str:
    """Wrap a single event line in a styled list item."""
    line = html.escape(render_event_line(event))
    ts = html.escape(_format_timestamp(event.get("_ts", "")))
    seq = event.get("_seq", "?")
    return (
        '<li class="border-b border-slate-800 py-3 flex justify-between items-baseline gap-4">'
        f'  <span class="text-slate-200">{line}</span>'
        f'  <span class="text-xs text-slate-500 font-mono whitespace-nowrap" title="seq={seq}">{ts}</span>'
        '</li>'
    )


def render_activity_feed(limit: int = DEFAULT_LIMIT) -> str:
    """Render the activity feed as an HTML fragment for the #content swap target."""
    items = list(reversed(events.read_recent(events.BOOKS_TOPIC, limit=limit)))
    if not items:
        body = (
            '<p class="text-slate-400 text-center py-8">'
            'No activity yet. Add a book to get started.'
            '</p>'
        )
    else:
        list_items = "\n".join(_render_event_html(ev) for ev in items)
        body = f'<ul class="divide-y divide-slate-800">{list_items}</ul>'

    return (
        '<div class="bg-slate-900 rounded-xl border border-slate-700 p-6 shadow-xl"'
        '     hx-get="/activity" hx-trigger="every 10s" hx-swap="outerHTML">'
        '  <div class="flex justify-between items-center mb-4">'
        '    <h2 class="text-xl font-bold font-[\'Space_Grotesk\'] text-white">Activity</h2>'
        '    <span class="text-xs text-slate-500">auto-refreshes every 10s</span>'
        '  </div>'
        f'  {body}'
        '</div>'
    )
