"""Vérification d'expiration des offres retenues (EXE-76).

URL employeur (saisie manuelle) et lancement de la vérification : deux actions
explicites, jamais déclenchées par l'ingestion, le rescore ou un changement de
profil. La logique de vérification vit dans
`orchestrator.job_search.expiration.service` ; cette route ne fait que le
garde-fou "offre retenue" et la persistance de l'URL employeur.
"""

from fastapi import APIRouter, HTTPException

from orchestrator.job_search.expiration.service import run_expiration_check

from .db import get_conn
from .schemas import EmployerUrlIn

router = APIRouter(prefix="/offers")


@router.put("/{offer_id}/employer-url", status_code=204)
def set_employer_url(offer_id: int, body: EmployerUrlIn) -> None:
    conn = get_conn()
    try:
        v = conn.execute(
            "SELECT status FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if v is None or v["status"] != "retenu":
            raise HTTPException(
                status_code=409,
                detail="L'URL employeur n'est enregistrée que pour une offre retenue",
            )

        url = body.url.strip()
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=422,
                detail="L'URL doit commencer par http:// ou https://",
            )

        existing = conn.execute(
            "SELECT id FROM expirations WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE expirations SET employer_url = ? WHERE offer_id = ?",
                (url or None, offer_id),
            )
        else:
            conn.execute(
                "INSERT INTO expirations (offer_id, employer_url, expired) VALUES (?, ?, 0)",
                (offer_id, url or None),
            )
        conn.commit()
    finally:
        conn.close()


@router.post("/check-expirations", status_code=204)
def check_expirations() -> None:
    conn = get_conn()
    try:
        run_expiration_check(conn)
    finally:
        conn.close()
