"""Nom de fichier des pièces PDF (CV, lettre) — EXE-102.

Résolution de l'entreprise affichée dans le nom (critères 11-13) : l'entreprise de
l'offre si elle est utilisable, sinon l'employeur trouvé par la fiche entreprise
quand l'offre est vide ou un intermédiaire connu (`profiles/intermediaires.yaml`),
sinon l'intitulé de l'offre — décidé par l'appelant, cette fonction ne connaît pas
l'intitulé.

Assainissement (critère 14) : accents retirés, toute suite de caractères hors
lettres/chiffres/tiret devient un seul « _ », sans « _ » de bord par partie.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

from orchestrator.job_search.fiche.intermediaires import is_known
from orchestrator.job_search.pdf.coordonnees import Coordonnees

_NON_ALNUM_DASH = re.compile(r"[^A-Za-z0-9-]+")


def sanitize_part(value: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", value)
    sans_accents = "".join(c for c in sans_accents if not unicodedata.combining(c))
    return _NON_ALNUM_DASH.sub("_", sans_accents).strip("_")


def resolve_entreprise(company: str | None, employeur_fiche: str | None) -> str | None:
    """Entreprise utilisable pour le nom de fichier, ou None (critère 13 : alors
    l'appelant retombe sur l'intitulé de l'offre)."""
    company = (company or "").strip()
    if company and not is_known(company):
        return company
    employeur_fiche = (employeur_fiche or "").strip()
    return employeur_fiche or None


def piece_filename(prefix: str, prenom: str, nom: str, entreprise_ou_titre: str) -> str:
    parts = [
        prefix,
        sanitize_part(prenom),
        sanitize_part(nom),
        sanitize_part(entreprise_ou_titre),
    ]
    return "_".join(parts) + ".pdf"


def resolve_piece_filename(
    conn: sqlite3.Connection, offer_id: int, prefix: str, coordonnees: Coordonnees
) -> str:
    """Nom de fichier complet d'une pièce (critères 4, 10-14) : lit l'offre et sa
    fiche entreprise, résout l'entreprise, puis assainit."""
    offer = conn.execute(
        "SELECT company, title FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    fiche = conn.execute(
        "SELECT employeur_nom FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    entreprise = resolve_entreprise(
        offer["company"] if offer else None,
        fiche["employeur_nom"] if fiche else None,
    )
    if not entreprise:
        entreprise = (offer["title"] if offer else "") or ""
    return piece_filename(
        prefix, coordonnees.prenom, coordonnees.nom_de_famille, entreprise
    )
