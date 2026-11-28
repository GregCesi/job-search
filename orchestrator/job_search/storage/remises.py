"""Remises à la main d'offres sorties par la vérification (EXE-223).

Table `remises`, à part du module d'états : une remise n'est ni un tri ni une
étape. Elle ne naît que de POST /offers/{id}/remise et ne s'efface que par
DELETE /offers/{id}/remise.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def remises(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT offer_id FROM remises").fetchall()}


def poser(conn: sqlite3.Connection, offer_id: int) -> None:
    conn.execute(
        "INSERT INTO remises (offer_id, remise_le) VALUES (?, ?) "
        "ON CONFLICT(offer_id) DO NOTHING",
        (offer_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def retirer(conn: sqlite3.Connection, offer_id: int) -> bool:
    """Retire la remise ; rend False s'il n'y en avait pas."""
    cur = conn.execute("DELETE FROM remises WHERE offer_id = ?", (offer_id,))
    conn.commit()
    return cur.rowcount > 0
