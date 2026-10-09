"""Endpoints fiche entreprise (TCK-224).

Seules deux routes appellent le SDK : POST /fiche (génération, action explicite) et
POST /fiche/points/{idx}/explain (reprise de session). PATCH ne touche que la base.

Retenir une offre lance aussi la fiche (TCK-281, EXE-127) : `launch_fiche` est le
point d'entrée idempotent partagé entre la route et la cascade de `api/cascade.py`.
Sa fin enchaîne la lettre (`launch_lettre_if_ready`) sur les points qu'elle désigne
elle-même — jamais sur un changement de profil ou de verdict ultérieur.
"""

import asyncio
import json
from typing import Literal

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.fiche import intermediaires
from orchestrator.job_search.fiche.service import reset_pending, run_fiche
from orchestrator.job_search.lettre.repertoire import sujet_libelle
from orchestrator.job_search.paths import FICHE_CWD
from orchestrator.job_search.pieces_state import mark_changed

from . import lettre as lettre_api
from .db import get_conn

router = APIRouter(prefix="/offers")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()


def is_running(offer_id: int) -> bool:
    return offer_id in _running


def running_offer_ids() -> set[int]:
    return set(_running)


Tas = Literal["lettre", "entretien", "rien"]


class PointPatch(BaseModel):
    model_config = ConfigDict(
        extra="forbid"
    )  # `reaction` n'existe plus : un champ inconnu doit échouer, pas être ignoré

    tas: Tas | None = None


_AGENCE_OU_AGREGATEUR = {"agence", "agregateur"}


def _points_avec_libelle(points_json: str | None) -> list[dict]:
    """EXE-162, critère 23 : le `sujet` stocké sur un point est l'id du texte
    type du répertoire — son libellé humain est résolu ici, jamais côté front
    (frontend.md : zéro logique métier dans les composants)."""
    return [
        {**p, "sujet_libelle": sujet_libelle(p.get("sujet"))}
        for p in json.loads(points_json or "[]")
    ]


def _row_to_fiche(row, company: str | None) -> dict:
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
        "points": _points_avec_libelle(row["points_json"]),
        "session_id": row["session_id"],
        "cost_usd": row["cost_usd"],
        "tools_called": json.loads(row["tools_called_json"] or "[]"),
        "api_key_source": row["api_key_source"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        # bouton « Ajouter aux intermédiaires » : recalculé à chaque lecture, jamais persisté
        "propose_intermediaire": (
            row["employeur_type_source"] in _AGENCE_OU_AGREGATEUR
            and bool(company)
            and not intermediaires.is_known(company)
        ),
    }


async def _generate(offer_id: int) -> None:
    try:
        await run_fiche(offer_id)
    finally:
        _running.discard(offer_id)
    mark_changed(offer_id)
    # Enchaînement (TCK-281) : la fiche désigne elle-même les points de la lettre
    # et la lance si elle peut partir — jamais depuis un autre déclencheur.
    await lettre_api.launch_lettre_if_ready(offer_id)


async def launch_fiche(offer_id: int) -> asyncio.Task | None:
    """Lance la génération si elle n'est pas déjà en cours ni déjà terminée —
    idempotent (critères 1, 11, 12 du ticket EXE-127). Rend la tâche créée, ou
    `None` si rien n'a été lancé."""
    if offer_id in _running:
        return None
    with get_conn() as conn:
        f = conn.execute(
            "SELECT statut FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if f is not None and f["statut"] == "done":
            return None
        reset_pending(conn, offer_id)
    _running.add(offer_id)
    task = asyncio.create_task(_generate(offer_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


@router.post("/{offer_id}/fiche", status_code=202)
async def create_fiche(offer_id: int) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="La fiche n'est produite que pour une offre retenue",
            )
        f = conn.execute(
            "SELECT statut FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if f is not None and f["statut"] == "done":
            raise HTTPException(
                status_code=409,
                detail="Fiche déjà produite : la relancer effacerait les annotations",
            )
    await launch_fiche(offer_id)
    return {"statut": "pending"}


@router.get("/{offer_id}/fiche")
def get_fiche(offer_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT f.*, o.company FROM fiches_entreprise f "
            "JOIN offers o ON o.id = f.offer_id WHERE f.offer_id = ?",
            (offer_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
    fiche = _row_to_fiche(row, row["company"])
    if fiche["statut"] == "pending" and offer_id not in _running:
        # Génération orpheline (API redémarrée en cours de route) : l'exposer comme relançable.
        fiche["statut"] = "error"
        fiche["error_message"] = (
            "Génération interrompue (API redémarrée). Relancer la fiche."
        )
    return fiche


@router.post("/{offer_id}/fiche/intermediaire", status_code=200)
def add_intermediaire(offer_id: int) -> dict:
    """Ajoute `offers.company` à `intermediaires.yaml`. N'écrit jamais depuis la génération ou le PATCH."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT company FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    company = (row["company"] or "").strip()
    if not company:
        raise HTTPException(
            status_code=409, detail="L'offre n'a pas de nom d'entreprise à ajouter"
        )
    added = intermediaires.add(company)
    return {"company": company, "added": added}


def _update_point(
    offer_id: int, point_idx: int, mutate, expect_session: str | None = None
) -> dict:
    """Read-modify-write de points_json sous verrou d'écriture (BEGIN IMMEDIATE) : pas de mise à jour perdue."""
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT points_json, session_id FROM fiches_entreprise WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Pas de fiche pour cette offre")
        if expect_session is not None and row["session_id"] != expect_session:
            raise HTTPException(
                status_code=409, detail="La fiche a été régénérée pendant l'appel"
            )
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
        for (
            field
        ) in body.model_fields_set:  # un champ explicitement null efface la valeur
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
            raise HTTPException(
                status_code=409, detail="Fiche non terminée ou sans session"
            )
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
            disallowed_tools=[
                "WebSearch",
                "WebFetch",
                "Bash",
                "Write",
                "Edit",
                "NotebookEdit",
            ],
            setting_sources=[],
            cwd=str(FICHE_CWD),
        ),
    ):
        if isinstance(msg, ResultMessage):
            if msg.is_error:
                raise HTTPException(
                    status_code=502, detail=f"SDK en erreur ({msg.subtype})"
                )
            explication = (msg.result or "").strip()
    if not explication:
        raise HTTPException(status_code=502, detail="Explication vide")

    # Écriture atomique, refusée si la fiche a été régénérée entre-temps (session_id changé).
    def mutate(point: dict) -> None:
        point["explication"] = explication

    _update_point(offer_id, point_idx, mutate, expect_session=row["session_id"])
    return explication
