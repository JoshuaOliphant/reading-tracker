# Git as a Per-User State Store

## The Idea

Treat each user's reading list as a mini git repository. Every mutation
(add book, change rating, mark as finished) becomes a commit. The full
reading history is the git log. "What if" scenarios are branches.

This extends the "reading list as repo context" analogy from Raschka's
Component 1 (Live Repo Context) into the storage layer itself.

## What Already Exists

### Production-Ready (Different Domain, Same Pattern)

| Tool | What It Does | Relevance |
|---|---|---|
| [**Dolt**](https://github.com/dolthub/dolt) | Git for SQL databases. Clone, branch, merge, diff on tables. MySQL-compatible wire protocol. Embeddable via Go driver (like SQLite). | Closest to the idea but overkill -- it's a full database engine. No Python embedding. |
| [**Git-based CMSs**](https://contentrain.io/) (Tina, Sveltia, Contentrain) | Store content as JSON/Markdown files in git, commit on every edit. | Proven pattern. Each "content item" is like a book entry. |
| [**GitRows**](https://gitrows.com/) | REST API for CRUD on JSON/CSV files stored in GitHub/GitLab repos. | Demonstrates the REST-to-git mapping, but depends on GitHub API. |
| [**GitOps tools**](https://www.gitops.tech/) (Argo CD, Flux) | Declarative infrastructure state in git, operators reconcile. | Proves git-as-desired-state works at enterprise scale. |

### Libraries (Build Your Own)

| Library | Language | Approach | Maturity |
|---|---|---|---|
| [**pygit2**](https://www.pygit2.org/) | Python (C bindings to libgit2) | Low-level git operations without shelling out to `git` CLI. Fast. | Mature, actively maintained |
| [**GitPython**](https://gitpython.readthedocs.io/en/stable/) | Python (wraps `git` CLI) | Higher-level API. Ships with [gitdb](https://github.com/gitpython-developers/gitdb) for direct object access. | Mature but less actively maintained |
| [**isomorphic-git**](https://isomorphic-git.org/) | JavaScript | Pure JS git implementation. Works in browsers. | Active, well-tested |
| [**gitfs**](https://github.com/presslabs/gitfs) | Python (FUSE) | Mount a git repo as a filesystem, auto-commits changes. | Experimental |

### Theoretical Foundations

- **Event Sourcing**: [Git IS event sourcing](https://dev.to/devcorner/git-as-an-event-sourced-system-understanding-event-sourcing-through-git-271p).
  Each commit is an immutable event. The current state is the projection.
  The full log is the event stream.
- **Content-Addressable Storage**: Git's object model (blobs, trees,
  commits) is a Merkle DAG. Every object is addressed by its SHA hash.
  This gives deduplication and integrity for free.

## How Git Stores Data (Not JSONL)

Git doesn't use JSONL, CSV, or any text log format. It has its own
**content-addressable object database** with four object types, all
stored as zlib-compressed blobs addressed by SHA-1 hash.

### The Four Object Types

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  COMMIT  │────▶│   TREE   │────▶│   BLOB   │     │   TAG    │
│          │     │(directory)│     │ (file)   │     │(bookmark)│
│ metadata │     │          │     │          │     │          │
│ message  │     │ name→sha │     │ content  │     │ name→sha │
│ parent   │     │ name→sha │     │          │     │ message  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
```

**Blob** -- A file's raw content. No filename, no metadata. Just bytes.
```
blob 5374\0# reading-list\n\n**A test application...
```

**Tree** -- A directory listing. Maps filenames to blob/tree SHAs.
```
100644 blob d0e58d0a...  tools.py
100644 blob bdfb1388...  database.py
040000 tree 0bd909d0...  agents/
```

**Commit** -- A snapshot pointer + metadata. Points to a tree (the root
directory at that moment), plus parent commit(s), author, timestamp, message.
```
tree 2b54848e...
parent 82a03ba8...
author Claude <noreply@anthropic.com> 1775441425 +0000
committer Claude <noreply@anthropic.com> 1775441425 +0000

docs: explore git as per-user state store for reading lists
```

**Tag** -- A named, annotated pointer to a commit.

### On Disk

Every object is stored as:
```
{type} {size}\0{content}  →  zlib compress  →  .git/objects/{sha[0:2]}/{sha[2:]}
```

So `.git/objects/00/f85e37f6...` is a zlib-compressed blob. Git also
**packs** objects into `.git/objects/pack/*.pack` files for efficiency
(delta-compressed, indexed).

### Why This Matters vs. JSONL

| Concern | JSONL Event Log | Git Object Store |
|---|---|---|
| **Deduplication** | None. Same book content repeated in every event. | Automatic. If a blob's content hasn't changed, git reuses the same SHA. A commit touching 1 of 14 books stores only 1 new blob. |
| **Integrity** | Must add your own checksums. | Every object is SHA-addressed. Corruption is detectable. |
| **Diffing** | Must implement yourself. | `git diff` compares any two commits structurally. |
| **Branching** | Must copy the whole log. | Branches are just pointers (41-byte files). Nearly free. |
| **Compression** | Must add your own. | zlib on every object + delta compression in packs. |
| **Querying** | Fast -- just scan lines. | Slow for arbitrary queries. Need to walk tree objects. |
| **Append speed** | Very fast -- just append a line. | Slower -- write blob, update tree, create commit. |
| **Human readable** | Yes, plain text. | No, binary (but `git log`/`git cat-file` decode it). |

**Bottom line**: JSONL is better if you need a simple, fast append log.
Git is better if you need deduplication, branching, diffing, and
structural integrity -- which are exactly the features that make it
interesting as a "reading list repo."

### What a Book Mutation Looks Like Internally

When a user rates "Dune" 5/5, here's what git creates:

```
1. NEW BLOB: books/004-dune.json (updated content with rating: 5)
   sha: a1b2c3d4...

2. NEW TREE: books/ (same as before but 004-dune.json points to new blob)
   sha: e5f6a7b8...

3. NEW TREE: root (same as before but books/ points to new tree)
   sha: c9d0e1f2...

4. NEW COMMIT: points to new root tree + parent commit
   sha: 1a2b3c4d...
   message: "Rate 'Dune' 5/5"

Objects REUSED (not duplicated):
   - All other book blobs (001-neuromancer.json, etc.)
   - preferences.json blob
   - All unchanged tree entries
```

Only ~4 new objects for a single-field change. Everything else is shared
by reference.

---

## How It Would Work for Reading Tracker

### Data Layout (Per User)

```
data/users/{user_id}/
├── reading-list.json       # Current state: all books
├── preferences.json        # User preferences (genres, page limits)
└── .git/                   # Git repo tracking changes
```

Or, for finer-grained tracking:

```
data/users/{user_id}/
├── books/
│   ├── 001-dune.json           # One file per book
│   ├── 002-neuromancer.json
│   └── 003-project-hail-mary.json
├── preferences.json
└── .git/
```

### Every Mutation = A Commit

```python
# User adds a book
await user_repo.add_book({"title": "Dune", "author": "Frank Herbert", "status": "want-to-read"})
# Under the hood:
#   1. Write books/004-dune.json
#   2. git add books/004-dune.json
#   3. git commit -m "Add 'Dune' by Frank Herbert [status: want-to-read]"

# User rates a book
await user_repo.update_book(4, {"rating": 5})
# Commit: "Rate 'Dune' 5/5"

# User marks as finished
await user_repo.update_book(4, {"status": "finished"})
# Commit: "Finish 'Dune'"
```

### What You Get for Free

| Feature | How Git Provides It |
|---|---|
| **Full audit trail** | `git log` -- every change, when, what |
| **Undo/revert** | `git revert <commit>` -- undo any specific change |
| **Diff any two points** | `git diff abc123..def456` -- what changed between two states |
| **Time travel** | `git checkout <commit>` -- see the list as it was on any date |
| **"What if" branches** | `git branch what-if && git checkout what-if` -- try adding books without committing to it |
| **Deduplication** | Git's content-addressable storage deduplicates identical content |
| **Integrity** | SHA hashes verify nothing was corrupted or tampered with |
| **Backup** | `git push` to any remote -- instant off-site backup |
| **Merge user lists** | Two users combining their lists = `git merge` |

### What It Gives the Agent (Harness Context)

This is where it connects back to harness engineering. The git log
becomes rich context for the agents:

```
## Reading List Context (from git history)

Current state: 14 books (5 want-to-read, 3 reading, 6 finished)

Recent activity (last 7 days):
- 2 days ago: Added "The Name of the Wind" (want-to-read)
- 3 days ago: Rated "Neuromancer" 5/5
- 5 days ago: Started reading "Dune" (want-to-read -> reading)
- 6 days ago: Finished "Hyperion" and rated it 5/5

Patterns from history:
- Averages 2 books/week added
- Finishes ~60% of books started
- Tends to rate sci-fi higher (avg 4.5) than literary fiction (avg 3.2)
- Has been on a sci-fi streak for 3 weeks
```

The git log provides the "recent commits" that a coding agent uses
to understand what work is in progress. For us, it's "what reading
activity is in progress."

## Implementation Difficulty

### Option A: Minimal (pygit2 wrapper) -- ~200 lines of Python

Replace `database.py` with a git-backed store. This is the most
educational approach.

```python
# app/git_store.py -- sketch
import pygit2
import json
from pathlib import Path
from datetime import datetime


class GitUserStore:
    """Per-user reading list backed by a local git repo."""

    def __init__(self, user_id: str, base_path: Path = Path("data/users")):
        self.repo_path = base_path / user_id
        self.repo = self._init_repo()

    def _init_repo(self) -> pygit2.Repository:
        if (self.repo_path / ".git").exists():
            return pygit2.Repository(str(self.repo_path))
        self.repo_path.mkdir(parents=True, exist_ok=True)
        return pygit2.init_repository(str(self.repo_path))

    async def add_book(self, book: dict) -> dict:
        book_id = self._next_id()
        book["id"] = book_id
        book["created_at"] = datetime.now().isoformat()

        # Write file
        book_path = self.repo_path / "books" / f"{book_id}.json"
        book_path.parent.mkdir(exist_ok=True)
        book_path.write_text(json.dumps(book, indent=2))

        # Commit
        self._commit(
            f"Add '{book['title']}' by {book.get('author', 'unknown')}"
        )
        return book

    async def update_book(self, book_id: int, updates: dict) -> dict | None:
        book_path = self.repo_path / "books" / f"{book_id}.json"
        if not book_path.exists():
            return None

        book = json.loads(book_path.read_text())
        old_status = book.get("status")
        book.update(updates)
        book["updated_at"] = datetime.now().isoformat()
        book_path.write_text(json.dumps(book, indent=2))

        # Descriptive commit message
        msg = self._describe_update(book, updates, old_status)
        self._commit(msg)
        return book

    async def get_history(self, limit: int = 20) -> list[dict]:
        """Get recent changes as structured events."""
        events = []
        for commit in self.repo.walk(
            self.repo.head.target, pygit2.GIT_SORT_TIME
        ):
            if len(events) >= limit:
                break
            events.append({
                "timestamp": datetime.fromtimestamp(commit.commit_time).isoformat(),
                "message": commit.message,
                "sha": str(commit.id)[:8],
            })
        return events

    async def get_context_summary(self) -> str:
        """Build agent context from git history.

        This is the reading-tracker equivalent of a coding agent's
        WorkspaceContext (Raschka Component 1).
        """
        books = await self.get_all_books()
        history = await self.get_history(limit=10)

        stats = self._compute_stats(books)
        recent = "\n".join(
            f"- {e['timestamp'][:10]}: {e['message']}" for e in history[:5]
        )

        return f"""## Reading List Context

Current state: {stats['total']} books ({stats['summary']})

Recent activity:
{recent}
"""

    def _commit(self, message: str):
        """Stage all changes and commit."""
        index = self.repo.index
        index.add_all()
        index.write()
        tree = index.write_tree()

        sig = pygit2.Signature("Reading Tracker", "tracker@local")
        parents = [self.repo.head.target] if not self.repo.head_is_unborn else []
        self.repo.create_commit("HEAD", sig, sig, message, tree, parents)

    def _describe_update(self, book, updates, old_status) -> str:
        title = book["title"]
        parts = []
        if "status" in updates:
            if updates["status"] == "finished":
                parts.append(f"Finish '{title}'")
            elif updates["status"] == "reading":
                parts.append(f"Start reading '{title}'")
        if "rating" in updates:
            parts.append(f"Rate '{title}' {updates['rating']}/5")
        if "notes" in updates:
            parts.append(f"Add notes to '{title}'")
        return " + ".join(parts) if parts else f"Update '{title}'"
```

**Effort**: ~2 days. Replace `database.py` with `git_store.py`, update
`tools.py` to use it, add `get_history` tool.

**Dependencies**: Add `pygit2` to `pyproject.toml`.

### Option B: Hybrid (SQLite + git log) -- ~100 lines

Keep SQLite for fast queries, but mirror every mutation to a git repo
for history. Best of both worlds.

```python
# In database.py, add a git mirror
class GitAuditLog:
    """Mirror SQLite mutations to a git repo for history."""

    def __init__(self, repo_path: Path):
        self.repo = pygit2.Repository(str(repo_path))

    async def record(self, action: str, data: dict):
        """Snapshot current state and commit."""
        # Export all books to JSON
        snapshot_path = self.repo_path / "reading-list.json"
        snapshot_path.write_text(json.dumps(data, indent=2))
        self._commit(action)
```

**Effort**: ~1 day. Add alongside existing database, no migration needed.

### Option C: Use Dolt -- ~50 lines of config

Replace SQLite with Dolt for a "real" git-for-data experience.

**Effort**: Low code, but Dolt is a Go binary (not embeddable in Python
the way SQLite is). Would require running Dolt as a separate process.
Probably overkill for this project's learning goals.

## Known Limitations

| Concern | Severity for This Project | Mitigation |
|---|---|---|
| **Performance at scale** | Low -- reading lists are small (tens to hundreds of books, not millions) | N/A |
| **High-frequency commits** | Low -- users add/update books infrequently (minutes to hours between changes) | Batch commits if needed |
| **Query performance** | Medium -- git has no indexes, can't do `WHERE rating > 4` | Option B hybrid: SQLite for queries, git for history |
| **Concurrent writes** | Low -- single user per repo, no contention | File locking if needed |
| **Disk usage** | Low -- JSON files are tiny, git packs efficiently | N/A |
| **No ACID transactions** | Medium -- git commits aren't atomic in the DB sense | Option B hybrid: SQLite provides ACID, git is eventual |
| **Merge conflicts** | Low for this use case -- one user per repo | Custom merge driver for JSON if needed |

## Connections to Harness Engineering

| Raschka Component | How Git-as-State Helps |
|---|---|
| **1. Live Repo Context** | `get_history()` provides temporal context. The agent knows not just what books exist but the *trajectory* of reading activity. |
| **2. Prompt Shape** | History summary is a natural "changing" part of the prompt that updates per-request. Git log is cheap to query. |
| **4. Context Bloat** | Git diffs are compact. Instead of dumping the full book list, show "what changed since last turn" as a diff. |
| **5. Session Memory** | Git IS persistent memory. Cross-session by nature. The full transcript of reading activity survives restarts, resets, everything. |

## Option D: Brooklet Event Streaming

[Brooklet](https://github.com/JoshuaOliphant/brooklet) is a JSONL event
streaming library ("the SQLite of event streaming") that could replace or
complement the git audit log. Instead of git commits, every mutation
becomes an appended JSONL event with automatic metadata.

### How Brooklet Works

```python
import brooklet

stream = brooklet.open("data/events")

# Register external JSONL sources (or produce to local topics)
stream.register("agent-sessions", "~/.claude/projects/**/*.jsonl", mode="glob")

# Produce events
stream.produce("reading-list", {
    "action": "create",
    "book": {"title": "Dune", "author": "Frank Herbert", "status": "want-to-read"}
}, source="app")
# Writes to data/events/reading-list/stream.jsonl:
# {"action":"create","book":{...},"_ts":"2026-04-06T12:00:00","_seq":1,"_src":"app"}

# Consume with offset tracking (picks up where it left off)
consumer = stream.consume("reading-list", group="insights-agent", follow=True)
for event in consumer:
    print(event)  # Each event is a dict with _ts, _seq, _src metadata
```

### What Brooklet Gives You

| Feature | How It Works |
|---|---|
| **Append-only JSONL** | Simple, human-readable, `grep`-able event log |
| **Automatic metadata** | `_ts` (timestamp), `_seq` (sequence number), `_src` (producer) injected on every event |
| **Consumer groups** | Multiple independent consumers with offset tracking. The insights agent and recommender agent could consume the same stream at different speeds. |
| **Follow mode** | `tail -f` behavior -- consumers block waiting for new events. Could power real-time agent reactions to book changes. |
| **Glob registration** | Register `**/*.jsonl` patterns as topics. This is how you'd consume Claude Code session transcripts (stored at `~/.claude/projects/.../*.jsonl`). |
| **Byte-level offsets** | O(1) resume. No re-scanning the entire log on restart. |

### Brooklet + Reading Tracker: What It Would Look Like

```python
# app/event_store.py
import brooklet

stream = brooklet.open("data/events")

async def emit_book_created(book: dict):
    stream.produce("books", {
        "action": "create",
        "book_id": book["id"],
        "title": book["title"],
        "author": book.get("author", ""),
        "status": book.get("status", "want-to-read"),
    })

async def emit_book_updated(book: dict, updates: dict):
    stream.produce("books", {
        "action": "update",
        "book_id": book["id"],
        "title": book["title"],
        "updates": updates,
    })

async def emit_book_deleted(book: dict):
    stream.produce("books", {
        "action": "delete",
        "book_id": book["id"],
        "title": book["title"],
    })
```

The resulting JSONL in `data/events/books/stream.jsonl`:
```jsonl
{"action":"create","book_id":1,"title":"Dune","author":"Frank Herbert","status":"want-to-read","_ts":"2026-04-06T12:00:00","_seq":1,"_src":"app"}
{"action":"update","book_id":1,"title":"Dune","updates":{"status":"reading"},"_ts":"2026-04-06T12:05:00","_seq":2,"_src":"app"}
{"action":"update","book_id":1,"title":"Dune","updates":{"rating":5},"_ts":"2026-04-06T13:00:00","_seq":3,"_src":"app"}
{"action":"update","book_id":1,"title":"Dune","updates":{"status":"finished"},"_ts":"2026-04-06T15:00:00","_seq":4,"_src":"app"}
{"action":"delete","book_id":1,"title":"Dune","_ts":"2026-04-07T10:00:00","_seq":5,"_src":"app"}
```

### The Interesting Part: Consuming Claude Code Sessions

Claude Code stores its sessions as JSONL at
`~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`. Brooklet can
register these as a topic:

```python
stream.register(
    "agent-sessions",
    "~/.claude/projects/**/*.jsonl",
    mode="glob"
)

# Now a downstream consumer can react to agent activity:
for event in stream.consume("agent-sessions", group="analytics"):
    if event.get("type") == "tool_use" and "create_book" in str(event):
        print(f"Agent created a book at {event['_ts']}")
```

This creates a unified event stream: **book mutations AND agent activity**
in the same system. The insights agent could consume both to say "you've
been asking the recommender a lot this week but not adding any books --
maybe you're having trouble finding something you like?"

### Brooklet vs. Git Audit Log

| Concern | Git Audit Log (implemented) | Brooklet |
|---|---|---|
| **Format** | Full state snapshot per commit (reading-list.json) | Individual events (one JSONL line per mutation) |
| **Storage efficiency** | Git deduplicates via content-addressing | JSONL appends are minimal (one line per event) |
| **Querying** | `git log`, `git diff` -- structural | `grep`, `jq`, or iterate with consumer -- linear scan |
| **Branching/diffing** | Yes -- git's core strength | No -- append-only log, no branching |
| **Consumer groups** | No -- single reader model | Yes -- multiple independent consumers with offsets |
| **Follow mode** | No -- must poll for new commits | Yes -- blocks waiting for new events |
| **Agent session integration** | No | Yes -- glob-register Claude Code JSONL files as topics |
| **Undo/revert** | Yes -- `git revert` | No -- append a compensating event |
| **Human readability** | `git log --oneline` is clean | `cat stream.jsonl \| jq` is clean |
| **Dependencies** | pygit2 (C library, ~5MB) | brooklet (pure Python, tiny) |

### Is This Overkill?

**For the reading tracker alone?** Slightly. The git audit log already
provides history and context. Brooklet would add consumer groups and
follow mode, which the app doesn't currently need (single user, agents
query on demand rather than streaming).

**For learning harness engineering?** No -- it's exactly right. Here's why:

1. **Event sourcing is a core harness pattern.** Raschka's Component 5
   (Structured Session Memory) is fundamentally about event logs. Brooklet
   makes the pattern explicit rather than hiding it inside the SDK's
   session JSONL.

2. **Consumer groups model multi-agent consumption.** The UI agent,
   recommender, and insights agent each consuming the same book-event
   stream at their own pace is a natural fit for the message-passing
   architecture.

3. **Unifying app events + agent events.** Brooklet can consume both
   your custom book events AND Claude Code's session JSONL. That
   combination -- "what happened to the data" + "what did the agents do" --
   is powerful observability.

4. **It's your own library.** Using it here exercises brooklet in a real
   application, which is the best way to find rough edges and missing
   features.

### Recommendation: Layered Approach

Use **all three** storage layers, each for its strength:

| Layer | Tool | Purpose |
|---|---|---|
| **Query engine** | SQLite | Fast reads, ACID writes, `WHERE` clauses |
| **State history** | Git (pygit2) | Snapshots, diffs, branches, undo |
| **Event stream** | Brooklet | Individual events, consumer groups, agent session integration |

The mutation flow:
```
User action
  → SQLite (ACID write, fast query)
  → Git audit (snapshot + commit for diffing/undo)
  → Brooklet event (append for streaming/downstream triggers)
```

Each layer is optional and fails gracefully. Start with SQLite + git
(already implemented). Add brooklet when you want to experiment with
event-driven agent patterns or cross-stream analytics.

## Recommendation

**Start with Option B (Hybrid)** for learning. It preserves the working
SQLite database while adding git-backed history. You learn the git-as-state
pattern without risking the app's query performance.

Then consider migrating to Option A once you're comfortable with pygit2
and want to explore the full pattern (branches for "what if I drop these
books?", diffs for "what changed this month?", merges for "combine two
users' reading lists").

Add **brooklet** when you want to explore event-driven patterns: consumer
groups for multi-agent consumption, follow mode for real-time reactions,
or unifying book events with Claude Code session transcripts into a
single observable stream.

## References

- [Git as a NoSQL Database](https://www.kenneth-truyers.net/2016/10/13/git-nosql-database/)
- [Turning Git into an application database](https://nede.dev/blog/turning-git-into-an-application-database/)
- [Git as an Event Sourced System](https://dev.to/devcorner/git-as-an-event-sourced-system-understanding-event-sourcing-through-git-271p)
- [Dolt: Git for Data](https://github.com/dolthub/dolt)
- [pygit2 Documentation](https://www.pygit2.org/)
- [GitPython + gitdb](https://github.com/gitpython-developers/gitdb)
- [GitRows](https://gitrows.com/)
- [So you want a Git Database?](https://www.dolthub.com/blog/2021-11-26-so-want-git-database/)
- [Package managers keep using git as a database](https://nesbitt.io/2025/12/24/package-managers-keep-using-git-as-a-database.html) (cautionary tale)
