"""Endpoint du mail de candidature d'une offre retenue (EXE-103, EXE-176).

GET rend le mail courant : généré depuis la lettre ou écrit à la main s'il y en
a un (table `mails`), sinon le gabarit statique comme avant EXE-176 (critère 10).
POST /mail/generer appelle le modèle une fois (Sonnet), à partir de la lettre
courante — action explicite, jamais un recalcul déclenché par un changement de
profil ni un rescore (architecture.md). PUT /mail enregistre une version écrite
à la main, qui remplace la précédente quelle que soit son origine (critères 7,
8, 11).
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from orchestrator.job_search.mail.candidature import (
    GabaritAbsentError,
    RepereInconnuError,
    load_gabarit,
    load_gabarit_sans_lettre,
    render_mail_candidature,
)
from orchestrator.job_search.mail.generation import (
    ConsigneAbsenteError,
    ReponseIncompleteError,
    enregistrer_manuel,
    generer_depuis_lettre,
    get_appel,
    get_mail,
    persister_generation,
)
from orchestrator.job_search.pdf.coordonnees import (
    CoordonneesManquantesError,
    load_coordonnees,
)
from orchestrator.job_search.pdf.filename import resolve_entreprise
from orchestrator.job_search.pieces import DECISION_SANS_LETTRE, decision_lettre
from orchestrator.job_search.suivi import storage as suivi_storage

from .db import get_conn

router = APIRouter(prefix="/offers")


class MailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objet: str
    corps: str


def _check_retenu(conn, offer_id: int) -> None:
    if not suivi_storage.est_retenue(conn, offer_id):
        raise HTTPException(
            status_code=409,
            detail="Le mail n'est préparé que pour une offre retenue",
        )


def _offer_entreprise_intitule(conn, offer_id: int) -> tuple[str | None, str]:
    offer = conn.execute(
        "SELECT title, company FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    fiche = conn.execute(
        "SELECT employeur_nom FROM fiches_entreprise WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    entreprise = resolve_entreprise(
        offer["company"] if offer else None,
        fiche["employeur_nom"] if fiche else None,
    )
    intitule = (offer["title"] if offer else None) or ""
    return entreprise, intitule


@router.get("/{offer_id}/mail")
def get_mail_candidature(offer_id: int) -> dict:
    with get_conn() as conn:
        _check_retenu(conn, offer_id)
        mail = get_mail(conn, offer_id)
        if mail is not None:
            return mail
        entreprise, intitule = _offer_entreprise_intitule(conn, offer_id)
        lettre_row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    sans_lettre = decision_lettre(lettre_row) == DECISION_SANS_LETTRE
    try:
        # EXE-196, critère 11 : gabarit distinct sans lettre, mêmes repères.
        gabarit_text = load_gabarit_sans_lettre() if sans_lettre else load_gabarit()
    except GabaritAbsentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        rendu = render_mail_candidature(gabarit_text, intitule, entreprise)
    except RepereInconnuError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {**rendu, "origine": None, "modele": None, "created_at": None}


@router.put("/{offer_id}/mail")
def put_mail_candidature(offer_id: int, body: MailIn) -> dict:
    objet = body.objet.strip()
    corps = body.corps.strip()
    if not objet or not corps:
        raise HTTPException(status_code=422, detail="L'objet et le corps sont requis")
    with get_conn() as conn:
        _check_retenu(conn, offer_id)
        return enregistrer_manuel(conn, offer_id, objet, corps)


@router.post("/{offer_id}/mail/generer")
async def post_mail_generer(offer_id: int) -> dict:
    with get_conn() as conn:
        _check_retenu(conn, offer_id)
        lettre_row = conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        # EXE-196, critère 12 : refusé avant tout appel de modèle.
        if decision_lettre(lettre_row) == DECISION_SANS_LETTRE:
            raise HTTPException(
                status_code=409,
                detail="Cette annonce n'a pas de lettre : impossible de "
                "générer le mail depuis la lettre.",
            )
        lettre = (
            lettre_row
            if lettre_row is not None and lettre_row["statut"] == "done"
            else None
        )
        if lettre is None or not lettre["texte"]:
            raise HTTPException(
                status_code=409, detail="Écris ou génère la lettre d'abord"
            )
        entreprise, intitule = _offer_entreprise_intitule(conn, offer_id)
        texte_lettre = lettre["texte"]

    try:
        coordonnees = load_coordonnees()
    except CoordonneesManquantesError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        resultat = await generer_depuis_lettre(
            intitule, entreprise, texte_lettre, coordonnees
        )
    except ConsigneAbsenteError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReponseIncompleteError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    with get_conn() as conn:
        return persister_generation(conn, offer_id, resultat)


@router.get("/{offer_id}/mail/appel")
def get_mail_appel(offer_id: int) -> dict:
    with get_conn() as conn:
        _check_retenu(conn, offer_id)
        appel = get_appel(conn, offer_id)
    if appel is None:
        raise HTTPException(
            status_code=404, detail="Pas d'appel de modèle pour ce mail"
        )
    return appel
