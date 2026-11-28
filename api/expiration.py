"""Vérification d'expiration des offres retenues (EXE-76) et, sur désignation
explicite, de n'importe quelle offre affichée dans un onglet de la vue
candidat (EXE-78), avec la lecture de leur parcours de candidature (EXE-217).

L'URL employeur se saisit à la main. La vérification part de deux endroits, et
d'aucun autre : cette route, POST /offers/check-expirations, et la fin d'un run,
pour les offres des files « À postuler » et « À étudier », qui lance la même
vérification (EXE-217, H7). Jamais le rescore, un changement de profil, le
démarrage de l'API ni l'affichage d'une file. La logique de vérification vit dans
`orchestrator.job_search.expiration.service` ; cette route ne fait que le
garde-fou "offre retenue" (URL employeur), la résolution des offres désignées,
et la persistance de l'URL employeur. GET /offers/{id}/parcours rend le parcours
lu, sans rien lire.

Le corps {"tout": true} vérifie le périmètre de la fin du run : les lignes des
deux files, leurs jumelles et les candidatures en cours (EXE-223).
"""

from fastapi import APIRouter, HTTPException

from orchestrator.job_search.expiration.fin_de_run import ids_a_verifier
from orchestrator.job_search.expiration.service import run_expiration_check
from orchestrator.job_search.parcours.service import parcours_de
from orchestrator.job_search.suivi import storage as suivi_storage

from .a_postuler import classement_des_files
from .db import get_conn
from .schemas import CheckExpirationsIn, EmployerUrlIn

router = APIRouter(prefix="/offers")


@router.put("/{offer_id}/employer-url", status_code=204)
def set_employer_url(offer_id: int, body: EmployerUrlIn) -> None:
    conn = get_conn()
    try:
        if not suivi_storage.est_retenue(conn, offer_id):
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
def check_expirations(body: CheckExpirationsIn | None = None) -> None:
    if body is not None and body.tout:
        _verifier_tout()
        return
    offer_ids = body.offer_ids if body is not None else None
    conn = get_conn()
    try:
        if offer_ids is not None:
            existing_ids: set[int] = set()
            if offer_ids:
                placeholders = ",".join("?" for _ in offer_ids)
                rows = conn.execute(
                    f"SELECT id FROM offers WHERE id IN ({placeholders})",
                    offer_ids,
                ).fetchall()
                existing_ids = {r["id"] for r in rows}
            missing = [oid for oid in offer_ids if oid not in existing_ids]
            if missing:
                raise HTTPException(
                    status_code=404,
                    detail=f"Offre(s) introuvable(s) : {missing}",
                )
        run_expiration_check(conn, offer_ids=offer_ids)
    finally:
        conn.close()


def _verifier_tout() -> None:
    """Le corps {"tout": true} (EXE-223, H3) : le périmètre de la fin du run."""
    classement, _ = classement_des_files()
    conn = get_conn()
    try:
        run_expiration_check(conn, offer_ids=ids_a_verifier(conn, classement))
    finally:
        conn.close()


@router.get("/{offer_id}/parcours")
def get_parcours(offer_id: int) -> dict:
    """Le parcours de candidature gardé pour l'offre (EXE-217, H5). Ne lit rien."""
    conn = get_conn()
    try:
        rendu = parcours_de(conn, offer_id)
    finally:
        conn.close()
    if rendu is None:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return rendu
