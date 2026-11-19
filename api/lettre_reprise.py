"""Partir d'une de mes lettres (EXE-206).

GET /offers/{id}/lettre/mes-lettres rend les lettres marquées Prêtes sur
d'autres offres, de la plus récente à la plus ancienne. POST
/offers/{id}/lettre/copier copie l'une d'elles, mot pour mot, sur la lettre de
l'offre courante. Aucun appel de modèle : la copie est un calcul Python, à
part des trois appels encadrés (architecture.md, exceptions encadrées).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.lettre import stockage as lettre_stockage
from orchestrator.job_search.pieces_state import mark_changed
from orchestrator.job_search.suivi import storage as suivi_storage

from .db import get_conn
from .lettre import get_lettre

router = APIRouter(prefix="/offers")

RAISON_NON_RETENUE = "La lettre n'est préparée que pour une offre retenue"


class CopieLettreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_offer_id: int


def _check_retenue(conn, offer_id: int) -> None:
    if not suivi_storage.est_retenue(conn, offer_id):
        raise HTTPException(status_code=409, detail=RAISON_NON_RETENUE)


@router.get("/{offer_id}/lettre/mes-lettres")
def get_mes_lettres(offer_id: int) -> list[dict]:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        return lettre_stockage.mes_lettres(conn, offer_id)


@router.post("/{offer_id}/lettre/copier")
def copier_lettre(offer_id: int, body: CopieLettreIn) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        try:
            lettre_stockage.copier_lettre(conn, offer_id, body.source_offer_id)
        except lettre_stockage.CopieRefuseeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    mark_changed(offer_id)
    return get_lettre(offer_id)
