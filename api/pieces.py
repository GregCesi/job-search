"""Statut de pièce (CV / lettre) d'une offre retenue (EXE-101).

Lecture agrégée (`GET /pieces`) et marque humaine (`PUT /cv/pret`,
`PUT /lettre/pret`) — jamais l'inverse : une pièce ne devient jamais Prête
sans cette marque explicite, ni à la fin d'une génération ni par un calcul
de l'app (architecture.md). Marquer ou démarquer ne touche jamais au
contenu de la pièce : seule la colonne `marque_pret_at` est écrite ici.

`PUT /envoyee` (EXE-139) marque la candidature comme envoyée — seule marque
humaine possible, sur `verdicts.envoyee_at`, et seulement si les deux pièces
sont Prêtes. Ne touche ni au statut des pièces ni au verdict de l'offre : une
candidature envoyée le reste si une pièce cesse ensuite d'être Prête.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.pieces import (
    PRETE,
    cv_statut,
    lettre_statut,
    prete_a_l_envoi,
)

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
    v = conn.execute(
        "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if v is None or v["status"] != "retenu":
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
        verdict_row = conn.execute(
            "SELECT envoyee_at FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    cv_s = cv_statut(cv_row)
    lettre_s = lettre_statut(lettre_row)
    return {
        "cv": _piece_payload(cv_s, cv_row["marque_pret_at"] if cv_row else None),
        "lettre": _piece_payload(
            lettre_s, lettre_row["marque_pret_at"] if lettre_row else None
        ),
        "prete_a_l_envoi": prete_a_l_envoi(cv_s, lettre_s),
        "envoyee_le": verdict_row["envoyee_at"] if verdict_row else None,
    }


@router.put("/{offer_id}/envoyee")
def set_envoyee(offer_id: int, body: MarqueEnvoyeeIn) -> dict:
    with get_conn() as conn:
        _check_retenue(conn, offer_id)
        if body.envoyee:
            cv_row = conn.execute(
                "SELECT statut, marque_pret_at FROM cvs WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
            lettre_row = conn.execute(
                "SELECT statut, marque_pret_at FROM lettres WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
            cv_s = cv_statut(cv_row)
            lettre_s = lettre_statut(lettre_row)
            if not prete_a_l_envoi(cv_s, lettre_s):
                cv_manque = cv_s != PRETE
                lettre_manque = lettre_s != PRETE
                if cv_manque and lettre_manque:
                    quoi = "Le CV et la lettre ne sont pas prêts"
                elif cv_manque:
                    quoi = "Le CV n'est pas prêt"
                else:
                    quoi = "La lettre n'est pas prête"
                raise HTTPException(
                    status_code=409,
                    detail=f"{quoi} : impossible de marquer la candidature envoyée",
                )
            row = conn.execute(
                "SELECT envoyee_at FROM verdicts WHERE offer_id = ?", (offer_id,)
            ).fetchone()
            if row["envoyee_at"] is None:
                conn.execute(
                    "UPDATE verdicts SET envoyee_at = ? WHERE offer_id = ?",
                    (_now(), offer_id),
                )
        else:
            conn.execute(
                "UPDATE verdicts SET envoyee_at = NULL WHERE offer_id = ?", (offer_id,)
            )
        conn.commit()
        row = conn.execute(
            "SELECT envoyee_at FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    return {"envoyee_le": row["envoyee_at"]}


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
