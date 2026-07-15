"""Migration idempotente : ajoute offers.seen si absente."""
import sqlite3

from orchestrator.job_search.paths import DB_PATH


def run() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(offers)")}
        if "seen" in cols:
            print("seen already present — nothing to do")
            return
        conn.execute("ALTER TABLE offers ADD COLUMN seen INTEGER NOT NULL DEFAULT 0")
        conn.commit()
        print("Migration OK : seen column added")
    finally:
        conn.close()


if __name__ == "__main__":
    run()
