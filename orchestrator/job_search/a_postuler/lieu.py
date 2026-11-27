"""Le lieu d'une offre dans les files et les marques de son parcours (EXE-220).

Python pur. Le lieu réel se lit dans le parcours de candidature à chaque lecture
des files, et ne réécrit jamais le lieu de l'offre en base. La zone de recherche
est la liste des plages de codes postaux de `profiles/a_postuler.yaml` : aucune
distance n'est calculée ici, et aucun mot, plage ni nombre de jours n'y est écrit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from orchestrator.job_search.a_postuler.regles import (
    Regles,
    premier_mot,
    premiere_sous_chaine,
    sans_accents,
)
from orchestrator.job_search.parcours.lecture import ACCUEIL

LIEU = "lieu"

MARQUE_LIEU = "lieu non précisé"
MARQUE_SANS_LIEN = "sans lien"
MARQUE_ACCUEIL = "page d'accueil de l'employeur"
MARQUE_ANCIENNE = "en ligne depuis plus de 6 mois"
MARQUE_JAMAIS_VERIFIEE = "jamais vérifiée"

_DEPARTEMENT = re.compile(r"\d{2}")
_CODE_BELGE = re.compile(r"\d{4}")


@dataclass(frozen=True)
class ParcoursFile:
    """Ce que les files lisent du parcours d'une offre. `lu` : le parcours a été lu
    au moins une fois ; `adresse` : l'offre a un point de départ pour le lire."""

    lu: bool
    adresse: bool
    lieu_reel: str | None = None
    code_postal: str | None = None
    provinces: tuple[str, ...] = ()
    fin_forme: str | None = None
    fin_adresse: str | None = None
    en_ligne_depuis: str | None = None
    verifiee_le: str | None = None


@dataclass(frozen=True)
class LieuJuge:
    affiche: str
    motif: str | None
    marques: list[str]


def motif_lieu(lieu: str, regles: Regles) -> tuple[str | None, list[str]]:
    """La règle sur le seul lieu de l'annonce (EXE-210)."""
    texte = lieu.casefold().strip()
    if _DEPARTEMENT.match(texte):
        return LIEU, []
    if premier_mot(regles.communes_acceptees, texte):
        return None, []
    if premier_mot(regles.lieux_refuses, texte):
        return LIEU, []
    if premiere_sous_chaine(regles.pays_non_precis, texte):
        return None, [MARQUE_LIEU]
    return LIEU, []


def lieu_reel(p: ParcoursFile | None, regles: Regles) -> str | None:
    """Le lieu réel du parcours, ou None s'il n'y en a pas ou s'il n'est que le
    nom du pays."""
    if p is None or not p.lieu_reel or not p.lieu_reel.strip():
        return None
    if p.lieu_reel.casefold().strip() in regles.pays_non_precis:
        return None
    return p.lieu_reel.strip()


def code_postal_belge(p: ParcoursFile | None) -> int | None:
    """Le champ une fois ses espaces retirées, s'il fait exactement quatre chiffres."""
    if p is None or p.code_postal is None:
        return None
    code = "".join(p.code_postal.split())
    return int(code) if _CODE_BELGE.fullmatch(code) else None


def _motif_parcours(
    reel: str | None, code: int | None, provinces: tuple[str, ...], regles: Regles
) -> str | None:
    """Les règles 1 à 5 de H5, dans l'ordre."""
    if reel and premier_mot(regles.communes_acceptees, reel):
        return None
    if reel and premier_mot(regles.lieux_refuses, reel):
        return LIEU
    if code is not None:
        dans_la_zone = any(a <= code <= b for a, b in regles.plages_codes_postaux)
        return None if dans_la_zone else LIEU
    if provinces and all(
        sans_accents(p) in regles.provinces_refusees for p in provinces
    ):
        return LIEU
    return None


def juger_lieu(annonce: str, p: ParcoursFile | None, regles: Regles) -> LieuJuge:
    """Le lieu affiché, le motif « lieu » ou None, et la marque de lieu."""
    motif_annonce, marques_annonce = motif_lieu(annonce, regles)
    reel = lieu_reel(p, regles)
    code = code_postal_belge(p)
    provinces = p.provinces if p is not None else ()
    marques = [] if reel else marques_annonce
    affiche = reel or annonce
    if _DEPARTEMENT.match(annonce.casefold().strip()):
        return LieuJuge(affiche, LIEU, marques)
    if not (reel or code is not None or provinces):
        return LieuJuge(affiche, motif_annonce, marques)
    return LieuJuge(affiche, _motif_parcours(reel, code, provinces, regles), marques)


def _jours_en_ligne(en_ligne_depuis: str | None, aujourdhui: date) -> int | None:
    if not en_ligne_depuis:
        return None
    try:
        return (aujourdhui - date.fromisoformat(en_ligne_depuis[:10])).days
    except ValueError:
        return None


def marques_parcours(
    p: ParcoursFile | None, regles: Regles, maintenant: datetime
) -> list[str]:
    """Ce que la ligne dit de regarder soi-même : sans lien, page d'accueil,
    annonce ancienne, jamais vérifiée."""
    if p is None:
        return []
    if not p.lu:
        return [MARQUE_JAMAIS_VERIFIEE if p.adresse else MARQUE_SANS_LIEN]
    marques = []
    if p.fin_forme == ACCUEIL:
        marques.append(MARQUE_ACCUEIL)
    jours = _jours_en_ligne(p.en_ligne_depuis, maintenant.date())
    if (
        jours is not None
        and regles.jours_en_ligne_max is not None
        and jours > regles.jours_en_ligne_max
    ):
        marques.append(MARQUE_ANCIENNE)
    return marques
