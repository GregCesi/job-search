"""Lecture et rendu du parcours de candidature (EXE-217).

`lire_parcours` part uniquement de la vérification (`run_expiration_check`), lancée
par POST /offers/check-expirations ou par la fin d'un run (H7). Une panne sur une
offre n'arrête pas la lecture des suivantes ; un site injoignable laisse la fin,
la clé et le lieu lus auparavant tels quels.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timezone

import yaml

import orchestrator.job_search.paths as paths
from orchestrator.job_search.parcours import stockage
from orchestrator.job_search.parcours.adresses import charger_suivi
from orchestrator.job_search.parcours.lecture import (
    INCONNUE,
    Course,
    Depart,
    Lecteur,
    depart_possible,
)

JAMAIS_LU = "jamais lu"
SANS_LIEN = "sans lien"
LU = "lu"

_CE_QUI_SE_GARDE = (
    "fin_forme",
    "fin_adresse",
    "cle",
    "lieu_reel",
    "code_postal",
    "provinces",
    "en_ligne_depuis",
)


def _lire_une(conn: sqlite3.Connection, offer_id: int, lecteur: Lecteur) -> None:
    depart = stockage.lire_depart(conn, offer_id)
    if depart is None or not depart_possible(depart):
        return
    parcours = Course(depart, lecteur).lire()
    precedent = stockage.lire(conn, offer_id)
    if (
        parcours.panne
        and precedent is not None
        and precedent.parcours.fin_forme != INCONNUE
    ):
        gardes = {nom: getattr(precedent.parcours, nom) for nom in _CE_QUI_SE_GARDE}
        parcours = dataclasses.replace(parcours, **gardes)
    stockage.ecrire(conn, offer_id, datetime.now(timezone.utc).isoformat(), parcours)


def lire_parcours(conn: sqlite3.Connection, offer_ids: list[int]) -> None:
    """Lit le parcours de chaque offre désignée et le garde dans `parcours`."""
    try:
        suivi = charger_suivi(paths.A_POSTULER_PATH)
    except (OSError, yaml.YAMLError) as exc:
        print(f"[parcours] paramètres de suivi illisibles : {exc}")
        return
    lecteur = Lecteur(suivi)
    for offer_id in offer_ids:
        try:
            _lire_une(conn, offer_id, lecteur)
        except Exception as exc:  # une panne sur une offre n'arrête pas les suivantes
            print(f"[parcours] offre {offer_id} : lecture abandonnée ({exc})")
    conn.commit()


def rendu(depart: Depart, lu: stockage.ParcoursLu | None) -> dict:
    """Ce que rend GET /offers/{id}/parcours (H5)."""
    if lu is None:
        return {
            "etat": JAMAIS_LU if depart_possible(depart) else SANS_LIEN,
            "lu_le": None,
            "maillons": [],
            "fin": None,
            "cle": None,
            "lieu_reel": None,
            "code_postal": None,
            "provinces": [],
            "en_ligne_depuis": None,
        }
    p = lu.parcours
    return {
        "etat": LU,
        "lu_le": lu.lu_le,
        "maillons": p.maillons,
        "fin": {"forme": p.fin_forme, "adresse": p.fin_adresse},
        "cle": p.cle,
        "lieu_reel": p.lieu_reel,
        "code_postal": p.code_postal,
        "provinces": p.provinces,
        "en_ligne_depuis": p.en_ligne_depuis,
    }


def parcours_de(conn: sqlite3.Connection, offer_id: int) -> dict | None:
    """Le rendu du parcours d'une offre, ou None si l'offre est inconnue."""
    depart = stockage.lire_depart(conn, offer_id)
    if depart is None:
        return None
    return rendu(depart, stockage.lire(conn, offer_id))
