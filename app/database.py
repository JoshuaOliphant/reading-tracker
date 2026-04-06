# ABOUTME: SQLite database layer for persistent book storage.
# ABOUTME: Provides async CRUD operations and handles schema initialization.

"""
Database layer using SQLite for persistent storage.

This replaces the JSON file approach for better reliability
and proper ACID compliance.
"""

import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Any

from app.git_audit import get_audit_log

DATABASE_PATH = Path("data/reading_list.db")


async def init_db():
    """Initialize the database schema."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '',
                status TEXT DEFAULT 'want-to-read',
                rating INTEGER,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)
        await db.commit()


async def get_all_books() -> list[dict]:
    """Get all books from the database."""
    await init_db()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM books ORDER BY id") as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_book(book_id: int) -> dict | None:
    """Get a single book by ID."""
    await init_db()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM books WHERE id = ?", (book_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def create_book(
    title: str,
    author: str = "",
    status: str = "want-to-read",
    rating: int | None = None,
    notes: str = ""
) -> dict:
    """Create a new book and return it."""
    await init_db()

    # Validate status
    if status not in ("want-to-read", "reading", "finished"):
        status = "want-to-read"

    # Validate rating
    if rating is not None:
        rating = max(1, min(5, int(rating)))

    created_at = datetime.now().isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO books (title, author, status, rating, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, author, status, rating, notes, created_at)
        )
        await db.commit()
        book_id = cursor.lastrowid

    book = {
        "id": book_id,
        "title": title,
        "author": author,
        "status": status,
        "rating": rating,
        "notes": notes,
        "created_at": created_at,
        "updated_at": None
    }

    await get_audit_log().record_create(book)
    return book


async def update_book(book_id: int, **updates) -> dict | None:
    """Update a book and return the updated record."""
    await init_db()

    # Get existing book
    book = await get_book(book_id)
    if not book:
        return None

    # Apply updates
    if "title" in updates and updates["title"]:
        book["title"] = updates["title"]
    if "author" in updates and updates["author"]:
        book["author"] = updates["author"]
    if "status" in updates and updates["status"]:
        if updates["status"] in ("want-to-read", "reading", "finished"):
            book["status"] = updates["status"]
    if "rating" in updates and updates["rating"] is not None:
        book["rating"] = max(1, min(5, int(updates["rating"])))
    if "notes" in updates:
        book["notes"] = updates["notes"] if updates["notes"] else ""

    book["updated_at"] = datetime.now().isoformat()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            UPDATE books
            SET title = ?, author = ?, status = ?, rating = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (book["title"], book["author"], book["status"], book["rating"],
             book["notes"], book["updated_at"], book_id)
        )
        await db.commit()

    await get_audit_log().record_update(book, updates)
    return book


async def delete_book(book_id: int) -> dict | None:
    """Delete a book and return the deleted record."""
    await init_db()

    # Get existing book first
    book = await get_book(book_id)
    if not book:
        return None

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM books WHERE id = ?", (book_id,))
        await db.commit()

    await get_audit_log().record_delete(book)
    return book


async def search_books(query: str) -> list[dict]:
    """Search books by title or author."""
    await init_db()

    search_term = f"%{query}%"

    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM books
            WHERE title LIKE ? OR author LIKE ?
            ORDER BY id
            """,
            (search_term, search_term)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_stats() -> dict:
    """Get reading statistics."""
    await init_db()

    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Total count
        async with db.execute("SELECT COUNT(*) FROM books") as cursor:
            total = (await cursor.fetchone())[0]

        # Count by status
        by_status = {"want-to-read": 0, "reading": 0, "finished": 0}
        async with db.execute(
            "SELECT status, COUNT(*) FROM books GROUP BY status"
        ) as cursor:
            async for row in cursor:
                if row[0] in by_status:
                    by_status[row[0]] = row[1]

        # Average rating
        async with db.execute(
            "SELECT AVG(rating), COUNT(*) FROM books WHERE rating IS NOT NULL"
        ) as cursor:
            row = await cursor.fetchone()
            avg_rating = round(row[0], 1) if row[0] else None
            rated_count = row[1]

    return {
        "total": total,
        "by_status": by_status,
        "average_rating": avg_rating,
        "rated_count": rated_count
    }


async def migrate_from_json():
    """Migrate existing JSON data to SQLite (one-time operation)."""
    import json

    json_path = Path("data/books.json")
    if not json_path.exists():
        return

    # Check if we already have data in SQLite
    books = await get_all_books()
    if books:
        return  # Already migrated

    try:
        data = json.loads(json_path.read_text())
        for book in data.get("books", []):
            await create_book(
                title=book.get("title", ""),
                author=book.get("author", ""),
                status=book.get("status", "want-to-read"),
                rating=book.get("rating"),
                notes=book.get("notes", "")
            )
        print(f"Migrated {len(data.get('books', []))} books from JSON to SQLite")
    except Exception as e:
        print(f"Migration error: {e}")
