"""Routes de la liste « À postuler » et de la file « À étudier » (EXE-210).

Lecture seule, aucun appel de modèle : les files se calculent à chaque lecture
(orchestrator/job_search/a_postuler). Du profil personnel, seules les
compétences servent, pour l'atteignabilité (H7).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

import orchestrator.job_search.paths as paths
from orchestrator.job_search.a_postuler import calcul
from orchestrator.job_search.a_postuler.regles import Regles, charger_regles
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.storage import a_postuler as stockage
from orchestrator.job_search.suivi import storage as suivi_storage

from .db import get_conn

router = APIRouter()

Tri = Literal[
    "rang", "entreprise", "contrat", "lieu", "famille", "recuperee", "atteignabilite"
]
FAMILLES = {"ia": calcul.IA, "developpeur": calcul.DEVELOPPEUR, "data": calcul.DATA}

_CLES_TRI = {
    "rang": lambda li: li.rang,
    "entreprise": lambda li: li.entreprise.casefold(),
    "contrat": lambda li: li.contrat.casefold(),
    "lieu": lambda li: li.lieu.casefold(),
    "famille": lambda li: li.famille,
    "recuperee": lambda li: li.recuperee or "",
    "atteignabilite": lambda li: li.atteignabilite,
}


def _classement() -> tuple[calcul.Classement, Regles]:
    try:
        profil, _ = load_profile(paths.PROFILE_PATH)
    except (OSError, yaml.YAMLError, ValidationError, TypeError, AttributeError):
        raise HTTPException(
            status_code=503,
            detail=f"Profil personnel absent ou illisible : {paths.PROFILE_PATH}",
        )
    try:
        regles = charger_regles(paths.A_POSTULER_PATH)
    except (OSError, yaml.YAMLError, KeyError, ValueError):
        raise HTTPException(
            status_code=503,
            detail=f"Règle des files absente ou illisible : {paths.A_POSTULER_PATH}",
        )
    alias = load_alias_table(paths.ALIAS_PATH)
    conn = get_conn()
    try:
        offres = stockage.lire_offres(conn)
        expirees = stockage.offres_expirees(conn)
        etats_stockes = suivi_storage.etat_map(conn)
        cles = stockage.cles_comparaison(conn)
    finally:
        conn.close()
    return calcul.classer(
        offres, etats_stockes, expirees, regles, profil, alias, cles
    ), regles


def _nombres(classement: calcul.Classement, file: str, regles: Regles) -> dict:
    """Nombres de la file entière, avant tout filtre (critère 54)."""
    toutes = classement.principale + classement.a_etudier
    return {
        "file_principale": len(classement.principale),
        "file_a_etudier": len(classement.a_etudier),
        "familles": {
            nom: sum(1 for li in toutes if li.famille == nom)
            for nom in FAMILLES.values()
        },
        "recentes": sum(
            1 for li in classement.file(file) if calcul.est_recente(li, regles)
        ),
    }


def _filtrer(
    lignes: list[calcul.Ligne],
    regles: Regles,
    famille: str | None,
    recentes: bool,
    q: str | None,
) -> list[calcul.Ligne]:
    if famille is not None:
        lignes = [li for li in lignes if li.famille == FAMILLES[famille]]
    if recentes:
        lignes = [li for li in lignes if calcul.est_recente(li, regles)]
    if q:
        mot = q.casefold()
        lignes = [
            li
            for li in lignes
            if mot in li.titre.casefold() or mot in li.entreprise.casefold()
        ]
    return lignes


@router.get("/a-postuler")
def a_postuler(
    file: Literal["principale", "a_etudier"] = calcul.PRINCIPALE,
    famille: Literal["ia", "developpeur", "data"] | None = None,
    recentes: bool = False,
    q: str | None = None,
    tri: Tri = "rang",
    ordre: Literal["asc", "desc"] = Query("asc"),
) -> dict:
    classement, regles = _classement()
    lignes = _filtrer(classement.file(file), regles, famille, recentes, q)
    cle = _CLES_TRI[tri]
    lignes = sorted(lignes, key=lambda li: (cle(li), li.rang), reverse=ordre == "desc")
    return {
        "file": file,
        "lignes": [asdict(li) for li in lignes],
        "nombres": _nombres(classement, file, regles),
        "hors_files": classement.hors_files(),
    }


@router.get("/offers/{offer_id}/a-postuler")
def a_postuler_offre(offer_id: int) -> dict:
    """La file et le rang d'une offre, ou le motif qui la laisse dehors ; pour un
    motif venu d'une autre offre, l'id et l'état de cette offre (EXE-219)."""
    classement, _ = _classement()
    for nom in (calcul.PRINCIPALE, calcul.A_ETUDIER):
        for li in classement.file(nom):
            if li.id == offer_id:
                return {
                    "offer_id": offer_id,
                    "file": nom,
                    "rang": li.rang,
                    "famille": li.famille,
                    "motif": None,
                    "meme_offre_que": None,
                }
    if offer_id not in classement.motifs:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return {
        "offer_id": offer_id,
        "file": None,
        "rang": None,
        "famille": None,
        "motif": classement.motifs[offer_id],
        "meme_offre_que": classement.meme_offre_que.get(offer_id),
    }
