"""
Purge des offres non pertinentes.

Après la suppression du scoring /10-/100, la purge automatique est désactivée.
Les offres sont triées par catégorie ; la suppression est un geste humain (verdict masqué).
"""
import sqlite3


def purge_irrelevant(conn: sqlite3.Connection) -> int:
    """No-op — purge automatique désactivée (scoring supprimé)."""
    return 0
