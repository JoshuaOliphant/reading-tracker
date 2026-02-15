# ABOUTME: Redesigned saved views with proper static vs data-driven separation.
# ABOUTME: Static views cache HTML directly; data-driven views use templates with fresh data.

"""
Saved Views - Redesigned Progressive UI Caching

Architecture:
1. STATIC views (forms, welcome): Cache full HTML, serve directly
2. DATA-DRIVEN views (book lists): Cache HTML template with placeholders,
   fetch fresh data at serve time, render with actual data

This fixes the caching bug where stale book data was served because
the old design cached full HTML but couldn't actually inject fresh data.

Template placeholders:
- {{BOOK_LIST}} - Renders the book list items
- {{BOOK_COUNT}} - Number of books
- {{STATS}} - Reading statistics
"""

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from enum import Enum


DATA_FILE = Path("data/saved_views.json")


class ViewType(str, Enum):
    STATIC = "static"           # Cache full HTML (forms, welcome, etc.)
    DATA_DRIVEN = "data-driven"  # Template + fresh data at serve time


@dataclass
class SavedView:
    """A user-saved view with proper caching semantics."""
    id: str
    name: str
    trigger_phrases: list[str]
    keywords: list[str]
    view_type: str  # "static" or "data-driven"
    html_template: str
    tools_needed: list[str] = field(default_factory=list)  # Tools to call for fresh data
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    use_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SavedView":
        # Handle legacy views without view_type
        if "view_type" not in data:
            data["view_type"] = "static"
        if "tools_needed" not in data:
            data["tools_needed"] = []
        # Remove legacy field
        data.pop("has_dynamic_data", None)
        return cls(**data)

    @property
    def is_static(self) -> bool:
        return self.view_type == ViewType.STATIC.value

    @property
    def is_data_driven(self) -> bool:
        return self.view_type == ViewType.DATA_DRIVEN.value


class SavedViewsManager:
    """Manages saved views with proper static/data-driven handling."""

    def __init__(self):
        self._views: dict[str, SavedView] = {}
        self._load()

    def _load(self):
        """Load saved views from disk."""
        if not DATA_FILE.exists():
            return
        try:
            data = json.loads(DATA_FILE.read_text())
            self._views = {}
            for v in data.get("views", []):
                try:
                    view = SavedView.from_dict(v)
                    self._views[view.id] = view
                except Exception as e:
                    print(f"Skipping invalid view: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error loading views: {e}")
            self._views = {}

    def _save(self):
        """Save views to disk."""
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {"views": [v.to_dict() for v in self._views.values()]}
        DATA_FILE.write_text(json.dumps(data, indent=2))

    def add_static_view(
        self,
        name: str,
        trigger_phrases: list[str],
        keywords: list[str],
        html: str,
    ) -> SavedView:
        """Add a static view (forms, welcome screens, etc.)."""
        view_id = f"static_{len(self._views) + 1}_{int(datetime.now().timestamp())}"

        view = SavedView(
            id=view_id,
            name=name,
            trigger_phrases=[p.lower().strip() for p in trigger_phrases],
            keywords=[k.lower().strip() for k in keywords],
            view_type=ViewType.STATIC.value,
            html_template=html,
            tools_needed=[],
        )

        self._views[view_id] = view
        self._save()
        return view

    def add_data_driven_view(
        self,
        name: str,
        trigger_phrases: list[str],
        keywords: list[str],
        html_template: str,
        tools_needed: list[str],
    ) -> SavedView:
        """
        Add a data-driven view with template and required tools.

        The html_template should contain placeholders like {{BOOK_LIST}}
        that will be replaced with fresh data at serve time.
        """
        view_id = f"dynamic_{len(self._views) + 1}_{int(datetime.now().timestamp())}"

        view = SavedView(
            id=view_id,
            name=name,
            trigger_phrases=[p.lower().strip() for p in trigger_phrases],
            keywords=[k.lower().strip() for k in keywords],
            view_type=ViewType.DATA_DRIVEN.value,
            html_template=html_template,
            tools_needed=tools_needed,
        )

        self._views[view_id] = view
        self._save()
        return view

    def get_view(self, view_id: str) -> SavedView | None:
        return self._views.get(view_id)

    def delete_view(self, view_id: str) -> bool:
        if view_id in self._views:
            del self._views[view_id]
            self._save()
            return True
        return False

    def list_views(self) -> list[SavedView]:
        """List all saved views, sorted by use count."""
        return sorted(
            self._views.values(),
            key=lambda v: v.use_count,
            reverse=True
        )

    def find_matching_view(self, user_message: str) -> SavedView | None:
        """Find a saved view matching the user's message."""
        message_lower = user_message.lower().strip()

        # Exact phrase match (highest priority)
        for view in self._views.values():
            for phrase in view.trigger_phrases:
                if phrase == message_lower:
                    view.use_count += 1
                    self._save()
                    return view

        # Keyword match (all keywords must be present)
        for view in self._views.values():
            if view.keywords:
                if all(kw in message_lower for kw in view.keywords):
                    view.use_count += 1
                    self._save()
                    return view

        return None

    def record_use(self, view_id: str):
        if view_id in self._views:
            self._views[view_id].use_count += 1
            self._save()


# Singleton
_manager: SavedViewsManager | None = None


def get_views_manager() -> SavedViewsManager:
    global _manager
    if _manager is None:
        _manager = SavedViewsManager()
    return _manager


# ============================================================================
# TEMPLATE RENDERING
# ============================================================================

async def render_book_list_html(books: list[dict]) -> str:
    """Render a list of books as HTML items."""
    if not books:
        return '''
<div class="text-center py-12 animate-in">
    <div class="w-16 h-16 rounded-2xl bg-slate-800 flex items-center justify-center mx-auto mb-4">
        <span class="text-2xl">📚</span>
    </div>
    <h3 class="text-lg font-semibold text-white mb-2">No books yet</h3>
    <p class="text-slate-400 mb-6">Start building your reading list!</p>
    <button hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator"
            hx-vals='{"message":"add a book"}'
            class="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg
                   shadow-lg shadow-indigo-500/25 transition-all">
        Add Your First Book
    </button>
</div>
'''

    items = []
    for book in books:
        book_id = book.get("id", "")
        title = book.get("title", "Unknown")
        author = book.get("author", "Unknown")
        status = book.get("status", "want-to-read")
        rating = book.get("rating")

        # Status badge
        status_classes = {
            "want-to-read": "bg-blue-500/20 text-blue-400 border-blue-500/30",
            "reading": "bg-amber-500/20 text-amber-400 border-amber-500/30",
            "finished": "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
        }
        status_labels = {
            "want-to-read": "Want to Read",
            "reading": "Reading",
            "finished": "Finished",
        }
        badge_class = status_classes.get(status, status_classes["want-to-read"])
        badge_label = status_labels.get(status, "Want to Read")

        # Rating stars
        if rating:
            filled = "★" * rating
            empty = "★" * (5 - rating)
            rating_html = f'<span class="text-amber-400">{filled}</span><span class="text-slate-600">{empty}</span>'
        else:
            rating_html = '<span class="text-slate-500 text-sm">Not rated</span>'

        items.append(f'''
<div class="group flex items-center justify-between p-4 bg-slate-900 rounded-lg border border-slate-800
            hover:border-slate-700 hover:bg-slate-800/50 transition-all duration-200 cursor-pointer"
     hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator"
     hx-vals='{{"message":"show book {book_id}"}}'>
    <div class="flex items-center gap-4">
        <div class="w-12 h-16 rounded bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center">
            <span class="text-white text-xl">📖</span>
        </div>
        <div>
            <p class="font-medium text-white group-hover:text-indigo-300 transition-colors">{title}</p>
            <p class="text-sm text-slate-400">by {author}</p>
            <div class="flex items-center gap-3 mt-1">
                <span class="px-2.5 py-1 text-xs font-medium rounded-full {badge_class} border">{badge_label}</span>
                <div class="flex items-center gap-0.5 text-sm">{rating_html}</div>
            </div>
        </div>
    </div>
    <div class="text-slate-400 group-hover:text-white transition-colors">→</div>
</div>
''')

    return '<div class="space-y-3">' + '\n'.join(items) + '</div>'


async def render_data_driven_view(view: SavedView, data: dict[str, Any]) -> str:
    """
    Render a data-driven view by replacing placeholders with fresh data.

    Placeholders:
    - {{BOOK_LIST}} - Rendered book list items
    - {{BOOK_COUNT}} - Number of books
    """
    html = view.html_template

    # Replace {{BOOK_COUNT}}
    if "{{BOOK_COUNT}}" in html:
        books = data.get("books", [])
        html = html.replace("{{BOOK_COUNT}}", str(len(books)))

    # Replace {{BOOK_LIST}}
    if "{{BOOK_LIST}}" in html:
        books = data.get("books", [])
        book_list_html = await render_book_list_html(books)
        html = html.replace("{{BOOK_LIST}}", book_list_html)

    return html


def inject_dynamic_data(html: str, data: dict[str, Any]) -> str:
    """Legacy function for backward compatibility."""
    # Simple placeholder replacement
    for key, value in data.items():
        placeholder = "{{" + key + "}}"
        if isinstance(value, list):
            html = html.replace(placeholder, str(len(value)))
        else:
            html = html.replace(placeholder, str(value))
    return html
