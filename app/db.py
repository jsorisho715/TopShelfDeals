"""SQLite connection, migration runner, and a thin DAL.

Stdlib only (``sqlite3``). The database lives at ``data/topshelf.db`` (gitignored);
the ``data/`` directory is created on demand. Migrations are ordered ``.sql`` files
in the repo-root ``migrations/`` folder, tracked by a ``schema_version`` table.

Typical usage::

    from app import db
    db.run_migrations()          # idempotent; safe to call on every startup
    conn = db.get_conn()
    presets = db.list_filters(conn)

Connections return ``sqlite3.Row`` rows (mapping access by column name) and have
foreign keys enabled.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

# Repo root = two levels up from this file (app/db.py -> repo root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _REPO_ROOT / "data"
DB_PATH = DATA_DIR / "topshelf.db"
MIGRATIONS_DIR = _REPO_ROOT / "migrations"


# ===========================================================================
# Connection
# ===========================================================================
def get_conn(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Open a SQLite connection with row access by name + FKs enabled.

    Creates the parent ``data/`` directory if missing. Callers own the
    connection lifecycle (``with db.get_conn() as conn: ...`` commits/rolls back).
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ===========================================================================
# Migrations
# ===========================================================================
def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            filename   TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    _ensure_schema_version_table(conn)
    rows = conn.execute("SELECT version FROM schema_version;").fetchall()
    return {int(r["version"]) for r in rows}


def _migration_files() -> list[tuple[int, Path]]:
    """Return ``(version, path)`` for ordered ``NNNN_*.sql`` migration files."""
    out: list[tuple[int, Path]] = []
    if not MIGRATIONS_DIR.exists():
        return out
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        prefix = p.name.split("_", 1)[0]
        try:
            version = int(prefix)
        except ValueError:
            continue
        out.append((version, p))
    out.sort(key=lambda t: t[0])
    return out


def run_migrations(db_path: Optional[Path | str] = None) -> list[int]:
    """Apply any pending migrations in order. Returns versions newly applied.

    Idempotent: already-applied versions (tracked in ``schema_version``) are
    skipped. Each migration runs in its own transaction.
    """
    applied_now: list[int] = []
    conn = get_conn(db_path)
    try:
        done = _applied_versions(conn)
        for version, path in _migration_files():
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn:  # transaction
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_version (version, filename) VALUES (?, ?);",
                    (version, path.name),
                )
            applied_now.append(version)
        return applied_now
    finally:
        conn.close()


# ===========================================================================
# Generic helpers
# ===========================================================================
def _insert(conn: sqlite3.Connection, table: str, data: dict[str, Any]) -> int:
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    cur = conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({placeholders});",
        tuple(data.values()),
    )
    return int(cur.lastrowid)


def _rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# ===========================================================================
# Dispensaries
# ===========================================================================
def insert_dispensary(conn: sqlite3.Connection, **fields: Any) -> int:
    return _insert(conn, "dispensaries", fields)


def get_dispensary(conn: sqlite3.Connection, dispensary_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM dispensaries WHERE id = ?;", (dispensary_id,)).fetchone()
    return dict(r) if r else None


def get_dispensary_by_name(conn: sqlite3.Connection, name: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM dispensaries WHERE name = ?;", (name,)).fetchone()
    return dict(r) if r else None


def list_dispensaries(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM dispensaries ORDER BY name;").fetchall())


# ===========================================================================
# Brands
# ===========================================================================
def insert_brand(conn: sqlite3.Connection, **fields: Any) -> int:
    return _insert(conn, "brands", fields)


def get_brand_by_name(conn: sqlite3.Connection, canonical_name: str) -> Optional[dict]:
    r = conn.execute(
        "SELECT * FROM brands WHERE canonical_name = ?;", (canonical_name,)
    ).fetchone()
    return dict(r) if r else None


def list_brands(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM brands ORDER BY canonical_name;").fetchall())


# ===========================================================================
# Products
# ===========================================================================
def insert_product(conn: sqlite3.Connection, **fields: Any) -> int:
    return _insert(conn, "products", fields)


def get_product(conn: sqlite3.Connection, product_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM products WHERE id = ?;", (product_id,)).fetchone()
    return dict(r) if r else None


def list_products(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(conn.execute("SELECT * FROM products ORDER BY id;").fetchall())


# ===========================================================================
# Price observations
# ===========================================================================
def insert_price_observation(conn: sqlite3.Connection, **fields: Any) -> int:
    return _insert(conn, "price_observations", fields)


def list_price_observations(
    conn: sqlite3.Connection, product_id: int
) -> list[dict]:
    """All observations for a product, oldest -> newest (by observed_at)."""
    rows = conn.execute(
        "SELECT * FROM price_observations WHERE product_id = ? ORDER BY observed_at ASC;",
        (product_id,),
    ).fetchall()
    return _rows_to_dicts(rows)


# ===========================================================================
# Deals
# ===========================================================================
def insert_deal(conn: sqlite3.Connection, **fields: Any) -> int:
    return _insert(conn, "deals", fields)


def get_deal(conn: sqlite3.Connection, deal_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM deals WHERE id = ?;", (deal_id,)).fetchone()
    return dict(r) if r else None


def list_deals(conn: sqlite3.Connection) -> list[dict]:
    return _rows_to_dicts(
        conn.execute("SELECT * FROM deals ORDER BY score DESC;").fetchall()
    )


# ===========================================================================
# Filters (CRUD) — the API agent uses these for /api/filters
# ===========================================================================
def _filter_row_to_preset(row: sqlite3.Row | dict) -> dict:
    """Convert a DB row into the preset shape the UI expects:
    ``{ id, name, c: {...}, active, telegram_alerts_on }``.

    ``c`` is the parsed ``json_criteria`` (``{cat, sort, maxDist, minOff, inStock}``).
    """
    d = dict(row)
    try:
        criteria = json.loads(d.get("json_criteria") or "{}")
    except (json.JSONDecodeError, TypeError):
        criteria = {}
    return {
        "id": d.get("id"),
        "name": d.get("name"),
        "c": criteria,
        "active": bool(d.get("active", 1)),
        "telegram_alerts_on": bool(d.get("telegram_alerts_on", 1)),
    }


def list_filters(conn: sqlite3.Connection) -> list[dict]:
    """Return all saved filter presets in UI shape (``{id, name, c, ...}``)."""
    rows = conn.execute("SELECT * FROM filters ORDER BY id;").fetchall()
    return [_filter_row_to_preset(r) for r in rows]


def get_filter(conn: sqlite3.Connection, filter_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM filters WHERE id = ?;", (filter_id,)).fetchone()
    return _filter_row_to_preset(r) if r else None


def create_filter(
    conn: sqlite3.Connection,
    name: str,
    criteria: Optional[dict] = None,
    active: bool = True,
    telegram_alerts_on: bool = True,
) -> dict:
    """Create a preset. ``criteria`` is the ``c`` object; it is JSON-encoded into
    ``json_criteria``. Returns the created preset in UI shape."""
    with conn:
        new_id = _insert(
            conn,
            "filters",
            {
                "name": name,
                "json_criteria": json.dumps(criteria or {}),
                "active": 1 if active else 0,
                "telegram_alerts_on": 1 if telegram_alerts_on else 0,
            },
        )
    return get_filter(conn, new_id)  # type: ignore[return-value]


def update_filter(
    conn: sqlite3.Connection,
    filter_id: int,
    name: Optional[str] = None,
    criteria: Optional[dict] = None,
    active: Optional[bool] = None,
    telegram_alerts_on: Optional[bool] = None,
) -> Optional[dict]:
    """Patch a preset (only provided fields change). Returns updated preset or None."""
    sets: list[str] = []
    vals: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        vals.append(name)
    if criteria is not None:
        sets.append("json_criteria = ?")
        vals.append(json.dumps(criteria))
    if active is not None:
        sets.append("active = ?")
        vals.append(1 if active else 0)
    if telegram_alerts_on is not None:
        sets.append("telegram_alerts_on = ?")
        vals.append(1 if telegram_alerts_on else 0)
    if sets:
        vals.append(filter_id)
        with conn:
            conn.execute(f"UPDATE filters SET {', '.join(sets)} WHERE id = ?;", tuple(vals))
    return get_filter(conn, filter_id)


def delete_filter(conn: sqlite3.Connection, filter_id: int) -> bool:
    """Delete a preset. Returns True if a row was removed."""
    with conn:
        cur = conn.execute("DELETE FROM filters WHERE id = ?;", (filter_id,))
    return cur.rowcount > 0


# ===========================================================================
# Allowed users (bot allowlist) — inbound-only Telegram chat ids
# ===========================================================================
def _allowed_user_row_to_dict(row: sqlite3.Row | dict) -> dict:
    """Convert a DB row into the UI shape: ``{id, chat_id, label, active, added_at}``."""
    d = dict(row)
    return {
        "id": d.get("id"),
        "chat_id": d.get("chat_id"),
        "label": d.get("label") or "",
        "active": bool(d.get("active", 1)),
        "added_at": d.get("added_at"),
    }


def list_allowed_users(conn: sqlite3.Connection) -> list[dict]:
    """Return all allowlisted users in UI shape, oldest first."""
    rows = conn.execute("SELECT * FROM allowed_users ORDER BY id;").fetchall()
    return [_allowed_user_row_to_dict(r) for r in rows]


def get_allowed_user(conn: sqlite3.Connection, user_id: int) -> Optional[dict]:
    r = conn.execute("SELECT * FROM allowed_users WHERE id = ?;", (user_id,)).fetchone()
    return _allowed_user_row_to_dict(r) if r else None


def add_allowed_user(
    conn: sqlite3.Connection, chat_id: str, label: str = ""
) -> dict:
    """Insert a new allowlisted chat id. Raises ``sqlite3.IntegrityError`` on duplicate."""
    with conn:
        new_id = _insert(
            conn,
            "allowed_users",
            {"chat_id": str(chat_id), "label": label or ""},
        )
    return get_allowed_user(conn, new_id)  # type: ignore[return-value]


def update_allowed_user(
    conn: sqlite3.Connection,
    user_id: int,
    label: Optional[str] = None,
    active: Optional[bool] = None,
) -> Optional[dict]:
    """Patch an allowlisted user (only provided fields change)."""
    sets: list[str] = []
    vals: list[Any] = []
    if label is not None:
        sets.append("label = ?")
        vals.append(label)
    if active is not None:
        sets.append("active = ?")
        vals.append(1 if active else 0)
    if sets:
        vals.append(user_id)
        with conn:
            conn.execute(
                f"UPDATE allowed_users SET {', '.join(sets)} WHERE id = ?;",
                tuple(vals),
            )
    return get_allowed_user(conn, user_id)


def delete_allowed_user(conn: sqlite3.Connection, user_id: int) -> bool:
    """Delete an allowlisted user. Returns True if a row was removed."""
    with conn:
        cur = conn.execute("DELETE FROM allowed_users WHERE id = ?;", (user_id,))
    return cur.rowcount > 0


def is_allowed_chat_id(conn: sqlite3.Connection, chat_id: str) -> bool:
    """True if ``chat_id`` is present and active in the allowlist."""
    r = conn.execute(
        "SELECT 1 FROM allowed_users WHERE chat_id = ? AND active = 1 LIMIT 1;",
        (str(chat_id),),
    ).fetchone()
    return r is not None
