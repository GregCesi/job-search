"""Lectures en base des files « À postuler » et « À étudier » (EXE-210).

Lecture seule : rang, famille, file et motif ne s'écrivent jamais en base. L'état
d'une offre ne se lit pas ici, mais par le module d'états (suivi/storage.py).
"""

import sqlite3

from orchestrator.job_search.a_postuler.calcul import OffreLue
from orchestrator.job_search.parcours.lecture import INCONNUE


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


def cles_comparaison(conn: sqlite3.Connection) -> dict[int, str]:
    """La clé de comparaison du parcours lu de chaque offre qui en a une (EXE-219).
    Un parcours à la fin de forme « inconnue » compte comme sans clé."""
    rows = conn.execute(
        "SELECT offer_id, cle FROM parcours WHERE cle IS NOT NULL AND fin_forme != ?",
        (INCONNUE,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}
