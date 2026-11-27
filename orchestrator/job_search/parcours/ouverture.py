"""Ouverture d'une offre, lue sur son parcours de candidature (EXE-218, H4).

Quatre signes de fermeture, dans cet ordre : la source ne rend plus l'offre, le
code de la page de fin, une phrase de fermeture sur cette page, le renvoi vers
une autre page. Dans le doute, l'offre reste : un refus, une panne, une erreur du
site, un mail, un formulaire ou une page d'accueil ne ferment rien.

Les phrases de fermeture vivent dans profiles/a_postuler.yaml (section
`parcours`) : aucune phrase n'est écrite ici.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from orchestrator.job_search.parcours.adresses import est_accueil, site

OUVERTE = "ouverte"
FERMEE = "fermée"
NON_VERIFIABLE = "non vérifiable"

SOURCE = "la source ne rend plus l'offre"
EDITX_FERMEE = "EDITx n'accepte plus de candidature"
INTROUVABLE = "page introuvable"
PHRASE = "la page dit que l'offre est fermée"
RENVOI = "renvoi vers une autre page"

CODES_FERMES = frozenset({404, 410})

_INVISIBLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.S)
_BALISE = re.compile(r"<[^>]*>")
_ESPACES = re.compile(r"\s+")
_NUMERO = re.compile(r"\d{4,}")


@dataclass(frozen=True)
class PageLue:
    """La page de fin : l'adresse demandée (nettoyée), l'adresse d'arrivée après
    les redirections, son code et son texte."""

    demandee: str
    arrivee: str
    code: int
    texte: str


def fermeture(
    signe: str, nom_site: str, code: int | None = None, phrase: str | None = None
) -> dict:
    return {"signe": signe, "site": nom_site, "code": code, "phrase": phrase}


def charger_phrases(chemin: str | Path) -> tuple[str, ...]:
    """Lève OSError si le fichier est illisible, yaml.YAMLError s'il est mal formé."""
    data = yaml.safe_load(Path(chemin).read_text(encoding="utf-8")) or {}
    phrases = (data.get("parcours") or {}).get("phrases_fermeture") or []
    return tuple(str(p) for p in phrases if str(p).strip())


def _normaliser(texte: str) -> str:
    texte = texte.replace("’", "'").replace(" ", " ")
    return _ESPACES.sub(" ", texte).casefold()


def texte_visible(page: str) -> str:
    """Titre et texte de la page, sans balises ni contenu de script ou de style."""
    sans_code = _INVISIBLE.sub(" ", page or "")
    return _normaliser(html.unescape(_BALISE.sub(" ", sans_code)))


def phrase_trouvee(page: str, phrases: tuple[str, ...]) -> str | None:
    """La première phrase de fermeture lue dans la page, sans tenir compte de la casse."""
    visible = texte_visible(page)
    for phrase in phrases:
        if _normaliser(phrase).strip() in visible:
            return phrase
    return None


def numero(adresse: str) -> str | None:
    """La plus longue suite d'au moins 4 chiffres de l'adresse (la première à égalité)."""
    suites = _NUMERO.findall(adresse)
    return max(suites, key=len) if suites else None


def renvoi(demandee: str, arrivee: str) -> bool:
    """Le numéro de l'offre a disparu de l'adresse d'arrivée. Une adresse sans
    numéro n'est jamais fermée par ce signe."""
    num = numero(demandee)
    return num is not None and num not in arrivee


def juger_page(page: PageLue, phrases: tuple[str, ...]) -> tuple[str, dict | None]:
    """L'ouverture lue sur la page de fin, et le signe de fermeture s'il y en a un."""
    if est_accueil(page.demandee):
        return NON_VERIFIABLE, None
    nom_site = site(page.arrivee)
    if page.code in CODES_FERMES:
        return FERMEE, fermeture(INTROUVABLE, nom_site, page.code)
    if not 200 <= page.code < 300:
        return NON_VERIFIABLE, None
    phrase = phrase_trouvee(page.texte, phrases)
    if phrase is not None:
        return FERMEE, fermeture(PHRASE, nom_site, page.code, phrase)
    if renvoi(page.demandee, page.arrivee):
        return FERMEE, fermeture(RENVOI, site(page.demandee), page.code)
    if est_accueil(page.arrivee):
        return NON_VERIFIABLE, None
    return OUVERTE, None
