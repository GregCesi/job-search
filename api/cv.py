"""Endpoints CV adapté (EXE-58).

POST déclenche la génération (action explicite, offre retenue seulement — critère 2).
Si un CV est déjà `done`, POST le rend tel quel sans rappeler le modèle (critère 1).

Retenir une offre lance aussi le CV, en parallèle de la fiche (TCK-281, EXE-127) :
`launch_cv` est le point d'entrée idempotent partagé entre la route et la cascade
de `api/cascade.py`. Le CV est indépendant de la fiche entreprise, rien n'attend.
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
    clear_titre_defaut,
    get_titre_defaut,
    reset_pending,
    run_cv,
    set_titre,
    set_titre_defaut,
)
from orchestrator.job_search.pdf.coordonnees import (
    CoordonneesManquantesError,
    load_coordonnees,
)
from orchestrator.job_search.pdf.filename import resolve_piece_filename
from orchestrator.job_search.pdf.render import html_to_pdf
from orchestrator.job_search.pieces_state import mark_changed

from .db import get_conn

router = APIRouter(prefix="/offers")
# Titre par défaut (EXE-130) : réglage global, pas une ressource d'offre — pas de
# préfixe /offers/{offer_id}, à la différence du reste de ce module.
titre_defaut_router = APIRouter()

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()


def is_running(offer_id: int) -> bool:
    return offer_id in _running


def running_offer_ids() -> set[int]:
    return set(_running)


class SkillCorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["ajout", "retrait"]
    competence: str
    maitrisee: bool | None = None
    groupe: str | None = None


class CvTitreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titre: str
    par_defaut: bool = False


class TitreDefautIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titre_defaut: str


def _row_to_cv(row) -> dict:
    return {
        "statut": row["statut"],
        "html": row["html"],
        "titre": row["titre"],
        "localisation": row["localisation"],
        "au_cv": json.loads(row["au_cv_json"] or "[]"),
        "groupes": json.loads(row["groupes_json"] or "[]"),
        "notions": json.loads(row["notions_json"] or "[]"),
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
    mark_changed(offer_id)


async def launch_cv(offer_id: int) -> asyncio.Task | None:
    """Lance la génération si elle n'est pas déjà en cours ni déjà terminée —
    idempotent (critères 1, 11, 12 du ticket EXE-127). Rend la tâche créée, ou
    `None` si rien n'a été lancé."""
    if offer_id in _running:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT statut FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            return None
        reset_pending(conn, offer_id)
    _running.add(offer_id)
    task = asyncio.create_task(_generate(offer_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


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
    await launch_cv(offer_id)
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


@router.put("/{offer_id}/cv/titre")
def put_cv_titre(offer_id: int, body: CvTitreIn) -> dict:
    with get_conn() as conn:
        try:
            titre = set_titre(conn, offer_id, body.titre)
        except CvNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if body.par_defaut:
            set_titre_defaut(conn, titre)
        row = conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return _row_to_cv(row)


@titre_defaut_router.get("/cv/titre-defaut")
def get_cv_titre_defaut() -> dict:
    with get_conn() as conn:
        return {"titre_defaut": get_titre_defaut(conn)}


@titre_defaut_router.put("/cv/titre-defaut")
def put_cv_titre_defaut(body: TitreDefautIn) -> dict:
    with get_conn() as conn:
        try:
            titre = set_titre_defaut(conn, body.titre_defaut)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"titre_defaut": titre}


@titre_defaut_router.delete("/cv/titre-defaut")
def delete_cv_titre_defaut() -> dict:
    with get_conn() as conn:
        clear_titre_defaut(conn)
    return {"titre_defaut": None}


@router.get("/{offer_id}/cv/pdf")
def get_cv_pdf(offer_id: int) -> Response:
    """PDF téléchargeable du CV d'une offre retenue (EXE-102) — le CV généré tel
    quel, jamais recorrigé ; aucun appel modèle (critère 17)."""
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="Le PDF n'est produit que pour une offre retenue",
            )
        row = conn.execute(
            "SELECT html FROM cvs WHERE offer_id = ? AND statut = 'done'",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=409, detail="Le CV n'est pas généré pour cette offre"
            )
        try:
            coordonnees = load_coordonnees()
        except CoordonneesManquantesError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        filename = resolve_piece_filename(conn, offer_id, "CV", coordonnees)
    pdf_bytes = html_to_pdf(row["html"])
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
