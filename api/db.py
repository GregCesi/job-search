"""Connexion SQLite — chemin résolu depuis paths.py (source unique)."""
import sqlite3

from orchestrator.job_search.paths import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
