"""Calculs Python purs pour la lettre de motivation (EXE-65).

Frontière (architecture.md §4) : le choix des points, le comptage de mots et la
détection de tournures interdites ne dépendent d'aucun jugement du modèle — ce sont
des calculs déterministes appliqués à ce qu'il rend, jamais des corrections de ce
texte (une tournure signalée reste dans le texte stocké).
"""

from __future__ import annotations

import html as html_lib
import json
import re
from pathlib import Path

MAX_MOTS = (
    250  # EXE-162, H2 : recruteurs lus le 8 octobre 2026, lettres de 120 à 250 mots
)

# Raisons de blocage du lancement de la lettre (EXE-127, critère 15 ; réduites à
# deux par EXE-162, critère 3 : la boucle retient elle-même un fait ou part en
# générique, le choix de points ne gate plus rien) — centralisées ici pour que la
# route, l'avancement et la cascade au geste de retenir disent toujours la même chose.
RAISON_FICHE_NON_TERMINEE = "La fiche entreprise de cette offre n'est pas terminée"
RAISON_TEXTE_MANQUANT = "Le texte de l'offre manque, impossible de générer la lettre"
# EXE-162, critère 17 : écarter un fait quand la lettre est générique (aucun fait
# retenu) n'a rien à retirer.
RAISON_RIEN_A_ECARTER = "Il n'y a rien à écarter : cette lettre est générique"


def resolve_chosen_indices(points: list[dict], stored_json: str | None) -> list[int]:
    """Indices des points choisis pour la lettre.

    Par défaut (aucun choix explicite stocké), les points du tas « lettre » (critère 5).
    Un choix explicite stocké prévaut toujours, même vide (critère 8 — démarquer tout).
    """
    if stored_json is not None:
        return sorted(json.loads(stored_json))
    return [i for i, p in enumerate(points) if p.get("tas") == "lettre"]


def point_text(point: dict) -> str:
    """Texte d'un point de fiche : sa position, complétée par sa citation si présente."""
    position = (point.get("position") or "").strip()
    citation = point.get("citation")
    if citation:
        return f"{position} — « {citation} »"
    return position


def strip_style_and_script(raw: str) -> str:
    """Retire les blocs <style> et <script> en entier — balise et contenu — avant
    tout autre nettoyage (EXE-153, critères 1, 2, 5) : leur contenu (CSS, JS) n'est
    jamais du texte visible, contrairement au contenu des autres balises."""
    return re.sub(
        r"<(style|script)\b[^>]*>.*?</\1>", "", raw, flags=re.IGNORECASE | re.DOTALL
    )


def strip_html(raw: str) -> str:
    """Texte sans balise HTML (critère 13) : blocs <style>/<script> retirés en
    entier (EXE-153), tags retirés, entités décodées, espaces simples resserrés
    (les sauts de ligne sont conservés)."""
    text = strip_style_and_script(raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def count_words(texte: str) -> int:
    return len(texte.split())


def exceeds_length(nb_mots: int, max_mots: int = MAX_MOTS) -> bool:
    return nb_mots > max_mots


def ecart_longueur_mots(nb_mots: int, longueur_cible_mots: int | None) -> int | None:
    """Écart signé en mots à la longueur cible du répertoire (EXE-152, banc,
    critère 8) — absent si aucune cible n'est déclarée, jamais remplacé par
    zéro (critère 9)."""
    if longueur_cible_mots is None:
        return None
    return nb_mots - longueur_cible_mots


def load_tournures_interdites(path: Path) -> list[str]:
    """Une tournure par ligne (H3 du ticket). Fichier absent → liste vide : ce n'est
    pas un critère de blocage de la génération, seulement de son signalement."""
    if not path.exists():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def detect_tournures(texte: str, tournures: list[str]) -> list[str]:
    """Tournures interdites trouvées dans `texte`, comparaison sans tenir compte de la
    casse (H3 du ticket, critère 16). Rend les occurrences telles qu'écrites dans le
    texte — jamais de correction de `texte` lui-même (invariant du ticket)."""
    lower_texte = texte.lower()
    found: list[str] = []
    for tournure in tournures:
        idx = lower_texte.find(tournure.lower())
        if idx != -1:
            found.append(texte[idx : idx + len(tournure)])
    return found


def resolve_offer_text(description_raw: str | None, description: str | None) -> str:
    """Texte de l'offre à envoyer au modèle (EXE-84) : le texte brut s'il contient
    autre chose que des espaces, sinon le texte nettoyé. Chaîne vide si les deux sont
    vides — signal de refus de génération, jamais un texte à corriger ici."""
    if (description_raw or "").strip():
        return description_raw
    if (description or "").strip():
        return description
    return ""


def blocage_lancement_lettre(fiche_statut: str | None, offer_text: str) -> str | None:
    """Raison qui empêche de lancer la lettre, ou `None` si elle peut partir
    (EXE-162, critère 3) : fiche pas terminée, puis texte d'offre manquant — dans
    cet ordre, le premier qui bloque gagne. Le choix de points ne gate plus rien
    (la boucle retient elle-même un fait parmi ceux de la fiche, ou part en
    générique si aucun ne convient)."""
    if fiche_statut != "done":
        return RAISON_FICHE_NON_TERMINEE
    if not offer_text:
        return RAISON_TEXTE_MANQUANT
    return None
