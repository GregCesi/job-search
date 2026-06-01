"""Connexion SQLite — chemin résolu depuis la racine du repo."""
import sqlite3
from pathlib import Path

# Racine du repo = deux niveaux au-dessus de ce fichier (api/db.py → api/ → repo/)
_DB_PATH = Path(__file__).parent.parent / "data" / "job_search.sqlite"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
