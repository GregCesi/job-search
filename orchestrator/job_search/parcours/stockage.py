"""Lectures et écritures en base du parcours de candidature (EXE-217).

Table `parcours`, à part de `offers` : ce que le parcours lit (lien, lieu réel,
date de mise en ligne) ne réécrit jamais un champ de l'offre.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from orchestrator.job_search.parcours.lecture import Depart, Parcours


@dataclass(frozen=True)
class ParcoursLu:
    lu_le: str
    parcours: Parcours


def lire_depart(conn: sqlite3.Connection, offer_id: int) -> Depart | None:
    row = conn.execute(
        "SELECT source, source_id, url FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    if row is None:
        return None
    return Depart(source=row[0] or "", source_id=row[1] or "", url=row[2] or None)


def lire(conn: sqlite3.Connection, offer_id: int) -> ParcoursLu | None:
    row = conn.execute(
        "SELECT lu_le, maillons_json, fin_forme, fin_adresse, cle, lieu_reel, "
        "code_postal, provinces_json, en_ligne_depuis FROM parcours WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    if row is None:
        return None
    return ParcoursLu(
        lu_le=row[0],
        parcours=Parcours(
            maillons=json.loads(row[1] or "[]"),
            fin_forme=row[2],
            fin_adresse=row[3],
            cle=row[4],
            lieu_reel=row[5],
            code_postal=row[6],
            provinces=json.loads(row[7] or "[]"),
            en_ligne_depuis=row[8],
        ),
    )


def ecrire(conn: sqlite3.Connection, offer_id: int, lu_le: str, p: Parcours) -> None:
    """Une seconde lecture remplace la première."""
    conn.execute(
        """
        INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, fin_adresse,
                              cle, lieu_reel, code_postal, provinces_json, en_ligne_depuis)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            lu_le           = excluded.lu_le,
            maillons_json   = excluded.maillons_json,
            fin_forme       = excluded.fin_forme,
            fin_adresse     = excluded.fin_adresse,
            cle             = excluded.cle,
            lieu_reel       = excluded.lieu_reel,
            code_postal     = excluded.code_postal,
            provinces_json  = excluded.provinces_json,
            en_ligne_depuis = excluded.en_ligne_depuis
        """,
        (
            offer_id,
            lu_le,
            json.dumps(p.maillons, ensure_ascii=False),
            p.fin_forme,
            p.fin_adresse,
            p.cle,
            p.lieu_reel,
            p.code_postal,
            json.dumps(p.provinces, ensure_ascii=False),
            p.en_ligne_depuis,
        ),
    )
