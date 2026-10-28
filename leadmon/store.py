"""Local SQLite storage: posts already seen, matches, check history, pause state.

Only what the alert needs is kept: title, a short excerpt, link, dates and the match reason.
The post body and the author's name are never stored.
"""
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXCERPT_CHARS = 200
STATUSES = ("new", "reviewed", "ignored")
SEEN_RETENTION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    client TEXT NOT NULL,
    item_id TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (client, item_id)
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    client_name TEXT NOT NULL,
    item_id TEXT NOT NULL,
    source TEXT NOT NULL,
    community TEXT NOT NULL,
    title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    url TEXT NOT NULL,
    published TEXT NOT NULL,
    matched_at TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    notified INTEGER NOT NULL DEFAULT 0,
    UNIQUE (client, item_id)
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client TEXT NOT NULL,
    started TEXT NOT NULL,
    finished TEXT,
    fetched INTEGER DEFAULT 0,
    new_items INTEGER DEFAULT 0,
    matches INTEGER DEFAULT 0,
    alerts_sent INTEGER DEFAULT 0,
    errors TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def commit(self):
        self.db.commit()

    # --- pause and back-off state ---

    def _get(self, key):
        row = self.db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _set(self, key, value):
        if value is None:
            self.db.execute("DELETE FROM state WHERE key = ?", (key,))
        else:
            self.db.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def is_paused(self, client: str | None = None) -> bool:
        return self._get(f"paused:{client or '*'}") == "1"

    def set_paused(self, client: str | None, paused: bool):
        self._set(f"paused:{client or '*'}", "1" if paused else None)

    def cooldown_until(self, source: str):
        value = self._get(f"cooldown:{source}")
        return datetime.fromisoformat(value) if value else None

    def set_cooldown(self, source: str, until: datetime):
        self._set(f"cooldown:{source}", iso(until))

    # --- seen posts ---

    def is_seen(self, client: str, item_id: str) -> bool:
        return self.db.execute(
            "SELECT 1 FROM seen WHERE client = ? AND item_id = ?", (client, item_id)
        ).fetchone() is not None

    def mark_seen(self, client: str, item_id: str):
        self.db.execute(
            "INSERT OR IGNORE INTO seen (client, item_id, first_seen) VALUES (?, ?, ?)",
            (client, item_id, iso(utcnow())),
        )

    def prune_seen(self):
        self.db.execute(
            "DELETE FROM seen WHERE first_seen < ?", (iso(utcnow() - timedelta(days=SEEN_RETENTION_DAYS)),)
        )
        self.db.commit()

    # --- matches ---

    def save_match(self, client, item, reason: str):
        self.db.execute(
            """INSERT OR IGNORE INTO matches
               (client, client_name, item_id, source, community, title, excerpt, url, published, matched_at, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (client.slug, client.name, item.id, item.source, item.community, item.title,
             excerpt(item.text), item.url, iso(item.published), iso(utcnow()), reason),
        )

    def title_matched_recently(self, client: str, title: str, days: int = 7) -> bool:
        """The same post is often cross-posted to several subreddits; alert on it once."""
        return self.db.execute(
            """SELECT 1 FROM matches WHERE client = ? AND lower(title) = lower(?)
               AND matched_at >= ?""",
            (client, title.strip(), iso(utcnow() - timedelta(days=days))),
        ).fetchone() is not None

    def pending_alerts(self, client: str, since: datetime, limit: int) -> list:
        return self.db.execute(
            """SELECT * FROM matches WHERE client = ? AND notified = 0 AND matched_at >= ?
               ORDER BY published DESC LIMIT ?""",
            (client, iso(since), limit),
        ).fetchall()

    def mark_notified(self, match_id: int):
        self.db.execute("UPDATE matches SET notified = 1 WHERE id = ?", (match_id,))
        self.db.commit()

    def list_matches(self, status: str | None = None, client: str | None = None, limit: int = 200) -> list:
        sql, args = "SELECT * FROM matches WHERE 1 = 1", []
        if status in STATUSES:
            sql += " AND status = ?"
            args.append(status)
        if client:
            sql += " AND client = ?"
            args.append(client)
        sql += " ORDER BY matched_at DESC, published DESC LIMIT ?"
        args.append(limit)
        return self.db.execute(sql, args).fetchall()

    def status_counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM matches GROUP BY status").fetchall()
        counts = {s: 0 for s in STATUSES}
        counts.update({r["status"]: r["n"] for r in rows})
        return counts

    def set_status(self, match_id: int, status: str):
        if status not in STATUSES:
            raise ValueError(f"unknown status {status!r}")
        self.db.execute("UPDATE matches SET status = ? WHERE id = ?", (status, match_id))
        self.db.commit()

    # --- check history ---

    def start_run(self, client: str) -> int:
        cur = self.db.execute("INSERT INTO runs (client, started) VALUES (?, ?)", (client, iso(utcnow())))
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, *, fetched, new_items, matches, alerts_sent, errors):
        self.db.execute(
            """UPDATE runs SET finished = ?, fetched = ?, new_items = ?, matches = ?, alerts_sent = ?, errors = ?
               WHERE id = ?""",
            (iso(utcnow()), fetched, new_items, matches, alerts_sent, "\n".join(errors), run_id),
        )
        self.db.commit()

    def last_run_started(self, client: str):
        row = self.db.execute(
            "SELECT started FROM runs WHERE client = ? ORDER BY id DESC LIMIT 1", (client,)
        ).fetchone()
        return datetime.fromisoformat(row["started"]) if row else None

    def recent_runs(self, limit: int = 10) -> list:
        return self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
