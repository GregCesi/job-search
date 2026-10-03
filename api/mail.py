"""Endpoint du mail de candidature d'une offre retenue (EXE-103).

GET déclenche le rendu (lecture seule, offre retenue seulement — critère 9).
Aucun appel modèle, aucun stockage : recalculé à chaque demande (critères 6, 10).
"""

from fastapi import APIRouter, HTTPException

from orchestrator.job_search.mail.candidature import (
    GabaritAbsentError,
    RepereInconnuError,
    load_gabarit,
    render_mail_candidature,
)
from orchestrator.job_search.pdf.filename import resolve_entreprise

from .db import get_conn

router = APIRouter(prefix="/offers")


@router.get("/{offer_id}/mail")
def get_mail_candidature(offer_id: int) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="Le mail n'est préparé que pour une offre retenue",
            )
        offer = conn.execute(
            "SELECT title, company FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        fiche = conn.execute(
            "SELECT employeur_nom FROM fiches_entreprise WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
    entreprise = resolve_entreprise(
        offer["company"] if offer else None,
        fiche["employeur_nom"] if fiche else None,
    )
    try:
        gabarit_text = load_gabarit()
    except GabaritAbsentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    intitule = (offer["title"] if offer else None) or ""
    try:
        return render_mail_candidature(gabarit_text, intitule, entreprise)
    except RepereInconnuError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
