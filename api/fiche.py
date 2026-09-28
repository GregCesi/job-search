"""Endpoints fiche entreprise (TCK-224).

Seules deux routes appellent le SDK : POST /fiche (génération, action explicite) et
POST /fiche/points/{idx}/explain (reprise de session). PATCH ne touche que la base.
"""
import asyncio
import json
from typing import Literal

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.fiche.service import reset_pending, run_fiche
from orchestrator.job_search.paths import FICHE_CWD

from .db import get_conn

router = APIRouter(prefix="/offers")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()

Tas = Literal["lettre", "entretien", "rien"]


class PointPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")  # `reaction` n'existe plus : un champ inconnu doit échouer, pas être ignoré

    tas: Tas | None = None


def _row_to_fiche(row) -> dict:
    return {
        "statut": row["statut"],
        "mode": row["mode"],
        "presentation": row["presentation"],
        "employeur_nom": row["employeur_nom"],
        "employeur_entite": row["employeur_entite"],
        "employeur_type_source": row["employeur_type_source"],
        "employeur_confiance": row["employeur_confiance"],
        "employeur_methode": row["employeur_methode"],
        "employeur_urls": json.loads(row["employeur_urls_json"] or "[]"),
        "points": json.loads(row["points_json"] or "[]"),
        "session_id": row["session_id"],
        "cost_usd": row["cost_usd"],
        "tools_called": json.loads(row["tools_called_json"] or "[]"),
        "api_key_source": row["api_key_source"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
    }


async def _generate(offer_id: int) -> None:
    try:
        await run_fiche(offer_id)
    finally:
        _running.discard(offer_id)


@router.post("/{offer_id}/fiche", status_code=202)
async def create_fiche(offer_id: int) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(status_code=409, detail="La fiche n'est produite que pour une offre retenue")
        f = conn.execute(
            "SELECT statut FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if f is not None and f["statut"] == "done":
            raise HTTPException(status_code=409, detail="Fiche déjà produite : la relancer effacerait les annotations")
        if offer_id not in _running:
            reset_pending(conn, offer_id)
    if offer_id not in _running:
        _running.add(offer_id)
        task = asyncio.create_task(_generate(offer_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    return {"statut": "pending"}


@router.get("/{offer_id}/fiche")
def get_fiche(offer_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
    fiche = _row_to_fiche(row)
    if fiche["statut"] == "pending" and offer_id not in _running:
        # Génération orpheline (API redémarrée en cours de route) : l'exposer comme relançable.
        fiche["statut"] = "error"
        fiche["error_message"] = "Génération interrompue (API redémarrée). Relancer la fiche."
    return fiche


def _update_point(offer_id: int, point_idx: int, mutate, expect_session: str | None = None) -> dict:
    """Read-modify-write de points_json sous verrou d'écriture (BEGIN IMMEDIATE) : pas de mise à jour perdue."""
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT points_json, session_id FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
        if expect_session is not None and row["session_id"] != expect_session:
            raise HTTPException(status_code=409, detail="La fiche a été régénérée pendant l'appel")
        points = json.loads(row["points_json"] or "[]")
        if not 0 <= point_idx < len(points):
            raise HTTPException(status_code=404, detail="Point inconnu")
        mutate(points[point_idx])
        conn.execute(
            "UPDATE fiches_entreprise SET points_json = ? WHERE offer_id = ?",
            (json.dumps(points, ensure_ascii=False), offer_id),
        )
        conn.commit()
        return points[point_idx]
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _load_points(conn, offer_id: int, point_idx: int) -> list[dict]:
    row = conn.execute(
        "SELECT points_json FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
    points = json.loads(row["points_json"] or "[]")
    if not 0 <= point_idx < len(points):
        raise HTTPException(status_code=404, detail="Point inconnu")
    return points


@router.patch("/{offer_id}/fiche/points/{point_idx}")
def patch_point(offer_id: int, point_idx: int, body: PointPatch) -> dict:
    def mutate(point: dict) -> None:
        for field in body.model_fields_set:  # un champ explicitement null efface la valeur
            point[field] = getattr(body, field)

    return _update_point(offer_id, point_idx, mutate)


@router.post("/{offer_id}/fiche/points/{point_idx}/explain")
async def explain_point(offer_id: int, point_idx: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT session_id FROM fiches_entreprise WHERE offer_id = ? AND statut = 'done'",
            (offer_id,),
        ).fetchone()
        if row is None or not row["session_id"]:
            raise HTTPException(status_code=409, detail="Fiche non terminée ou sans session")
        position = _load_points(conn, offer_id, point_idx)[point_idx]["position"]

    FICHE_CWD.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"Je ne connais pas ce point de la fiche : « {position} ». "
        "Explique-le en quelques phrases : ce que c'est, et ce que l'entreprise dit par là. "
        "Appuie-toi uniquement sur ce que tu as lu pendant la recherche."
    )
    explication = ""
    async for msg in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            resume=row["session_id"],
            max_turns=2,
            tools=[],
            allowed_tools=[],
            disallowed_tools=["WebSearch", "WebFetch", "Bash", "Write", "Edit", "NotebookEdit"],
            setting_sources=[],
            cwd=str(FICHE_CWD),
        ),
    ):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                raise HTTPException(status_code=502, detail=f"SDK en erreur ({msg.subtype})")
            explication = (msg.result or "").strip()
    if not explication:
        raise HTTPException(status_code=502, detail="Explication vide")

    # Écriture atomique, refusée si la fiche a été régénérée entre-temps (session_id changé).
    def mutate(point: dict) -> None:
        point["explication"] = explication

    _update_point(offer_id, point_idx, mutate, expect_session=row["session_id"])
    return explication
