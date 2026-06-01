-- TopShelf initial schema (PRD §4 "Data model (SQLite)").
-- All tables use IF NOT EXISTS so the migration is idempotent.

CREATE TABLE IF NOT EXISTS dispensaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    address     TEXT,
    lat         REAL,
    lng         REAL,
    dist_85251  REAL,
    dist_85255  REAL,
    platform    TEXT,
    menu_ref    TEXT,
    active      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS brands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT NOT NULL UNIQUE,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    tier            TEXT,
    allowlisted     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dispensary_id   INTEGER REFERENCES dispensaries(id),
    brand_id        INTEGER REFERENCES brands(id),
    name            TEXT NOT NULL,
    category        TEXT,
    strain_type     TEXT,
    lineage         TEXT,
    size_g          REAL,
    thc_pct         REAL,
    cbd_pct         REAL,
    unit            REAL,
    unit_label      TEXT,
    description     TEXT,
    effects_json    TEXT NOT NULL DEFAULT '[]',
    image_url       TEXT,
    menu_url        TEXT
);

CREATE TABLE IF NOT EXISTS price_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    observed_at     TEXT NOT NULL,
    price           REAL,
    sale_price      REAL,
    is_sale         INTEGER NOT NULL DEFAULT 0,
    source_platform TEXT,
    in_stock        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS deals (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id             INTEGER NOT NULL REFERENCES products(id),
    dispensary_id          INTEGER REFERENCES dispensaries(id),
    original_price         REAL,
    sale_price             REAL,
    discount_pct_validated INTEGER,
    unit_price             REAL,
    score                  INTEGER,
    score_factors_json     TEXT NOT NULL DEFAULT '[]',
    prior_avg              REAL,
    prior_min              REAL,
    is_lowest              INTEGER NOT NULL DEFAULT 0,
    pct_below_avg          INTEGER,
    is_fire                INTEGER NOT NULL DEFAULT 0,
    is_markup_trap         INTEGER NOT NULL DEFAULT 0,
    first_seen             TEXT,
    last_seen              TEXT,
    is_recurring           INTEGER NOT NULL DEFAULT 0,
    recurrence_dow         TEXT,
    in_stock               INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS filters (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    json_criteria       TEXT NOT NULL DEFAULT '{}',
    active              INTEGER NOT NULL DEFAULT 1,
    telegram_alerts_on  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS notifications_sent (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id         INTEGER REFERENCES deals(id),
    filter_id       INTEGER REFERENCES filters(id),
    sent_at         TEXT,
    alerted_price   REAL
);

CREATE TABLE IF NOT EXISTS digests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start    TEXT,
    sent_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_price_obs_product ON price_observations(product_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_deals_product ON deals(product_id);
CREATE INDEX IF NOT EXISTS idx_products_dispensary ON products(dispensary_id);
