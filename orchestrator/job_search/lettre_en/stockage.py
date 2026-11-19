"""Lecture et écriture de la version anglaise de la lettre (EXE-209).

Table d'interaction à part, `lettres_en` : la traduction ne s'écrit jamais dans
`lettres.texte`, dans `lettre_versions` ni dans `offers`, et ne touche ni la
marque Prête ni l'historique du texte français (critère 7).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from orchestrator.job_search.lettre_en.traduction import ResultatTraduction
from orchestrator.job_search.storage.db import init_db


class PasDeVersionAnglaiseError(Exception):
    def __init__(self) -> None:
        super().__init__("La version anglaise n'est pas générée pour cette offre")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def texte_fr_courant(conn: sqlite3.Connection, offer_id: int) -> str | None:
    """Texte français courant d'une lettre terminée ; `None` sinon."""
    init_db(conn)
    row = conn.execute(
        "SELECT texte FROM lettres WHERE offer_id = ? AND statut = 'done'",
        (offer_id,),
    ).fetchone()
    if row is None or not (row[0] or "").strip():
        return None
    return row[0]


def lire(conn: sqlite3.Connection, offer_id: int) -> dict | None:
    init_db(conn)
    row = conn.execute(
        "SELECT texte, texte_fr_source, origine, modele, created_at, updated_at "
        "FROM lettres_en WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "texte": row[0],
        "texte_fr_source": row[1],
        "origine": row[2],
        "modele": row[3],
        "created_at": row[4],
        "updated_at": row[5],
    }


def persister_traduction(
    conn: sqlite3.Connection,
    offer_id: int,
    texte_fr_source: str,
    resultat: ResultatTraduction,
) -> None:
    """Remplace la version anglaise courante par la nouvelle traduction."""
    init_db(conn)
    appel = {
        "modele": resultat.modele,
        "duree_s": resultat.duree_s,
        "cout_usd": resultat.cout_usd,
        "demande": resultat.demande,
        "reponse": resultat.reponse,
    }
    now = _now()
    conn.execute(
        """
        INSERT INTO lettres_en (offer_id, texte, texte_fr_source, origine, modele,
                                appel_json, created_at, updated_at)
        VALUES (?, ?, ?, 'modele', ?, ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            texte=excluded.texte, texte_fr_source=excluded.texte_fr_source,
            origine='modele', modele=excluded.modele, appel_json=excluded.appel_json,
            created_at=excluded.created_at, updated_at=excluded.updated_at
        """,
        (
            offer_id,
            resultat.texte,
            texte_fr_source,
            resultat.modele,
            json.dumps(appel, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()


def enregistrer_texte(conn: sqlite3.Connection, offer_id: int, texte: str) -> None:
    """Enregistre ma correction du texte anglais (critère 6). Le texte français
    de référence ne bouge pas : la fraîcheur reste mesurée contre lui."""
    init_db(conn)
    if not texte.strip():
        raise ValueError("le texte anglais ne peut pas être vide")
    cur = conn.execute(
        "UPDATE lettres_en SET texte = ?, origine = 'moi', updated_at = ? "
        "WHERE offer_id = ?",
        (texte, _now(), offer_id),
    )
    if cur.rowcount == 0:
        raise PasDeVersionAnglaiseError()
    conn.commit()
