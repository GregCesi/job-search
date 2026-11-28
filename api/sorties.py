"""Routes des sorties de la vérification et des annonces de mes candidatures (EXE-223).

GET /a-postuler/sorties rend les offres que la vérification tient hors des files,
avec leur motif, le signe vu, la preuve et la date ; POST /offers/{id}/remise
remet une de ces offres dans sa file, DELETE /offers/{id}/remise annule la remise.
GET /suivi/annonces rend, pour chaque candidature en cours, ce que la
vérification a vu de son annonce. Les deux lectures n'écrivent rien ; la remise
vit dans sa propre table, hors du module d'états, et ne change ni tri ni étape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from orchestrator.job_search.a_postuler import sorties as calcul_sorties
from orchestrator.job_search.parcours import stockage as parcours_stockage
from orchestrator.job_search.storage import a_postuler as stockage
from orchestrator.job_search.storage import remises as remises_stockage
from orchestrator.job_search.suivi import storage as suivi_storage

from .a_postuler import charger
from .db import get_conn

router = APIRouter()


def _sorties() -> list[dict]:
    entrees, regles, profil, alias = charger()
    conn = get_conn()
    try:
        verifications = stockage.verifications(conn)
    finally:
        conn.close()
    return calcul_sorties.sorties(entrees, verifications, regles, profil, alias)


@router.get("/a-postuler/sorties")
def get_sorties() -> list[dict]:
    return _sorties()


@router.post("/offers/{offer_id}/remise", status_code=204)
def poser_remise(offer_id: int) -> None:
    if offer_id not in {s["id"] for s in _sorties()}:
        raise HTTPException(
            status_code=409,
            detail="Seule une offre sortie par la vérification se remet dans la liste",
        )
    conn = get_conn()
    try:
        remises_stockage.poser(conn, offer_id)
    finally:
        conn.close()


@router.delete("/offers/{offer_id}/remise", status_code=204)
def annuler_remise(offer_id: int) -> None:
    conn = get_conn()
    try:
        retiree = remises_stockage.retirer(conn, offer_id)
    finally:
        conn.close()
    if not retiree:
        raise HTTPException(status_code=404, detail="Aucune remise pour cette offre")


@router.get("/suivi/annonces")
def get_annonces() -> list[dict]:
    conn = get_conn()
    try:
        rendues = []
        for oid in suivi_storage.offer_ids_en_cours(conn):
            lu = parcours_stockage.lire(conn, oid)
            fermeture = (lu.parcours.fermeture if lu else None) or {}
            rendues.append(
                {
                    "id": oid,
                    "ouverture": lu.parcours.ouverture if lu else None,
                    "signe": fermeture.get("signe"),
                    "site": fermeture.get("site"),
                    "verifiee_le": lu.verifiee_le if lu else None,
                }
            )
    finally:
        conn.close()
    return rendues
