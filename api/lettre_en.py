"""Version anglaise de la lettre (EXE-209).

POST /lettre/en traduit le texte français courant : un seul appel de modèle
(Sonnet, claude-agent-sdk, sans outil), parti uniquement du clic sur « Générer »
ou « Régénérer la version anglaise » d'une offre retenue (H2 du ticket). La
connexion à la base est fermée pendant l'appel.

GET /lettre/en rend l'état de la carte (bouton, fraîcheur, texte) calculé côté
Python ; PUT /lettre/en/texte enregistre ma correction. GET /lettre/en/pdf et
/lettre/en/mise-en-page rendent la page anglaise, mêmes refus que la française.

Rien ici n'écrit dans `lettres`, `lettre_versions` ni `offers`.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.lettre_en import stockage, traduction
from orchestrator.job_search.lettre_en.carte import carte_anglaise
from orchestrator.job_search.pdf.coordonnees import Coordonnees
from orchestrator.job_search.pdf.filename import resolve_piece_filename
from orchestrator.job_search.pdf.lettre_html import build_lettre_html
from orchestrator.job_search.pdf.render import html_to_pdf
from orchestrator.job_search.suivi import storage as suivi_storage

from .db import get_conn
from .lettre import _lettre_page_ingredients

router = APIRouter(prefix="/offers")


class LettreEnTexteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texte: str


def _carte(conn, offer_id: int) -> dict:
    return carte_anglaise(
        stockage.texte_fr_courant(conn, offer_id), stockage.lire(conn, offer_id)
    )


@router.get("/{offer_id}/lettre/en")
def get_lettre_en(offer_id: int) -> dict:
    with get_conn() as conn:
        return _carte(conn, offer_id)


@router.post("/{offer_id}/lettre/en")
async def generer_lettre_en(offer_id: int) -> dict:
    conn = get_conn()
    try:
        if not suivi_storage.est_retenue(conn, offer_id):
            raise HTTPException(
                status_code=409,
                detail="La version anglaise n'est produite que pour une offre retenue",
            )
        texte_fr = stockage.texte_fr_courant(conn, offer_id)
    finally:
        conn.close()
    if texte_fr is None:
        raise HTTPException(
            status_code=409, detail="La lettre n'est pas générée pour cette offre"
        )

    try:
        resultat = await traduction.traduire(texte_fr)
    except traduction.TraductionEchoueeError as exc:
        raise HTTPException(
            status_code=502, detail=f"La traduction a échoué : {exc}"
        ) from exc

    with get_conn() as conn:
        stockage.persister_traduction(conn, offer_id, texte_fr, resultat)
        return _carte(conn, offer_id)


@router.put("/{offer_id}/lettre/en/texte")
def put_lettre_en_texte(offer_id: int, body: LettreEnTexteIn) -> dict:
    with get_conn() as conn:
        try:
            stockage.enregistrer_texte(conn, offer_id, body.texte)
        except stockage.PasDeVersionAnglaiseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _carte(conn, offer_id)


def _page_anglaise(conn, offer_id: int) -> tuple[str, Coordonnees]:
    coordonnees, intitule, _texte_fr, entreprise, location = _lettre_page_ingredients(
        conn, offer_id
    )
    version = stockage.lire(conn, offer_id)
    if version is None:
        raise HTTPException(
            status_code=409, detail=str(stockage.PasDeVersionAnglaiseError())
        )
    html = build_lettre_html(
        coordonnees, intitule, version["texte"], entreprise, location, langue="en"
    )
    return html, coordonnees


@router.get("/{offer_id}/lettre/en/pdf")
def get_lettre_en_pdf(offer_id: int) -> Response:
    """PDF de la version anglaise : même nom de fichier que le français, avec
    `_EN` juste avant `.pdf`, comme le CV anglais (EXE-183)."""
    with get_conn() as conn:
        html, coordonnees = _page_anglaise(conn, offer_id)
        filename = resolve_piece_filename(conn, offer_id, "Lettre", coordonnees)
    filename = filename[:-4] + "_EN.pdf"
    return Response(
        content=html_to_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{offer_id}/lettre/en/mise-en-page")
def get_lettre_en_mise_en_page(offer_id: int) -> Response:
    with get_conn() as conn:
        html, _coordonnees = _page_anglaise(conn, offer_id)
    return Response(content=html, media_type="text/html")
