"""SQLite persistence layer for the LightWork Ops Agent."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).parent / "lightwork.db"

TEAMS = ["Engineering", "Product", "Commercial", "Operations"]
STATUSES = ["on_track", "at_risk", "missed", "done"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    owner TEXT,
    deadline TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'on_track',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_update_at TEXT
);

CREATE TABLE IF NOT EXISTS updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id INTEGER NOT NULL,
    author TEXT,
    text TEXT NOT NULL,
    status_inferred TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (commitment_id) REFERENCES commitments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nudges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commitment_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (commitment_id) REFERENCES commitments(id) ON DELETE CASCADE
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def add_commitment(
    team: str,
    title: str,
    deadline: str,
    owner: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "on_track",
) -> int:
    if team not in TEAMS:
        raise ValueError(f"team must be one of {TEAMS}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    # Validate deadline parses as YYYY-MM-DD
    datetime.strptime(deadline, "%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO commitments (team, title, description, owner, deadline, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (team, title, description, owner, deadline, status),
        )
        return cur.lastrowid


def list_commitments(
    team: Optional[str] = None,
    status: Optional[str] = None,
    include_done: bool = True,
) -> list[dict]:
    sql = "SELECT * FROM commitments WHERE 1=1"
    params: list = []
    if team:
        sql += " AND team = ?"
        params.append(team)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if not include_done:
        sql += " AND status != 'done'"
    sql += " ORDER BY date(deadline) ASC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_commitment(commitment_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
        ).fetchone()
        return dict(row) if row else None


def set_status(commitment_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    with get_conn() as conn:
        conn.execute(
            "UPDATE commitments SET status = ?, last_update_at = datetime('now') WHERE id = ?",
            (status, commitment_id),
        )


def log_update(
    commitment_id: int,
    text: str,
    author: Optional[str] = None,
    status_inferred: Optional[str] = None,
) -> int:
    if status_inferred and status_inferred not in STATUSES:
        raise ValueError(f"status_inferred must be one of {STATUSES}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO updates (commitment_id, author, text, status_inferred)
               VALUES (?, ?, ?, ?)""",
            (commitment_id, author, text, status_inferred),
        )
        update_sql = "UPDATE commitments SET last_update_at = datetime('now')"
        params: list = []
        if status_inferred:
            update_sql += ", status = ?"
            params.append(status_inferred)
        update_sql += " WHERE id = ?"
        params.append(commitment_id)
        conn.execute(update_sql, params)
        return cur.lastrowid


def list_updates(commitment_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM updates WHERE commitment_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (commitment_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_updates(days: int = 7) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(sep=" ")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.*, c.title AS commitment_title, c.team AS commitment_team
               FROM updates u
               JOIN commitments c ON c.id = u.commitment_id
               WHERE u.created_at >= ?
               ORDER BY u.created_at DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def record_nudge(commitment_id: int, reason: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO nudges (commitment_id, reason) VALUES (?, ?)",
            (commitment_id, reason),
        )
        return cur.lastrowid


def recent_nudge_exists(commitment_id: int, hours: int = 20) -> bool:
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(sep=" ")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM nudges WHERE commitment_id = ? AND created_at >= ?",
            (commitment_id, cutoff),
        ).fetchone()
        return row is not None


def days_until_deadline(deadline_iso: str, ref: Optional[date] = None) -> int:
    ref = ref or date.today()
    return (datetime.strptime(deadline_iso, "%Y-%m-%d").date() - ref).days


def days_since_last_update(c: dict, ref: Optional[datetime] = None) -> Optional[int]:
    ref = ref or datetime.now()
    last = c.get("last_update_at")
    if not last:
        return None
    last_dt = datetime.fromisoformat(last)
    return (ref - last_dt).days


def needs_attention(commitments: Optional[list[dict]] = None) -> list[dict]:
    """Return commitments that the FA should look at right now.

    Heuristic: not done AND (already past deadline, or deadline within 5 days
    with no update in 4+ days, or no update at all).
    """
    commitments = commitments or list_commitments(include_done=False)
    out = []
    for c in commitments:
        if c["status"] == "done":
            continue
        days_left = days_until_deadline(c["deadline"])
        stale = days_since_last_update(c)
        reason = None
        if days_left < 0 and c["status"] != "done":
            reason = f"Deadline passed {abs(days_left)} day(s) ago, not marked done"
        elif days_left <= 5 and (stale is None or stale >= 4):
            label = "no updates yet" if stale is None else f"last update {stale}d ago"
            reason = f"Deadline in {days_left} day(s), {label}"
        elif c["status"] == "at_risk":
            reason = "Currently flagged at risk"
        if reason:
            out.append({**c, "_attention_reason": reason, "_days_left": days_left})
    out.sort(key=lambda x: x["_days_left"])
    return out


def update_deadline(commitment_id: int, new_deadline: str) -> dict:
    """Change a commitment's deadline.

    Validates the date string. If the commitment is currently ``missed`` and
    the new deadline is today or in the future, status is auto-restored to
    ``on_track`` (since it's no longer a missed deadline). Logs an audit
    update so the change shows up in the commitment's history.

    Returns a dict with old/new deadline and whether status was restored.
    """
    datetime.strptime(new_deadline, "%Y-%m-%d")  # validate format
    c = get_commitment(commitment_id)
    if not c:
        raise ValueError(f"Commitment #{commitment_id} not found")

    old_deadline = c["deadline"]
    if old_deadline == new_deadline:
        return {
            "commitment_id": commitment_id,
            "old_deadline": old_deadline,
            "new_deadline": new_deadline,
            "status_restored": False,
        }

    new_deadline_date = datetime.strptime(new_deadline, "%Y-%m-%d").date()
    new_status = c["status"]
    status_restored = False
    if c["status"] == "missed" and new_deadline_date >= date.today():
        new_status = "on_track"
        status_restored = True

    with get_conn() as conn:
        conn.execute(
            """UPDATE commitments
               SET deadline = ?, status = ?, last_update_at = datetime('now')
               WHERE id = ?""",
            (new_deadline, new_status, commitment_id),
        )

    audit = f"Deadline changed from {old_deadline} to {new_deadline}"
    if status_restored:
        audit += " — status restored to on_track"
    log_update(commitment_id, text=audit, author="system")

    return {
        "commitment_id": commitment_id,
        "old_deadline": old_deadline,
        "new_deadline": new_deadline,
        "status_restored": status_restored,
    }


def auto_mark_missed_past_deadlines() -> int:
    """Flip any open commitment past its deadline to 'missed'.

    Cheap to call on every page load — one indexed UPDATE. Does not touch
    last_update_at, because an automatic clock-driven flip is not a human
    update and shouldn't reset the staleness signal.
    """
    today_iso = date.today().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            """UPDATE commitments
               SET status = 'missed'
               WHERE date(deadline) < date(?)
                 AND status NOT IN ('done', 'missed')""",
            (today_iso,),
        )
        return cur.rowcount


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
