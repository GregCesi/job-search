"""Choix du profil du CV — base ou écosystème Claude (EXE-184).

Détection 100% Python (architecture.md §3-4) : aucun appel modèle ne décide ce
choix, ni à la génération ni au recalcul après la fiche entreprise. Le profil
de base n'est jamais écrit en dur ici : c'est le paragraphe déjà présent dans
le CV de référence, laissé intact (H1 du ticket). Le profil Claude est le
texte d'un fichier posé à part (H4), repris mot pour mot (critère 6).
"""

from __future__ import annotations

import json
from typing import Literal

from orchestrator.job_search.paths import (
    CV_PROFIL_CLAUDE_EN_PATH,
    CV_PROFIL_CLAUDE_FR_PATH,
)

Profil = Literal["base", "claude"]
ProfilMotif = Literal["technos_offre", "fiche_entreprise", "aucune_mention", "manuel"]

MOTIF_LABELS: dict[str, str] = {
    "technos_offre": "Claude dans les technos de l'offre",
    "fiche_entreprise": "Claude dans la fiche entreprise",
    "aucune_mention": "aucune mention de Claude",
    "manuel": "choisi à la main",
}


def _mentionne_claude(texte: str | None) -> bool:
    return "claude" in (texte or "").lower()


def techs_citent_claude(techs_required: list[dict]) -> bool:
    """Critère 1 : une techno exigée contient « claude », quelle que soit la
    casse (claude, claude code, claude agent sdk — substring insensible à la
    casse)."""
    return any(_mentionne_claude(t.get("name")) for t in techs_required)


def fiche_cite_claude(presentation: str | None, points_json: str | None) -> bool:
    """Critère 3 : « Claude » dans la présentation, ou dans la position ou la
    citation d'un point. Critère 4 : manques, alertes, sources et prompt_text
    ne comptent pas — ils ne sont pas lus ici."""
    if _mentionne_claude(presentation):
        return True
    for point in json.loads(points_json or "[]"):
        if _mentionne_claude(point.get("position")) or _mentionne_claude(
            point.get("citation")
        ):
            return True
    return False


def determine_profile(
    conn, offer_id: int, techs_required: list[dict]
) -> tuple[Profil, ProfilMotif]:
    """Profil et motif calculés à la génération (critères 1, 3, 5) — une fiche
    non terminée ne compte pas (critère 3 : « fiche entreprise terminée »)."""
    if techs_citent_claude(techs_required):
        return "claude", "technos_offre"
    fiche = conn.execute(
        "SELECT statut, presentation, points_json FROM fiches_entreprise WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    if (
        fiche is not None
        and fiche["statut"] == "done"
        and fiche_cite_claude(fiche["presentation"], fiche["points_json"])
    ):
        return "claude", "fiche_entreprise"
    return "base", "aucune_mention"


def resolve_lead_text(
    lang: Literal["fr", "en"], profil: Profil
) -> tuple[str | None, str | None]:
    """(texte, message_erreur). Le profil de base ne touche jamais le
    paragraphe d'origine (H1) : `texte` vaut `None`, rien à substituer. Pour le
    profil Claude, `texte` est le contenu du fichier, mot pour mot (critère 6) ;
    si le fichier manque, `message_erreur` le nomme (critère 14)."""
    if profil == "base":
        return None, None
    path = CV_PROFIL_CLAUDE_FR_PATH if lang == "fr" else CV_PROFIL_CLAUDE_EN_PATH
    label = "français" if lang == "fr" else "anglais"
    if not path.exists():
        return None, f"Profil Claude ({label}) manquant : {path}"
    return path.read_text(encoding="utf-8").strip(), None
