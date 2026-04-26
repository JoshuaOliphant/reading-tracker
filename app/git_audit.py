# ABOUTME: Git-backed audit log that mirrors SQLite mutations for history.
# ABOUTME: Snapshots the reading list as JSON after each change, with descriptive commits.

"""
Git Audit Log - Hybrid storage layer.

SQLite handles queries and ACID. This module mirrors every mutation
to a local git repo, giving us:
- Full history of every change (git log)
- Diffs between any two points (git diff)
- Temporal context for agents (recent activity summary)
- Undo capability (git revert)

This is the reading-tracker equivalent of a coding agent's workspace
context (Raschka Component 1: Live Repo Context).
"""

import json
from pathlib import Path
from datetime import datetime

try:
    import pygit2

    PYGIT2_AVAILABLE = True
except ImportError:
    PYGIT2_AVAILABLE = False

REPO_PATH = Path("data/history")


class GitAuditLog:
    """Mirror SQLite mutations to a git repo for history tracking."""

    def __init__(self, repo_path: Path = REPO_PATH):
        self.repo_path = repo_path
        self._repo: "pygit2.Repository | None" = None

    @property
    def available(self) -> bool:
        return PYGIT2_AVAILABLE

    def _ensure_repo(self) -> "pygit2.Repository":
        """Initialize or open the git repo."""
        if self._repo is not None:
            return self._repo

        if not PYGIT2_AVAILABLE:
            raise RuntimeError("pygit2 is not installed")

        self.repo_path.mkdir(parents=True, exist_ok=True)

        if (self.repo_path / ".git").exists():
            self._repo = pygit2.Repository(str(self.repo_path))
        else:
            self._repo = pygit2.init_repository(str(self.repo_path))
        return self._repo

    async def record_create(self, book: dict) -> None:
        """Record a book creation."""
        title = book.get("title", "Unknown")
        author = book.get("author", "")
        status = book.get("status", "want-to-read")

        msg = f"Add '{title}'"
        if author:
            msg += f" by {author}"
        msg += f" [{status}]"

        await self._snapshot_and_commit(msg)

    async def record_update(self, book: dict, updates: dict) -> None:
        """Record a book update with a descriptive commit message."""
        title = book.get("title", "Unknown")
        parts = []

        if "status" in updates:
            new_status = updates["status"]
            if new_status == "finished":
                parts.append(f"Finish '{title}'")
            elif new_status == "reading":
                parts.append(f"Start reading '{title}'")
            else:
                parts.append(f"Move '{title}' to {new_status}")

        if "rating" in updates and updates["rating"] is not None:
            parts.append(f"Rate '{title}' {updates['rating']}/5")

        if "notes" in updates:
            parts.append(f"Add notes to '{title}'")

        if "title" in updates:
            parts.append(f"Rename to '{updates['title']}'")

        if "author" in updates:
            parts.append(f"Update author to '{updates['author']}'")

        msg = " + ".join(parts) if parts else f"Update '{title}'"
        await self._snapshot_and_commit(msg)

    async def record_delete(self, book: dict) -> None:
        """Record a book deletion."""
        title = book.get("title", "Unknown")
        await self._snapshot_and_commit(f"Remove '{title}'")

    async def _snapshot_and_commit(self, message: str) -> None:
        """Snapshot current DB state to JSON and commit."""
        if not PYGIT2_AVAILABLE:
            return

        try:
            repo = self._ensure_repo()

            # Import here to avoid circular imports at module level
            from app import database as db

            books = await db.get_all_books()
            stats = await db.get_stats()

            # Write the snapshot
            snapshot = {
                "snapshot_at": datetime.now().isoformat(),
                "stats": stats,
                "books": books,
            }

            snapshot_path = self.repo_path / "reading-list.json"
            snapshot_path.write_text(
                json.dumps(snapshot, indent=2, default=str)
            )

            # Stage and commit
            self._commit(repo, message)

        except Exception as e:
            # Audit log should never break the main app
            print(f"Git audit log error: {e}")

    def _commit(self, repo: "pygit2.Repository", message: str) -> None:
        """Stage all changes and create a commit."""
        index = repo.index
        index.add_all()
        index.write()
        tree = index.write_tree()

        sig = pygit2.Signature(
            "Reading Tracker", "tracker@local",
        )

        if repo.head_is_unborn:
            parents = []
        else:
            parents = [repo.head.target]

        repo.create_commit("HEAD", sig, sig, message, tree, parents)

    def get_history(self, limit: int = 20) -> list[dict]:
        """Get recent changes as structured events.

        Returns a list of {timestamp, message, sha} dicts.
        """
        if not PYGIT2_AVAILABLE:
            return []

        try:
            repo = self._ensure_repo()
            if repo.head_is_unborn:
                return []

            events = []
            for commit in repo.walk(
                repo.head.target, pygit2.GIT_SORT_TIME
            ):
                if len(events) >= limit:
                    break
                events.append({
                    "timestamp": datetime.fromtimestamp(
                        commit.commit_time
                    ).isoformat(),
                    "message": commit.message.strip(),
                    "sha": str(commit.id)[:8],
                })
            return events

        except Exception as e:
            print(f"Git history error: {e}")
            return []

    def get_diff(self, sha_old: str, sha_new: str = "HEAD") -> str | None:
        """Get the diff between two commits as text."""
        if not PYGIT2_AVAILABLE:
            return None

        try:
            repo = self._ensure_repo()
            old = repo.revparse_single(sha_old)
            new = repo.revparse_single(sha_new)

            if hasattr(old, "tree"):
                old_tree = old.tree
            else:
                old_tree = old.peel(pygit2.Tree)

            if hasattr(new, "tree"):
                new_tree = new.tree
            else:
                new_tree = new.peel(pygit2.Tree)

            diff = repo.diff(old_tree, new_tree)
            return diff.patch

        except Exception as e:
            print(f"Git diff error: {e}")
            return None

    def build_context_summary(self, limit: int = 10) -> str:
        """Build a temporal context summary for agent system prompts.

        This is Raschka Component 1: Live Repo Context, powered by
        git history instead of static DB queries.
        """
        history = self.get_history(limit=limit)
        if not history:
            return ""

        lines = ["## Recent Reading Activity"]
        for event in history[:limit]:
            date = event["timestamp"][:10]
            lines.append(f"- {date}: {event['message']}")

        return "\n".join(lines)


# Module-level singleton
_audit_log: GitAuditLog | None = None


def get_audit_log() -> GitAuditLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = GitAuditLog()
    return _audit_log
