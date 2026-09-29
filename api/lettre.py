"""Endpoints lettre de motivation (EXE-65).

Le choix des points est stocké avec la lettre, jamais dans la fiche entreprise
(architecture.md, exceptions encadrées) : PUT /lettre/points ne touche jamais
`fiches_entreprise.points_json`.

POST déclenche la génération (action explicite, offre retenue + fiche terminée +
au moins un point choisi — critères 3, 4, 8). Si une lettre est déjà `done`, POST la
rend telle quelle sans rappeler le modèle (critère 2).
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.lettre.redaction import point_text, resolve_chosen_indices
from orchestrator.job_search.lettre.service import reset_pending, run_lettre

from .db import get_conn

router = APIRouter(prefix="/offers")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()


class PointsChoisisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indices: list[int]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_fiche_points(conn, offer_id: int) -> list[dict] | None:
    row = conn.execute(
        "SELECT points_json FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["points_json"] or "[]")


def _fetch_stored_choice(conn, offer_id: int) -> str | None:
    row = conn.execute(
        "SELECT points_choisis_json FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    return row["points_choisis_json"] if row else None


def _points_with_choice(points: list[dict], chosen: set[int]) -> list[dict]:
    return [
        {"texte": point_text(p), "tas": p.get("tas"), "choisi": i in chosen}
        for i, p in enumerate(points)
    ]


@router.get("/{offer_id}/lettre/points")
def get_lettre_points(offer_id: int) -> list[dict]:
    with get_conn() as conn:
        points = _fetch_fiche_points(conn, offer_id)
        if points is None:
            raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
        chosen = set(
            resolve_chosen_indices(points, _fetch_stored_choice(conn, offer_id))
        )
    return _points_with_choice(points, chosen)


@router.put("/{offer_id}/lettre/points")
def set_lettre_points(offer_id: int, body: PointsChoisisIn) -> list[dict]:
    with get_conn() as conn:
        points = _fetch_fiche_points(conn, offer_id)
        if points is None:
            raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
        for idx in body.indices:
            if not 0 <= idx < len(points):
                raise HTTPException(status_code=404, detail="Point inconnu")
        conn.execute(
            """
            INSERT INTO lettres (offer_id, statut, points_choisis_json, created_at)
            VALUES (?, 'aucune', ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET points_choisis_json=excluded.points_choisis_json
            """,
            (offer_id, json.dumps(sorted(set(body.indices))), _now()),
        )
        conn.commit()
        chosen = set(
            resolve_chosen_indices(points, _fetch_stored_choice(conn, offer_id))
        )
    return _points_with_choice(points, chosen)


def _row_to_lettre(row) -> dict:
    return {
        "statut": row["statut"],
        "texte": row["texte"],
        "tournures_signalees": json.loads(row["tournures_signalees_json"] or "[]"),
        "nb_mots": row["nb_mots"],
        "depasse_longueur": bool(row["depasse_longueur"]),
        "modele": row["modele"],
        "cost_usd": row["cost_usd"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
    }


async def _generate(offer_id: int) -> None:
    try:
        await run_lettre(offer_id)
    finally:
        _running.discard(offer_id)


@router.post("/{offer_id}/lettre")
async def create_lettre(offer_id: int, response: Response) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="La lettre n'est générée que pour une offre retenue",
            )
        f = conn.execute(
            "SELECT statut FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if f is None or f["statut"] != "done":
            raise HTTPException(
                status_code=409,
                detail="La fiche entreprise de cette offre n'est pas terminée",
            )
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            response.status_code = 200
            return _row_to_lettre(row)

        points = _fetch_fiche_points(conn, offer_id) or []
        chosen = resolve_chosen_indices(
            points, row["points_choisis_json"] if row is not None else None
        )
        if not chosen:
            raise HTTPException(
                status_code=409, detail="Aucun point n'est choisi pour la lettre"
            )

        if offer_id not in _running:
            reset_pending(conn, offer_id)
    if offer_id not in _running:
        _running.add(offer_id)
        task = asyncio.create_task(_generate(offer_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    response.status_code = 202
    return {"statut": "pending"}


@router.get("/{offer_id}/lettre")
def get_lettre(offer_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de lettre pour cette offre")
    lettre = _row_to_lettre(row)
    if lettre["statut"] == "pending" and offer_id not in _running:
        # Génération orpheline (API redémarrée en cours de route) : l'exposer comme relançable.
        lettre["statut"] = "error"
        lettre["error_message"] = (
            "Génération interrompue (API redémarrée). Relancer la lettre."
        )
    return lettre
