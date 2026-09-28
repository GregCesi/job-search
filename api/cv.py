"""Endpoints CV adapté (EXE-58).

POST déclenche la génération (action explicite, offre retenue seulement — critère 2).
Si un CV est déjà `done`, POST le rend tel quel sans rappeler le modèle (critère 1).
"""

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.cv.corrections import (
    SkillAlreadyPresentError,
    SkillNotFoundError,
    UnknownGroupError,
)
from orchestrator.job_search.cv.service import (
    CvNotReadyError,
    apply_correction,
    reset_pending,
    run_cv,
)

from .db import get_conn

router = APIRouter(prefix="/offers")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()


class SkillCorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["ajout", "retrait"]
    competence: str
    maitrisee: bool | None = None
    groupe: str | None = None


def _row_to_cv(row) -> dict:
    return {
        "statut": row["statut"],
        "html": row["html"],
        "titre": row["titre"],
        "localisation": row["localisation"],
        "au_cv": json.loads(row["au_cv_json"] or "[]"),
        "demande_sans_y_etre": json.loads(row["demande_sans_y_etre_json"] or "[]"),
        "ajouts_permis": json.loads(row["ajouts_permis_json"] or "[]"),
        "seuil_utilise": row["seuil_utilise"],
        "cost_usd": row["cost_usd"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
    }


async def _generate(offer_id: int) -> None:
    try:
        await run_cv(offer_id)
    finally:
        _running.discard(offer_id)


@router.post("/{offer_id}/cv")
async def create_cv(offer_id: int, response: Response) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="Le CV n'est généré que pour une offre retenue",
            )
        row = conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            response.status_code = 200
            return _row_to_cv(row)
        if offer_id not in _running:
            reset_pending(conn, offer_id)
    if offer_id not in _running:
        _running.add(offer_id)
        task = asyncio.create_task(_generate(offer_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    response.status_code = 202
    return {"statut": "pending"}


@router.get("/{offer_id}/cv")
def get_cv(offer_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de CV pour cette offre")
    cv = _row_to_cv(row)
    if cv["statut"] == "pending" and offer_id not in _running:
        # Génération orpheline (API redémarrée en cours de route) : l'exposer comme relançable.
        cv["statut"] = "error"
        cv["error_message"] = "Génération interrompue (API redémarrée). Relancer le CV."
    return cv


@router.post("/{offer_id}/cv/skills")
def correct_cv_skill(offer_id: int, body: SkillCorrectionIn) -> dict:
    with get_conn() as conn:
        try:
            apply_correction(
                conn,
                offer_id,
                body.action,
                body.competence,
                body.maitrisee,
                body.groupe,
            )
        except CvNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SkillAlreadyPresentError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SkillNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (UnknownGroupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row = conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return _row_to_cv(row)


@router.get("/{offer_id}/cv/corrections")
def get_cv_corrections(offer_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT action, competence, maitrisee, groupe, created_at FROM cv_corrections "
            "WHERE offer_id = ? ORDER BY id ASC",
            (offer_id,),
        ).fetchall()
    return [
        {
            "action": r["action"],
            "competence": r["competence"],
            "maitrisee": bool(r["maitrisee"]),
            "groupe": r["groupe"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
