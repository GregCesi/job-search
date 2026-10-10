"""Endpoints lettre de motivation : boucle tamis/rédaction/vérificateur/juge
(EXE-162), reprise/régénération/historique (EXE-66).

GET/PUT /lettre/points restent pour compatibilité (hérités d'EXE-65) : la
génération ne les lit plus depuis EXE-162 — la boucle retient elle-même un fait
de la fiche, ou part en générique.

POST déclenche la génération (action explicite, offre retenue + fiche terminée +
texte de l'offre présent — critère 3). Si une lettre est déjà `done`, POST la
rend telle quelle sans rappeler le modèle (critère 2).

PUT /lettre/texte enregistre le texte repris par l'utilisateur (calcul 100% Python,
aucun appel modèle). POST /lettre/regenerer relance la boucle sans toucher à la
version d'avant tant qu'elle n'a pas abouti. POST /lettre/ecarter écarte le fait
retenu courant et régénère aussitôt (critère 13) ; POST /lettre/remettre le remet
sans régénérer (critère 15). GET /lettre/versions rend l'historique, jamais
réécrit ni tronqué.

Enchaînement (TCK-281, EXE-127) : `launch_lettre_if_ready` est appelé par la fiche
entreprise (api/fiche.py) dès qu'elle se termine — jamais par un changement de
profil ni par un rescore.

Modèle (EXE-166) : POST /lettre, /lettre/regenerer et /lettre/ecarter acceptent un
corps optionnel `{"modele": "sonnet"|"opus"}` ; absent, sonnet. Un autre modèle est
refusé (422) avant tout appel — `launch_lettre_if_ready` tourne toujours sur sonnet,
quel que soit le choix fait ailleurs (critère 4).
"""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

import orchestrator.job_search.lettre.service as lettre_service
from orchestrator.job_search.avancement import ProgressionLettre
from orchestrator.job_search.lettre.redaction import (
    blocage_lancement_lettre,
    point_text,
    resolve_chosen_indices,
    resolve_offer_text,
)
from orchestrator.job_search.lettre.repertoire import sujet_libelle
from orchestrator.job_search.lettre.service import reset_pending, run_lettre
from orchestrator.job_search.pdf.coordonnees import (
    Coordonnees,
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

# EXE-167, H3 : l'étape en cours vit dans la mémoire du processus, jamais en
# base — posée au lancement, retirée dès que la génération/régénération finit.
_progression: dict[int, ProgressionLettre] = {}


def is_running(offer_id: int) -> bool:
    return offer_id in _running


def running_offer_ids() -> set[int]:
    return set(_running)


def progression_lettre(offer_id: int) -> dict | None:
    """Étape en cours (EXE-167, critère 2) — None hors génération/régénération
    (critère 4), même si une entrée orpheline subsiste encore en mémoire."""
    if offer_id not in _running:
        return None
    tracker = _progression.get(offer_id)
    return tracker.as_dict() if tracker is not None else None


def _on_etape(offer_id: int) -> Callable[[dict], None]:
    tracker = _progression.setdefault(offer_id, ProgressionLettre())

    def _callback(signal: dict) -> None:
        tracker.signaler(signal)

    return _callback


class PointsChoisisIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indices: list[int]


class LettreTexteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: str


class FaitEcarteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation: str | None = None
    url: str | None = None


class ModeleLettreIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modele: str = lettre_service.MODELE_PAR_DEFAUT


def _modele_choisi(body: ModeleLettreIn | None) -> str:
    """Résout et valide le modèle demandé (EXE-166, critères 1-3) — refuse avant
    tout appel de modèle, avant toute autre mutation, avec les deux choix
    possibles dans le message."""
    modele = body.modele if body is not None else lettre_service.MODELE_PAR_DEFAUT
    try:
        lettre_service.valider_modele(modele)
    except lettre_service.ModeleInvalideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return modele


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


def _fait_retenu(row) -> dict | None:
    if not row["fait_retenu_json"]:
        return None
    fait = json.loads(row["fait_retenu_json"])
    return {**fait, "sujet_libelle": sujet_libelle(fait.get("sujet"))}


def _row_to_lettre(row, offer_id: int) -> dict:
    return {
        "statut": row["statut"],
        "texte": row["texte"],
        "tournures_signalees": json.loads(row["tournures_signalees_json"] or "[]"),
        "nb_mots": row["nb_mots"],
        "depasse_longueur": bool(row["depasse_longueur"]),
        "modele": row["modele"],
        "modele_juge": row["modele_juge"],
        "cost_usd": row["cost_usd"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "regeneration_en_cours": bool(row["regeneration_en_cours"]),
        "regeneration_error": row["regeneration_error"],
        "points_choisis_origine": row["points_choisis_origine"],
        "fait_retenu": _fait_retenu(row),
        "texte_type_id": row["texte_type_id"],
        "nb_tours": row["nb_tours"],
        "raison_fin": row["raison_fin"],
        "jugement": json.loads(row["jugement_json"]) if row["jugement_json"] else None,
        "releve": json.loads(row["releve_json"]) if row["releve_json"] else None,
        "faits_ecartes": json.loads(row["faits_ecartes_json"] or "[]"),
        # EXE-167, critères 2, 4 : étape de la boucle en cours — None hors
        # génération/régénération.
        "etape": progression_lettre(offer_id),
    }


async def _generate(offer_id: int, modele: str) -> None:
    try:
        await run_lettre(offer_id, modele, on_etape=_on_etape(offer_id))
    finally:
        _running.discard(offer_id)
        _progression.pop(offer_id, None)
    mark_changed(offer_id)


async def launch_lettre(
    offer_id: int, modele: str = lettre_service.MODELE_PAR_DEFAUT
) -> asyncio.Task | None:
    """Lance la génération si elle n'est pas déjà en cours ni déjà terminée —
    idempotent (critères 2, 11, 12 du ticket EXE-127), sur le modèle choisi
    (sonnet par défaut — EXE-166). Rend la tâche créée, ou `None` si rien n'a
    été lancé. N'effectue aucune des gardes de lancement (fiche terminée, texte
    présent, point choisi) : c'est à l'appelant de les avoir vérifiées (route
    POST, ou `launch_lettre_if_ready`)."""
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
    task = asyncio.create_task(_generate(offer_id, modele))
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
    """Enchaîné dès que la fiche entreprise se termine (TCK-281) : lance si les
    deux gardes (fiche terminée, texte présent — critère 3 d'EXE-162) sont
    satisfaites. La désignation de points ci-dessous est héritée (EXE-132) :
    elle n'est plus lue par la génération depuis EXE-162, mais reste écrite pour
    ne jamais remplacer un choix que j'ai fait (`points_choisis_origine == 'moi'`)."""
    with get_conn() as conn:
        fiche_statut, points = _fiche_statut_et_points(conn, offer_id)

        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is not None and row["statut"] == "done":
            return None

        if points and (row is None or row["points_choisis_origine"] != "moi"):
            designated = [i for i, p in enumerate(points) if p.get("pour_lettre")]
            conn.execute(
                """
                INSERT INTO lettres
                    (offer_id, statut, points_choisis_json, points_choisis_origine, created_at)
                VALUES (?, 'aucune', ?, 'systeme', ?)
                ON CONFLICT(offer_id) DO UPDATE SET
                    points_choisis_json=excluded.points_choisis_json,
                    points_choisis_origine='systeme'
                """,
                (offer_id, json.dumps(designated), _now()),
            )
            conn.commit()

        offer_text = _offer_text(conn, offer_id)
        if blocage_lancement_lettre(fiche_statut, offer_text) is not None:
            return None

    # Critère 4 : l'enchaînement automatique tourne toujours sur sonnet, quel
    # que soit le modèle choisi ailleurs pour une génération ou régénération.
    return await launch_lettre(offer_id, lettre_service.MODELE_PAR_DEFAUT)


@router.post("/{offer_id}/lettre")
async def create_lettre(
    offer_id: int, response: Response, body: ModeleLettreIn | None = None
) -> dict:
    modele = _modele_choisi(body)
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
            return _row_to_lettre(row, offer_id)

        fiche_statut, _points = _fiche_statut_et_points(conn, offer_id)
        offer_text = _offer_text(conn, offer_id)
        blocage = blocage_lancement_lettre(fiche_statut, offer_text)
        if blocage is not None:
            raise HTTPException(status_code=409, detail=blocage)
    await launch_lettre(offer_id, modele)
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
    lettre = _row_to_lettre(row, offer_id)
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
    return _row_to_lettre(row, offer_id)


async def _regenerate(offer_id: int, modele: str) -> None:
    try:
        await lettre_service.run_lettre_regenerate(
            offer_id, modele, on_etape=_on_etape(offer_id)
        )
    finally:
        _running.discard(offer_id)
        _progression.pop(offer_id, None)
    mark_changed(offer_id)


def _launch_regeneration(offer_id: int, modele: str) -> None:
    if offer_id not in _running:
        _running.add(offer_id)
        task = asyncio.create_task(_regenerate(offer_id, modele))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


@router.post("/{offer_id}/lettre/regenerer")
async def regenerer_lettre(
    offer_id: int, response: Response, body: ModeleLettreIn | None = None
) -> dict:
    modele = _modele_choisi(body)
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
    _launch_regeneration(offer_id, modele)
    response.status_code = 202
    return {"regeneration_en_cours": True}


@router.post("/{offer_id}/lettre/ecarter")
async def ecarter_fait(
    offer_id: int, response: Response, body: ModeleLettreIn | None = None
) -> dict:
    """Écarte le fait retenu courant de la lettre et régénère aussitôt (EXE-162,
    critère 13), sur le modèle choisi (sonnet par défaut — EXE-166). Refuse avec
    une raison lisible si la lettre est générique ou n'existe pas encore
    (critère 17)."""
    modele = _modele_choisi(body)
    with get_conn() as conn:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="La lettre n'est régénérée que pour une offre retenue",
            )
        try:
            lettre_service.ajouter_fait_ecarte(conn, offer_id)
        except lettre_service.RienAEcarterError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if offer_id not in _running:
            lettre_service.mark_regenerating(conn, offer_id)
    _launch_regeneration(offer_id, modele)
    response.status_code = 202
    return {"regeneration_en_cours": True}


@router.post("/{offer_id}/lettre/remettre")
def remettre_fait(offer_id: int, body: FaitEcarteIn) -> dict:
    """Remet un fait écarté, sans régénérer (EXE-162, critère 15)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail="Pas de lettre pour cette offre"
            )
        lettre_service.retirer_fait_ecarte(conn, offer_id, body.citation, body.url)
        row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return _row_to_lettre(row, offer_id)


def _lettre_page_ingredients(conn, offer_id: int) -> tuple[Coordonnees, str, str]:
    """Coordonnées, intitulé et texte nécessaires à la page de la lettre — gabarit
    partagé par le PDF et son aperçu HTML (EXE-129) : mêmes refus, même phrase,
    même ordre pour les deux."""
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
    offer = conn.execute(
        "SELECT title FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    intitule = offer["title"] if offer else ""
    return coordonnees, intitule, row["texte"]


@router.get("/{offer_id}/lettre/pdf")
def get_lettre_pdf(offer_id: int) -> Response:
    """PDF téléchargeable de la lettre d'une offre retenue (EXE-102) — mise en
    page du texte stocké tel quel, jamais corrigé ; aucun appel modèle (critère 17)."""
    with get_conn() as conn:
        coordonnees, intitule, texte = _lettre_page_ingredients(conn, offer_id)
        filename = resolve_piece_filename(conn, offer_id, "Lettre", coordonnees)
    html = build_lettre_html(coordonnees, intitule, texte)
    pdf_bytes = html_to_pdf(html)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{offer_id}/lettre/mise-en-page")
def get_lettre_mise_en_page(offer_id: int) -> Response:
    """Page HTML de la lettre d'une offre retenue, mise en page comme son PDF
    (EXE-129) : c'est la page dont le PDF est tiré, servie telle quelle plutôt
    que convertie. Mêmes refus que le PDF, même phrase (critères 1 à 4)."""
    with get_conn() as conn:
        coordonnees, intitule, texte = _lettre_page_ingredients(conn, offer_id)
    html = build_lettre_html(coordonnees, intitule, texte)
    return Response(content=html, media_type="text/html")


@router.get("/{offer_id}/lettre/versions")
def get_lettre_versions(offer_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT texte, tournures_signalees_json, nb_mots, depasse_longueur, "
            "origine, fait_retenu_json, created_at, modele, modele_juge, "
            "jugement_json, nb_tours, raison_fin FROM lettre_versions "
            "WHERE offer_id = ? ORDER BY id ASC",
            (offer_id,),
        ).fetchall()
    return [
        {
            "texte": r["texte"],
            "tournures_signalees": json.loads(r["tournures_signalees_json"] or "[]"),
            "nb_mots": r["nb_mots"],
            "depasse_longueur": bool(r["depasse_longueur"]),
            "origine": r["origine"],
            "fait_retenu": json.loads(r["fait_retenu_json"])
            if r["fait_retenu_json"]
            else None,
            "created_at": r["created_at"],
            "modele": r["modele"],
            "modele_juge": r["modele_juge"],
            "jugement": json.loads(r["jugement_json"]) if r["jugement_json"] else None,
            "nb_tours": r["nb_tours"],
            "raison_fin": r["raison_fin"],
        }
        for r in rows
    ]
