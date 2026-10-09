"""Avancement des pièces d'une offre retenue (EXE-127) — fiche, CV, lettre, mail.

Distinct de `pieces.py` (statut Prête, marqué à la main) : ceci dit si une
génération tourne, a fini ou a échoué, pour que l'app affiche où en est chaque
pièce sans que je doive ouvrir chaque fenêtre. Calcul 100% Python depuis l'état
déjà persisté et les registres en mémoire des tâches de fond.

`GET /avancement` (hors du préfixe `/offers/{id}` pour ne jamais être capturé
par la route `/offers/{offer_id}`) rend les offres dont une pièce est en cours
ou vient de changer d'état — pour le polling d'affichage, pas pour le détail
d'une offre précise.
"""

from fastapi import APIRouter, HTTPException

from orchestrator.job_search.avancement import (
    generation_avancement,
    lettre_avancement,
    mail_avancement,
)
from orchestrator.job_search.lettre.redaction import (
    blocage_lancement_lettre,
    resolve_offer_text,
)
from orchestrator.job_search.mail.candidature import (
    GabaritAbsentError,
    RepereInconnuError,
    load_gabarit,
    render_mail_candidature,
)
from orchestrator.job_search.pdf.filename import resolve_entreprise
from orchestrator.job_search.pieces_state import drain_changed

from . import cv as cv_api
from . import fiche as fiche_api
from . import lettre as lettre_api
from .db import get_conn

router = APIRouter()


def _mail_avancement(conn, offer_id: int) -> dict:
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
    intitule = (offer["title"] if offer else None) or ""
    try:
        gabarit_text = load_gabarit()
        render_mail_candidature(gabarit_text, intitule, entreprise)
    except (GabaritAbsentError, RepereInconnuError) as exc:
        return mail_avancement(False, str(exc))
    return mail_avancement(True, None)


def _compute_avancement(conn, offer_id: int) -> dict:
    fiche_row = conn.execute(
        "SELECT statut, error_message FROM fiches_entreprise WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    cv_row = conn.execute(
        "SELECT statut, error_message FROM cvs WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    lettre_row = conn.execute(
        "SELECT statut, error_message FROM lettres WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()

    fiche_statut = fiche_row["statut"] if fiche_row else None
    offer = conn.execute(
        "SELECT description_raw, description FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    offer_text = resolve_offer_text(
        offer["description_raw"] if offer else None,
        offer["description"] if offer else None,
    )
    blocage = blocage_lancement_lettre(fiche_statut, offer_text)

    return {
        "fiche": generation_avancement(fiche_row, fiche_api.is_running(offer_id)),
        "cv": generation_avancement(cv_row, cv_api.is_running(offer_id)),
        "lettre": lettre_avancement(
            lettre_row, lettre_api.is_running(offer_id), blocage
        ),
        "mail": _mail_avancement(conn, offer_id),
    }


@router.get("/offers/{offer_id}/avancement")
def get_avancement(offer_id: int) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="L'avancement n'est disponible que pour une offre retenue",
            )
        offer = conn.execute(
            "SELECT id FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")
        return _compute_avancement(conn, offer_id)


@router.get("/avancement")
def list_avancement() -> list[dict]:
    offer_ids = (
        drain_changed()
        | fiche_api.running_offer_ids()
        | cv_api.running_offer_ids()
        | lettre_api.running_offer_ids()
    )
    if not offer_ids:
        return []
    results = []
    with get_conn() as conn:
        for offer_id in sorted(offer_ids):
            offer = conn.execute(
                "SELECT id, title FROM offers WHERE id = ?", (offer_id,)
            ).fetchone()
            if offer is None:
                continue
            results.append(
                {
                    "id": offer["id"],
                    "title": offer["title"],
                    "avancement": _compute_avancement(conn, offer_id),
                }
            )
    return results
