"""
Async SQLite database layer using aiosqlite.

Schema
──────
files
  id          INTEGER PK AUTOINCREMENT
  file_name   TEXT    NOT NULL
  file_size   INTEGER NOT NULL          -- bytes
  sha256      TEXT    NOT NULL UNIQUE   -- for duplicate detection
  object_key  TEXT    NOT NULL          -- R2 key, e.g. uploads/abc123/foo.mp4
  public_slug TEXT    NOT NULL UNIQUE   -- UUID slug for the public URL
  uploaded_at TEXT    NOT NULL          -- ISO-8601 UTC timestamp
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config import config

logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name   TEXT    NOT NULL,
    file_size   INTEGER NOT NULL,
    sha256      TEXT    NOT NULL UNIQUE,
    object_key  TEXT    NOT NULL,
    public_slug TEXT    NOT NULL UNIQUE,
    uploaded_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_slug   ON files(public_slug);
"""


async def init_db() -> None:
    """Create tables if they don't exist."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.executescript(CREATE_TABLE_SQL)
        await db.commit()
    logger.info("Database initialised at %s", config.db_path)


async def save_file(
    file_name: str,
    file_size: int,
    sha256: str,
    object_key: str,
    public_slug: str,
) -> int:
    """Persist file metadata. Returns the new row id."""
    uploaded_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute(
            """
            INSERT INTO files (file_name, file_size, sha256, object_key, public_slug, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_name, file_size, sha256, object_key, public_slug, uploaded_at),
        )
        await db.commit()
        return cursor.lastrowid


async def get_file_by_hash(sha256: str) -> Optional[dict]:
    """Return the metadata row for a given SHA-256 hash, or None."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM files WHERE sha256 = ? LIMIT 1", (sha256,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_file_by_slug(slug: str) -> Optional[dict]:
    """Return the metadata row for a given public slug, or None."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM files WHERE public_slug = ? LIMIT 1", (slug,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def list_files(limit: int = 50, offset: int = 0) -> list[dict]:
    """List recently uploaded files (for debugging / admin)."""
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM files ORDER BY uploaded_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def delete_file_by_slug(slug: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute("DELETE FROM files WHERE public_slug = ?", (slug,))
        await db.commit()
