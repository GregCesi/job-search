import sqlite3
from pathlib import Path

DB_PATH = Path("data/job_search.sqlite")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS offers (
            id                   INTEGER PRIMARY KEY,
            source               TEXT NOT NULL,
            source_id            TEXT NOT NULL,
            fingerprint          TEXT NOT NULL,
            title                TEXT,
            company              TEXT,
            location             TEXT,
            remote               INTEGER,
            contract_type        TEXT,
            nature_contract      TEXT,
            alternance           INTEGER NOT NULL DEFAULT 0,
            full_time            INTEGER,
            company_size         TEXT,
            experience_required  TEXT,
            rome_code            TEXT,
            rome_label           TEXT,
            url                  TEXT,
            fetched_at           TEXT,
            description          TEXT,
            seen                 INTEGER NOT NULL DEFAULT 0,
            extracted_facts_json TEXT,
            desirability         REAL,
            desirability_detail  TEXT,
            attainability        TEXT,
            attainability_detail TEXT,
            UNIQUE(source, source_id)
        );

        CREATE TABLE IF NOT EXISTS verdicts (
            id         INTEGER PRIMARY KEY,
            offer_id   INTEGER REFERENCES offers(id),
            status     TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_offers_fingerprint ON offers(fingerprint);

        CREATE TABLE IF NOT EXISTS human_reviews (
            offer_id          TEXT PRIMARY KEY,
            ratings_json      TEXT NOT NULL,
            ai_snapshot_json  TEXT NOT NULL,
            global_audit_text TEXT,
            global_score      INTEGER,
            seen_at_review    INTEGER NOT NULL DEFAULT 0,
            created_at        TEXT NOT NULL
        );
    """)
    migrate_offers_schema(conn)


def migrate_offers_schema(conn: sqlite3.Connection) -> None:
    """Apply incremental column additions/removals to an existing offers table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(offers)").fetchall()}

    add_cols = [
        ("description",          "TEXT"),
        ("seen",                 "INTEGER NOT NULL DEFAULT 0"),
        ("nature_contract",      "TEXT"),
        ("alternance",           "INTEGER NOT NULL DEFAULT 0"),
        ("full_time",            "INTEGER"),
        ("company_size",         "TEXT"),
        ("experience_required",  "TEXT"),
        ("rome_code",            "TEXT"),
        ("rome_label",           "TEXT"),
        ("extracted_facts_json", "TEXT"),
        ("desirability",         "REAL"),
        ("desirability_detail",  "TEXT"),
        ("attainability",        "TEXT"),
        ("attainability_detail", "TEXT"),
        ("filtered_out",         "INTEGER NOT NULL DEFAULT 0"),
        ("filter_reason",        "TEXT"),
    ]
    for col, col_type in add_cols:
        if col not in existing:
            conn.execute(f"ALTER TABLE offers ADD COLUMN {col} {col_type}")

    # Suppression des anciens champs de scoring Zone A
    for col in ("score", "criteria_json"):
        if col in existing:
            conn.execute(f"ALTER TABLE offers DROP COLUMN {col}")

    conn.commit()
