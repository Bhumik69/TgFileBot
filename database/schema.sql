-- ─────────────────────────────────────────────────────────────────────────────
-- Telegram File Bot – SQLite Schema
-- Applied automatically by database/db.py on first run.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Original filename as reported by Telegram
    file_name   TEXT    NOT NULL,

    -- File size in bytes (0 if Telegram did not report it)
    file_size   INTEGER NOT NULL,

    -- SHA-256 hex digest of the file content (used for duplicate detection)
    sha256      TEXT    NOT NULL UNIQUE,

    -- Cloudflare R2 object key, e.g. "uploads/a1b2c3d4/myfile.mp4"
    object_key  TEXT    NOT NULL,

    -- UUID used in public-facing URLs / short links
    public_slug TEXT    NOT NULL UNIQUE,

    -- ISO-8601 UTC timestamp, e.g. "2024-06-15T12:34:56.789012+00:00"
    uploaded_at TEXT    NOT NULL
);

-- Fast lookup by hash (duplicate detection)
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256);

-- Fast lookup by slug (future: redirect service)
CREATE INDEX IF NOT EXISTS idx_files_slug ON files(public_slug);
