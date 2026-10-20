"""Statut de pièce (CV / lettre) d'une offre retenue (EXE-101).

Lecture agrégée (`GET /pieces`) et marque humaine (`PUT /cv/pret`,
`PUT /lettre/pret`) — jamais l'inverse : une pièce ne devient jamais Prête
sans cette marque explicite, ni à la fin d'une génération ni par un calcul
de l'app (architecture.md). Marquer ou démarquer ne touche jamais au
contenu de la pièce : seule la colonne `marque_pret_at` est écrite ici.

`PUT /envoyee` (EXE-139) marque la candidature comme envoyée — passe par le
geste `marquer_envoyee` du module d'états (TCK-311, EXE-193), seulement si les
deux pièces sont Prêtes ; `envoyee=false` annule ce dernier geste. Ne touche
jamais au statut des pièces : une candidature envoyée le reste si une pièce
cesse ensuite d'être Prête.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.pieces import (
    cv_statut,
    lettre_statut,
    prete_a_l_envoi,
)
from orchestrator.job_search.suivi import etats
from orchestrator.job_search.suivi import storage as suivi_storage

from .db import get_conn

router = APIRouter(prefix="/offers")


class MarquePretIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pret: bool


class MarqueEnvoyeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envoyee: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_retenue(conn, offer_id: int) -> None:
    if not suivi_storage.est_retenue(conn, offer_id):
        raise HTTPException(
            status_code=409,
            detail="Le statut des pièces n'est disponible que pour une offre retenue",
        )


def _piece_payload(statut: str, marque_pret_le: str | None) -> dict:
    return {"statut": statut, "marque_pret_le": marque_pret_le}


@router.get("/{offer_id}/pieces")
def get_pieces(offer_id: int) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        cv_row = conn.execute(
            "SELECT statut, marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        lettre_row = conn.execute(
            "SELECT statut, marque_pret_at FROM lettres WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        envoyee_le = suivi_storage.date_envoyee(conn, offer_id)
    cv_s = cv_statut(cv_row)
    lettre_s = lettre_statut(lettre_row)
    return {
        "cv": _piece_payload(cv_s, cv_row["marque_pret_at"] if cv_row else None),
        "lettre": _piece_payload(
            lettre_s, lettre_row["marque_pret_at"] if lettre_row else None
        ),
        "prete_a_l_envoi": prete_a_l_envoi(cv_s, lettre_s),
        "envoyee_le": envoyee_le,
    }


@router.put("/{offer_id}/envoyee")
def set_envoyee(offer_id: int, body: MarqueEnvoyeeIn) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        if body.envoyee:
            try:
                suivi_storage.appliquer_geste(conn, offer_id, etats.MARQUER_ENVOYEE)
            except etats.PiecesNonPretes as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except etats.GesteRefuse:
                pass  # déjà à l'étape candidature envoyée (ou au-delà) : rien à refaire
        elif suivi_storage.etat_stocke(conn, offer_id) == etats.CANDIDATURE_ENVOYEE:
            hist = suivi_storage.historique(conn, offer_id)
            dernier = etats.dernier_geste_non_annule(hist)
            if dernier is not None and dernier.geste == etats.MARQUER_ENVOYEE:
                suivi_storage.annuler_dernier_geste(conn, offer_id)
            # sinon : la candidature envoyée vient d'ailleurs (reprise, étape
            # ultérieure défaite) — rien à annuler ici, idempotent.
        envoyee_le = suivi_storage.date_envoyee(conn, offer_id)
    return {"envoyee_le": envoyee_le}


@router.put("/{offer_id}/cv/pret")
def set_cv_pret(offer_id: int, body: MarquePretIn) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        row = conn.execute(
            "SELECT statut, marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if body.pret:
            if row is None or row["statut"] != "done":
                raise HTTPException(
                    status_code=409,
                    detail="Le CV n'est pas terminé, impossible de le marquer prêt",
                )
            conn.execute(
                "UPDATE cvs SET marque_pret_at = ? WHERE offer_id = ?",
                (_now(), offer_id),
            )
        else:
            conn.execute(
                "UPDATE cvs SET marque_pret_at = NULL WHERE offer_id = ?", (offer_id,)
            )
        conn.commit()
        row = conn.execute(
            "SELECT statut, marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return _piece_payload(cv_statut(row), row["marque_pret_at"])


@router.put("/{offer_id}/lettre/pret")
def set_lettre_pret(offer_id: int, body: MarquePretIn) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        row = conn.execute(
            "SELECT statut, marque_pret_at, regeneration_en_cours FROM lettres "
            "WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        if body.pret:
            if row is None or row["statut"] != "done" or row["regeneration_en_cours"]:
                raise HTTPException(
                    status_code=409,
                    detail="La lettre n'est pas terminée, impossible de la marquer prête",
                )
            conn.execute(
                "UPDATE lettres SET marque_pret_at = ? WHERE offer_id = ?",
                (_now(), offer_id),
            )
        else:
            conn.execute(
                "UPDATE lettres SET marque_pret_at = NULL WHERE offer_id = ?",
                (offer_id,),
            )
        conn.commit()
        row = conn.execute(
            "SELECT statut, marque_pret_at FROM lettres WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
    return _piece_payload(lettre_statut(row), row["marque_pret_at"])
