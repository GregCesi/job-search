"""Rendu du mail de candidature depuis le gabarit `MAIL_CANDIDATURE_PATH` — EXE-103.

Gabarit texte, hors git (H3 du ticket) : première ligne « Objet : … », une ligne
vide, puis le corps. Deux repères reconnus : `{intitule}` et `{chez_entreprise}`.

Aucun appel modèle, aucun stockage : le mail se recalcule au caractère près à
chaque demande à partir du gabarit lu sur disque (critères 5, 6, 10).
"""

from __future__ import annotations

import re

from orchestrator.job_search.paths import MAIL_CANDIDATURE_PATH

_REPERE_PATTERN = re.compile(r"\{(\w+)\}")
_REPERES_CONNUS = {"intitule", "chez_entreprise"}
_CHEZ_ENTREPRISE_AVEC_ESPACES = re.compile(r"\s*\{chez_entreprise\}\s*")
_OBJET_PREFIX = "Objet : "


class GabaritAbsentError(Exception):
    def __init__(self, path) -> None:
        super().__init__(f"Fichier de gabarit du mail absent : {path}")
        self.path = path


class RepereInconnuError(Exception):
    def __init__(self, repere: str) -> None:
        super().__init__(f"Repère inconnu dans le gabarit du mail : {{{repere}}}")
        self.repere = repere


def load_gabarit() -> str:
    """Lit `MAIL_CANDIDATURE_PATH` (module global, monkeypatché dans les tests —
    même convention que `coordonnees.load_coordonnees`)."""
    if not MAIL_CANDIDATURE_PATH.exists():
        raise GabaritAbsentError(MAIL_CANDIDATURE_PATH)
    return MAIL_CANDIDATURE_PATH.read_text(encoding="utf-8")


def _parse_gabarit(text: str) -> tuple[str, str]:
    header, _, corps = text.partition("\n\n")
    objet = header.removeprefix(_OBJET_PREFIX)
    return objet, corps


def _verifier_reperes(text: str) -> None:
    for repere in _REPERE_PATTERN.findall(text):
        if repere not in _REPERES_CONNUS:
            raise RepereInconnuError(repere)


def _retirer_chez_entreprise(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        start, end = match.span()
        before = text[start - 1] if start > 0 else ""
        after = text[end] if end < len(text) else ""
        if not before or not after or after in ",.;:!?":
            return ""
        return " "

    return _CHEZ_ENTREPRISE_AVEC_ESPACES.sub(repl, text)


def _substituer(text: str, intitule: str, entreprise: str | None) -> str:
    text = text.replace("{intitule}", intitule)
    if entreprise:
        text = text.replace("{chez_entreprise}", f"chez {entreprise}")
    else:
        text = _retirer_chez_entreprise(text)
    return text


def render_mail_candidature(
    gabarit_text: str, intitule: str, entreprise: str | None
) -> dict[str, str]:
    """Rend `{"objet": ..., "corps": ...}` à partir du texte brut du gabarit.

    Lève `RepereInconnuError` si un repère entre accolades n'est ni `intitule`
    ni `chez_entreprise` (critère 8). Hors des deux repères, le texte rendu est
    celui du gabarit au caractère près (critère 5)."""
    objet_gabarit, corps_gabarit = _parse_gabarit(gabarit_text)
    _verifier_reperes(objet_gabarit)
    _verifier_reperes(corps_gabarit)
    return {
        "objet": _substituer(objet_gabarit, intitule, entreprise),
        "corps": _substituer(corps_gabarit, intitule, entreprise),
    }
