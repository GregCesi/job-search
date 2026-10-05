"""Endpoints lettre de motivation (EXE-65) et reprise/régénération/historique (EXE-66).

Le choix des points est stocké avec la lettre, jamais dans la fiche entreprise
(architecture.md, exceptions encadrées) : PUT /lettre/points ne touche jamais
`fiches_entreprise.points_json`.

POST déclenche la génération (action explicite, offre retenue + fiche terminée +
au moins un point choisi — critères 3, 4, 8). Si une lettre est déjà `done`, POST la
rend telle quelle sans rappeler le modèle (critère 2).

PUT /lettre/texte enregistre le texte repris par l'utilisateur (calcul 100% Python,
aucun appel modèle). POST /lettre/regenerer relance le modèle depuis le choix de
points courant sans toucher à la version d'avant tant qu'elle n'a pas abouti.
GET /lettre/versions rend l'historique, jamais réécrit ni tronqué.

Enchaînement (TCK-281, EXE-127) : `launch_lettre_if_ready` est appelé par la fiche
entreprise (api/fiche.py) dès qu'elle se termine — jamais par un changement de
profil ni par un rescore. Il désigne lui-même les points (tous ceux de la fiche)
si je n'en ai jamais choisi à la main, sans jamais remplacer un choix que j'ai
fait (`points_choisis_origine`).
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

import orchestrator.job_search.lettre.service as lettre_service
from orchestrator.job_search.lettre.redaction import (
    blocage_lancement_lettre,
    point_text,
    resolve_chosen_indices,
    resolve_offer_text,
)
from orchestrator.job_search.lettre.service import reset_pending, run_lettre
from orchestrator.job_search.pdf.coordonnees import (
    CoordonneesManquantesError,
    load_coordonnees,
)
from orchestrator.job_search.pdf.filename import resolve_piece_filename
from orchestrator.job_search.pdf.lettre_html import build_lettre_html
from orchestrator.job_search.pdf.render import html_to_pdf
from orchestrator.job_search.pieces_state import mark_changed

from .db import get_conn

router = APIRouter(prefix="/offers")

# Références fortes sur les tâches de fond (l'event loop ne garde que des références faibles).
_tasks: set[asyncio.Task] = set()
_running: set[int] = set()


def is_running(offer_id: int) -> bool:
    return offer_id in _running


def running_offer_ids() -> set[int]:
    return set(_running)


class PointsChoisisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indices: list[int]


class LettreTexteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: str


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
            INSERT INTO lettres (offer_id, statut, points_choisis_json, points_choisis_origine, created_at)
            VALUES (?, 'aucune', ?, 'moi', ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                points_choisis_json=excluded.points_choisis_json,
                points_choisis_origine='moi'
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
        "regeneration_en_cours": bool(row["regeneration_en_cours"]),
        "regeneration_error": row["regeneration_error"],
        "points_choisis_origine": row["points_choisis_origine"],
    }


async def _generate(offer_id: int) -> None:
    try:
        await run_lettre(offer_id)
    finally:
        _running.discard(offer_id)
    mark_changed(offer_id)


async def launch_lettre(offer_id: int) -> asyncio.Task | None:
    """Lance la génération si elle n'est pas déjà en cours ni déjà terminée —
    idempotent (critères 2, 11, 12 du ticket EXE-127). Rend la tâche créée, ou
    `None` si rien n'a été lancé. N'effectue aucune des gardes de lancement
    (fiche terminée, texte présent, point choisi) : c'est à l'appelant de les
    avoir vérifiées (route POST, ou `launch_lettre_if_ready`)."""
    if offer_id in _running:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT statut FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            return None
        reset_pending(conn, offer_id)
    _running.add(offer_id)
    task = asyncio.create_task(_generate(offer_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def _fiche_statut_et_points(conn, offer_id: int) -> tuple[str | None, list[dict]]:
    row = conn.execute(
        "SELECT statut, points_json FROM fiches_entreprise WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    if row is None:
        return None, []
    return row["statut"], json.loads(row["points_json"] or "[]")


def _offer_text(conn, offer_id: int) -> str:
    row = conn.execute(
        "SELECT description_raw, description FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    return resolve_offer_text(
        row["description_raw"] if row else None, row["description"] if row else None
    )


async def launch_lettre_if_ready(offer_id: int) -> asyncio.Task | None:
    """Enchaîné dès que la fiche entreprise se termine (TCK-281) : désigne tous
    ses points pour la lettre si je n'en ai jamais choisi à la main, puis lance
    si les trois gardes (fiche terminée, texte présent, au moins un point) sont
    satisfaites. Ne remplace jamais un choix que j'ai fait (`points_choisis_origine
    == 'moi'`) — critère « ne doit pas arriver » du ticket."""
    with get_conn() as conn:
        fiche_statut, points = _fiche_statut_et_points(conn, offer_id)

        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            return None

        if points and (row is None or row["points_choisis_origine"] != "moi"):
            conn.execute(
                """
                INSERT INTO lettres
                    (offer_id, statut, points_choisis_json, points_choisis_origine, created_at)
                VALUES (?, 'aucune', ?, 'systeme', ?)
                ON CONFLICT(offer_id) DO UPDATE SET
                    points_choisis_json=excluded.points_choisis_json,
                    points_choisis_origine='systeme'
                """,
                (offer_id, json.dumps(list(range(len(points)))), _now()),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
            ).fetchone()

        offer_text = _offer_text(conn, offer_id)
        chosen = resolve_chosen_indices(
            points, row["points_choisis_json"] if row is not None else None
        )
        if blocage_lancement_lettre(fiche_statut, offer_text, chosen) is not None:
            return None

    return await launch_lettre(offer_id)


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
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            response.status_code = 200
            return _row_to_lettre(row)

        fiche_statut, points = _fiche_statut_et_points(conn, offer_id)
        offer_text = _offer_text(conn, offer_id)
        chosen = resolve_chosen_indices(
            points, row["points_choisis_json"] if row is not None else None
        )
        blocage = blocage_lancement_lettre(fiche_statut, offer_text, chosen)
        if blocage is not None:
            raise HTTPException(status_code=409, detail=blocage)
    await launch_lettre(offer_id)
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


@router.put("/{offer_id}/lettre/texte")
def put_lettre_texte(offer_id: int, body: LettreTexteIn) -> dict:
    with get_conn() as conn:
        try:
            lettre_service.save_texte(conn, offer_id, body.texte)
        except lettre_service.LettreNonPreteError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return _row_to_lettre(row)


async def _regenerate(offer_id: int) -> None:
    try:
        await lettre_service.run_lettre_regenerate(offer_id)
    finally:
        _running.discard(offer_id)
    mark_changed(offer_id)


@router.post("/{offer_id}/lettre/regenerer")
async def regenerer_lettre(offer_id: int, response: Response) -> dict:
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="La lettre n'est régénérée que pour une offre retenue",
            )
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is None or row["statut"] != "done":
            raise HTTPException(
                status_code=409,
                detail="Pas de lettre prête à régénérer pour cette offre",
            )
        if offer_id not in _running:
            lettre_service.mark_regenerating(conn, offer_id)
    if offer_id not in _running:
        _running.add(offer_id)
        task = asyncio.create_task(_regenerate(offer_id))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
    response.status_code = 202
    return {"regeneration_en_cours": True}


@router.get("/{offer_id}/lettre/pdf")
def get_lettre_pdf(offer_id: int) -> Response:
    """PDF téléchargeable de la lettre d'une offre retenue (EXE-102) — mise en
    page du texte stocké tel quel, jamais corrigé ; aucun appel modèle (critère 17)."""
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
            "SELECT texte FROM lettres WHERE offer_id = ? AND statut = 'done'",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=409, detail="La lettre n'est pas générée pour cette offre"
            )
        try:
            coordonnees = load_coordonnees()
        except CoordonneesManquantesError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        filename = resolve_piece_filename(conn, offer_id, "Lettre", coordonnees)
        offer = conn.execute(
            "SELECT title FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
    intitule = offer["title"] if offer else ""
    html = build_lettre_html(coordonnees, intitule, row["texte"])
    pdf_bytes = html_to_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{offer_id}/lettre/versions")
def get_lettre_versions(offer_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT texte, tournures_signalees_json, nb_mots, depasse_longueur, "
            "origine, created_at FROM lettre_versions WHERE offer_id = ? ORDER BY id ASC",
            (offer_id,),
        ).fetchall()
    return [
        {
            "texte": r["texte"],
            "tournures_signalees": json.loads(r["tournures_signalees_json"] or "[]"),
            "nb_mots": r["nb_mots"],
            "depasse_longueur": bool(r["depasse_longueur"]),
            "origine": r["origine"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
