-- TopShelf allowlist of Telegram chat ids permitted to talk to the bot.
-- Inbound-only: rows here can issue commands/free-text queries. Proactive pushes
-- (daily alert, weekly digest, web ping) still go to the .env owner only.
-- IF NOT EXISTS keeps the migration idempotent.

CREATE TABLE IF NOT EXISTS allowed_users (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  TEXT    NOT NULL UNIQUE,
    label    TEXT    NOT NULL DEFAULT '',
    active   INTEGER NOT NULL DEFAULT 1,
    added_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_allowed_users_active ON allowed_users(active);
