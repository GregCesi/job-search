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
            id           INTEGER PRIMARY KEY,
            source       TEXT NOT NULL,
            source_id    TEXT NOT NULL,
            fingerprint  TEXT NOT NULL,
            title        TEXT,
            company      TEXT,
            location     TEXT,
            remote       INTEGER,
            contract_type TEXT,
            url          TEXT,
            fetched_at   TEXT,
            score        REAL,
            criteria_json TEXT,
            description  TEXT,
            UNIQUE(source, source_id)
        );

        CREATE TABLE IF NOT EXISTS verdicts (
            id         INTEGER PRIMARY KEY,
            offer_id   INTEGER REFERENCES offers(id),
            status     TEXT,
            created_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_offers_fingerprint ON offers(fingerprint);
    """)
    # Migration : ajoute description si colonne absente (DB existante)
    try:
        conn.execute("ALTER TABLE offers ADD COLUMN description TEXT")
        conn.commit()
    except Exception:
        pass  # colonne déjà présente
