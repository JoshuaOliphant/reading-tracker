# ABOUTME: MCP tool definitions for book reading list management.
# ABOUTME: Each tool handles one data operation using SQLite, returns structured JSON.

"""
Tool definitions for the reading list application.

Each tool:
1. Does ONE thing
2. Uses SQLite for persistent storage
3. Returns structured JSON data
4. Handles errors gracefully
"""

from claude_agent_sdk import tool, create_sdk_mcp_server
from typing import Any
import json

from app import database as db


def _success(data: Any) -> dict:
    """Format successful tool response."""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps(data, default=str)
        }]
    }


def _error(message: str) -> dict:
    """Format error tool response."""
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"error": message})
        }],
        "is_error": True
    }


# === Tool Definitions ===

@tool(
    "list_books",
    "Get all books in the reading list. Returns array with id, title, author, status (want-to-read, reading, finished), rating (1-5), notes.",
    {}
)
async def list_books(args: dict[str, Any]) -> dict[str, Any]:
    """List all books."""
    books = await db.get_all_books()
    return _success({"books": books, "count": len(books)})


@tool(
    "get_book",
    "Get a specific book by ID. Returns full book details.",
    {"id": str}
)
async def get_book(args: dict[str, Any]) -> dict[str, Any]:
    """Get a single book."""
    try:
        book_id = int(args["id"])
    except (ValueError, TypeError):
        return _error(f"Invalid book ID: {args.get('id')}")

    book = await db.get_book(book_id)
    if book:
        return _success({"book": book})
    return _error(f"Book not found: {args['id']}")


@tool(
    "create_book",
    "Add a new book to the reading list. Requires: title. Optional: author, status (want-to-read, reading, finished - defaults to want-to-read), rating (1-5), notes.",
    {"title": str, "author": str | None, "status": str | None, "rating": int | None, "notes": str | None}
)
async def create_book(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new book."""
    title = args.get("title", "").strip()
    if not title:
        return _error("Title is required")

    book = await db.create_book(
        title=title,
        author=args.get("author", "") or "",
        status=args.get("status", "want-to-read") or "want-to-read",
        rating=args.get("rating"),
        notes=args.get("notes", "") or ""
    )

    return _success({"book": book, "message": "Book added to reading list"})


@tool(
    "update_book",
    "Update an existing book. Requires: id. Optional: title, author, status (want-to-read, reading, finished), rating (1-5), notes.",
    {"id": str, "title": str | None, "author": str | None, "status": str | None, "rating": int | None, "notes": str | None}
)
async def update_book(args: dict[str, Any]) -> dict[str, Any]:
    """Update a book."""
    try:
        book_id = int(args["id"])
    except (ValueError, TypeError):
        return _error(f"Invalid book ID: {args.get('id')}")

    updates = {}
    if args.get("title"):
        updates["title"] = args["title"]
    if args.get("author"):
        updates["author"] = args["author"]
    if args.get("status"):
        updates["status"] = args["status"]
    if args.get("rating") is not None:
        updates["rating"] = args["rating"]
    if args.get("notes") is not None:
        updates["notes"] = args["notes"]

    book = await db.update_book(book_id, **updates)
    if book:
        return _success({"book": book, "message": "Book updated"})
    return _error(f"Book not found: {args['id']}")


@tool(
    "delete_book",
    "Remove a book from the reading list by ID. This is permanent.",
    {"id": str}
)
async def delete_book(args: dict[str, Any]) -> dict[str, Any]:
    """Delete a book."""
    try:
        book_id = int(args["id"])
    except (ValueError, TypeError):
        return _error(f"Invalid book ID: {args.get('id')}")

    deleted = await db.delete_book(book_id)
    if deleted:
        return _success({"deleted": deleted, "message": "Book removed from reading list"})
    return _error(f"Book not found: {args['id']}")


@tool(
    "search_books",
    "Search books by keyword in title or author.",
    {"query": str}
)
async def search_books(args: dict[str, Any]) -> dict[str, Any]:
    """Search books by title or author."""
    query = args.get("query", "").strip()
    if not query:
        return _error("Search query is required")

    matches = await db.search_books(query)
    return _success({"books": matches, "count": len(matches), "query": query})


@tool(
    "get_stats",
    "Get reading statistics. Returns total books, count by status, average rating of rated books.",
    {}
)
async def get_stats(args: dict[str, Any]) -> dict[str, Any]:
    """Get reading statistics."""
    stats = await db.get_stats()
    return _success({"stats": stats})


# === MCP Server Creation ===

def create_tools_server():
    """Create the MCP server with all tools."""
    return create_sdk_mcp_server(
        name="app_tools",
        version="1.0.0",
        tools=[
            list_books,
            get_book,
            create_book,
            update_book,
            delete_book,
            search_books,
            get_stats,
        ]
    )


# Keep _load_data for backward compatibility with main.py saved views
def _load_data() -> dict:
    """Load data - kept for backward compatibility."""
    import asyncio

    async def _get():
        books = await db.get_all_books()
        return {"books": books}

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're in an async context, need to run in executor
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, _get())
                return future.result()
        else:
            return loop.run_until_complete(_get())
    except RuntimeError:
        return asyncio.run(_get())
