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

from orchestrator.job_search.cv.skills import extract_lead_text
from orchestrator.job_search.paths import (
    CV_PROFIL_CLAUDE_EN_PATH,
    CV_PROFIL_CLAUDE_FR_PATH,
    CV_REFERENCE_EN_PATH,
    CV_REFERENCE_PATH,
)

Profil = Literal["base", "claude"]
ProfilMotif = Literal["technos_offre", "fiche_entreprise", "aucune_mention", "manuel"]

MOTIF_LABELS: dict[str, str] = {
    "technos_offre": "Claude dans les technos de l'offre",
    "fiche_entreprise": "Claude dans la fiche entreprise",
    "aucune_mention": "aucune mention de Claude",
    "manuel": "choisi à la main",
}

# Phrases affichées en tête de carte (EXE-185, critères 4-8) — distinctes de
# MOTIF_LABELS (panneau de détail, inchangé, EXE-184) : wording propre à ce
# ticket, jamais partagé.
PHRASE_SANS_PROFIL = "CV généré avant le choix automatique du profil"
PHRASE_NON_RECONNU = (
    "Profil non reconnu : le texte du CV ne correspond à aucun des deux profils"
)
PHRASE_FR_EN_DIFFERENT = "Les versions FR et EN n'ont pas le même profil"
PHRASE_INCOHERENT = "Le texte du CV ne correspond pas au profil enregistré"
PHRASE_MANUEL = "Choisi par toi"

_PHRASE_AUTOMATIQUE: dict[str, str] = {
    "technos_offre": "Choisi automatiquement : Claude est cité dans les technos de l'offre",
    "fiche_entreprise": "Choisi automatiquement : Claude est cité dans la fiche entreprise",
    "aucune_mention": "Choisi automatiquement : Claude n'est cité ni dans l'offre ni dans la fiche",
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


def constate_profil(cv_html: str | None, lang: Literal["fr", "en"]) -> Profil | None:
    """Profil constaté sur le texte réellement présent dans le CV (EXE-185,
    critères 2, 6, 8) — jamais le champ enregistré seul. Compare le paragraphe
    de profil du CV au paragraphe du CV de référence (profil de base, jamais
    modifié par lui-même) et au fichier du profil Claude de la même langue,
    mot pour mot. `None` si le texte ne correspond à aucun des deux (critère 6)."""
    lead = extract_lead_text(cv_html)
    if lead is None:
        return None
    lead = lead.strip()

    ref_path = CV_REFERENCE_PATH if lang == "fr" else CV_REFERENCE_EN_PATH
    if ref_path.exists():
        base_lead = extract_lead_text(ref_path.read_text(encoding="utf-8"))
        if base_lead is not None and lead == base_lead.strip():
            return "base"

    claude_path = CV_PROFIL_CLAUDE_FR_PATH if lang == "fr" else CV_PROFIL_CLAUDE_EN_PATH
    if claude_path.exists() and lead == claude_path.read_text(encoding="utf-8").strip():
        return "claude"

    return None


def compute_profil_affichage(
    html: str | None,
    en_html: str | None,
    profil_enregistre: Profil | None,
    profil_motif: ProfilMotif | None,
) -> tuple[Profil | None, str]:
    """Combine le texte réellement présent dans le CV et le profil enregistré
    pour décider ce que l'écran affiche (EXE-185, critères 2, 4-8). Rend
    (profil mis en évidence, phrase) : le profil mis en évidence suit toujours
    le texte constaté du CV français, jamais le champ enregistré seul
    (critère 8)."""
    constate_fr = constate_profil(html, "fr")
    if constate_fr is None:
        return None, PHRASE_NON_RECONNU

    if en_html is not None:
        constate_en = constate_profil(en_html, "en")
        if constate_en is not None and constate_en != constate_fr:
            return constate_fr, PHRASE_FR_EN_DIFFERENT

    if profil_motif is None:
        return constate_fr, PHRASE_SANS_PROFIL

    if profil_enregistre != constate_fr:
        return constate_fr, PHRASE_INCOHERENT

    return constate_fr, _PHRASE_AUTOMATIQUE.get(profil_motif, PHRASE_MANUEL)
