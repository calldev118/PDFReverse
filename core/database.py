"""
Database layer using SQLite.
Tracks conversions for analytics.
Stores service state (enabled/disabled).
Manages admin accounts.
"""

import sqlite3
import os
import hashlib
import secrets
import threading
from datetime import datetime, date

from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "slipgrid.db")

_local = threading.local()

# Super admin cannot be deleted. Username is configurable via env so it is
# not pinned to a single hardcoded value.
SUPER_ADMIN = os.environ.get("SUPER_ADMIN_USERNAME", "tesla").strip().lower()


def _is_legacy_hash(stored):
    """True if `stored` is an old unsalted sha256 hex digest (not a werkzeug hash)."""
    return ":" not in stored and len(stored) == 64


def _get_conn():
    """Get a thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            pages_in INTEGER NOT NULL DEFAULT 0,
            pages_out INTEGER NOT NULL DEFAULT 0,
            sheets INTEGER NOT NULL DEFAULT 0,
            grid TEXT NOT NULL DEFAULT '3x3',
            paper_size TEXT NOT NULL DEFAULT 'A4',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_super INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Default: service enabled
        INSERT OR IGNORE INTO settings (key, value) VALUES ('service_enabled', '1');
    """)
    # Ensure super admin exists. The bootstrap password comes from the
    # environment; if unset, a strong random one is generated and printed
    # once (never hardcoded in source).
    row = conn.execute("SELECT id FROM admins WHERE username = ?", (SUPER_ADMIN,)).fetchone()
    if not row:
        super_pass = os.environ.get("SUPER_ADMIN_PASSWORD")
        if not super_pass:
            super_pass = secrets.token_urlsafe(16)
            print(
                f"[slipgrid] Created super admin '{SUPER_ADMIN}' with generated "
                f"password: {super_pass}  (set SUPER_ADMIN_PASSWORD to control this)"
            )
        conn.execute(
            "INSERT INTO admins (username, password_hash, is_super) VALUES (?, ?, 1)",
            (SUPER_ADMIN, generate_password_hash(super_pass)),
        )
    conn.commit()


def log_conversion(filename, pages_in, pages_out, sheets, grid, paper_size):
    """Log a successful PDF conversion."""
    conn = _get_conn()
    conn.execute(
        """INSERT INTO conversions (filename, pages_in, pages_out, sheets, grid, paper_size)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (filename, pages_in, pages_out, sheets, grid, paper_size),
    )
    conn.commit()


def get_total_conversions():
    """Total number of conversions ever."""
    conn = _get_conn()
    row = conn.execute("SELECT COUNT(*) as cnt FROM conversions").fetchone()
    return row["cnt"]


def get_today_conversions():
    """Conversions today."""
    conn = _get_conn()
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversions WHERE date(created_at) = ?",
        (today,),
    ).fetchone()
    return row["cnt"]


def get_daily_stats(days=30):
    """Get conversions per day for the last N days."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT date(created_at) as day, COUNT(*) as cnt
           FROM conversions
           WHERE created_at >= date('now', ?)
           GROUP BY date(created_at)
           ORDER BY day DESC""",
        (f"-{days} days",),
    ).fetchall()
    return [{"day": r["day"], "count": r["cnt"]} for r in rows]


def get_recent_conversions(limit=50):
    """Get recent conversions."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT id, filename, pages_in, pages_out, sheets, grid, paper_size, created_at
           FROM conversions ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def is_service_enabled():
    """Check if the processing service is enabled."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'service_enabled'"
    ).fetchone()
    return row["value"] == "1" if row else True


def set_service_enabled(enabled):
    """Enable or disable the processing service."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('service_enabled', ?)",
        ("1" if enabled else "0",),
    )
    conn.commit()


# ── Conversion deletion ──────────────────────────────────────────

def delete_conversion(conversion_id):
    """Delete a single conversion record."""
    conn = _get_conn()
    conn.execute("DELETE FROM conversions WHERE id = ?", (conversion_id,))
    conn.commit()


def delete_all_conversions():
    """Delete all conversion records."""
    conn = _get_conn()
    conn.execute("DELETE FROM conversions")
    conn.commit()


# ── Admin management ─────────────────────────────────────────────

def authenticate_admin(username, password):
    """Check admin credentials. Returns True if valid.

    Verifies against salted werkzeug hashes. Legacy unsalted sha256 hashes
    are accepted once and transparently upgraded to a werkzeug hash on a
    successful login.
    """
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, password_hash FROM admins WHERE username = ?",
        (username,),
    ).fetchone()
    if not row:
        return False

    stored = row["password_hash"]
    if _is_legacy_hash(stored):
        ok = secrets.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
        if ok:
            # Upgrade the legacy hash in place.
            conn.execute(
                "UPDATE admins SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), row["id"]),
            )
            conn.commit()
        return ok

    return check_password_hash(stored, password)


def get_all_admins():
    """Get list of admin accounts."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, is_super, created_at FROM admins ORDER BY is_super DESC, id"
    ).fetchall()
    return [dict(r) for r in rows]


def create_admin(username, password):
    """Create a new admin account. Returns (success, message)."""
    conn = _get_conn()
    username = username.strip().lower()
    if not username or not password:
        return False, "Username and password are required"
    if len(username) < 3:
        return False, "Username must be at least 3 characters"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    existing = conn.execute("SELECT id FROM admins WHERE username = ?", (username,)).fetchone()
    if existing:
        return False, f"Admin '{username}' already exists"
    conn.execute(
        "INSERT INTO admins (username, password_hash, is_super) VALUES (?, ?, 0)",
        (username, generate_password_hash(password)),
    )
    conn.commit()
    return True, f"Admin '{username}' created"


def delete_admin(admin_id):
    """Delete an admin account. Cannot delete the super admin."""
    conn = _get_conn()
    row = conn.execute("SELECT username, is_super FROM admins WHERE id = ?", (admin_id,)).fetchone()
    if not row:
        return False, "Admin not found"
    if row["is_super"]:
        return False, "Cannot delete the super admin"
    conn.execute("DELETE FROM admins WHERE id = ?", (admin_id,))
    conn.commit()
    return True, f"Admin '{row['username']}' deleted"
