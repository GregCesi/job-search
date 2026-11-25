"""Lectures en base des files « À postuler » et « À étudier » (EXE-210).

Lecture seule : rang, famille, file et motif ne s'écrivent jamais en base. L'état
d'une offre ne se lit pas ici, mais par le module d'états (suivi/storage.py).
"""

import sqlite3

from orchestrator.job_search.a_postuler.calcul import OffreLue


def lire_offres(conn: sqlite3.Connection) -> list[OffreLue]:
    rows = conn.execute(
        "SELECT id, title, company, location, source, url, contract_type, "
        "fetched_at, description, ad_language, extracted_facts_json, filtered_out "
        "FROM offers ORDER BY id ASC"
    ).fetchall()
    return [
        OffreLue(
            id=r[0],
            titre=r[1] or "",
            entreprise=r[2] or "",
            lieu=r[3] or "",
            source=r[4] or "",
            url=r[5] or "",
            contrat=r[6] or "",
            recuperee=r[7],
            description=r[8] or "",
            langue_annonce=r[9],
            faits_json=r[10],
            filtree=bool(r[11]),
        )
        for r in rows
    ]


def offres_expirees(conn: sqlite3.Connection) -> set[int]:
    """Offres dont la vérification d'expiration est positive."""
    rows = conn.execute("SELECT offer_id FROM expirations WHERE expired = 1").fetchall()
    return {r[0] for r in rows}
