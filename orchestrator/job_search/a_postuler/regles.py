"""Mots de la règle des files « À postuler » et « À étudier » (EXE-210).

Les mots vivent dans `profiles/a_postuler.yaml`, suivi par git. Ce module ne fait
que les charger et dire si un texte en contient un : aucun mot de la règle n'est
écrit ici (ticket, « ce qui ne doit pas arriver »).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml


def _mot_entier(termes: list[str]) -> re.Pattern[str] | None:
    """Un terme ni précédé ni suivi d'une lettre ou d'un chiffre, sans casse."""
    if not termes:
        return None
    alternance = "|".join(re.escape(t.casefold()) for t in termes)
    return re.compile(rf"(?<![^\W_])(?:{alternance})(?![^\W_])")


def premier_mot(motif: re.Pattern[str] | None, texte: str) -> str | None:
    if motif is None:
        return None
    trouve = motif.search(texte.casefold())
    return trouve.group(0) if trouve else None


def premiere_sous_chaine(termes: tuple[str, ...], texte: str) -> str | None:
    bas = texte.casefold()
    return next((t for t in termes if t in bas), None)


def sans_accents(texte: str) -> str:
    """Le texte sans casse ni accents, espaces de bord retirées."""
    decompose = unicodedata.normalize("NFKD", texte.casefold().strip())
    return "".join(c for c in decompose if not unicodedata.combining(c))


@dataclass(frozen=True)
class Regles:
    communes_acceptees: re.Pattern[str] | None
    lieux_refuses: re.Pattern[str] | None
    pays_non_precis: tuple[str, ...]
    plages_codes_postaux: tuple[tuple[int, int], ...]
    provinces_refusees: frozenset[str]
    jours_en_ligne_max: int | None
    contrats_refuses: frozenset[str]
    titre_stage: re.Pattern[str] | None
    titre_senior: re.Pattern[str] | None
    titre_formateur: re.Pattern[str] | None
    titre_robotique: re.Pattern[str] | None
    titre_cloud_reseau: re.Pattern[str] | None
    titre_analyse: re.Pattern[str] | None
    titre_automatisation: tuple[str, ...]
    neerlandais: tuple[str, ...]
    tournures_atout: tuple[str, ...]
    ia_sous_chaine: tuple[str, ...]
    ia_mot_entier: re.Pattern[str] | None
    auto_sous_chaine: tuple[str, ...]
    auto_mot_entier: re.Pattern[str] | None
    domaines_ia: frozenset[str]
    domaines_techniques: frozenset[str]
    domaines_developpeur: frozenset[str]
    domaines_data: frozenset[str]
    niveaux_a_etudier: frozenset[str]
    niveaux_premier_groupe: frozenset[str]
    jours_recents: int
    marqueurs_titre: re.Pattern[str] | None

    def est_ia(self, techno: str) -> bool:
        return bool(
            premiere_sous_chaine(self.ia_sous_chaine, techno)
            or premier_mot(self.ia_mot_entier, techno)
        )

    def est_automatisation(self, techno: str) -> bool:
        return bool(
            premiere_sous_chaine(self.auto_sous_chaine, techno)
            or premier_mot(self.auto_mot_entier, techno)
        )


def _bas(valeurs: list[str] | None) -> tuple[str, ...]:
    return tuple(v.casefold() for v in valeurs or [])


def _plages(valeurs: list | None) -> tuple[tuple[int, int], ...]:
    """« 1000-1348 » ou « 1360 » : bornes comprises. Lève ValueError sur une plage mal écrite."""
    plages = []
    for valeur in valeurs or []:
        debut, _, fin = str(valeur).partition("-")
        plages.append((int(debut), int(fin or debut)))
    return tuple(plages)


def _marqueurs(termes: list[str]) -> re.Pattern[str] | None:
    """Un marqueur (H/F…), avec ses parenthèses s'il en a (H6)."""
    if not termes:
        return None
    alternance = "|".join(re.escape(t.casefold()) for t in termes)
    return re.compile(rf"\(?(?<![^\W_])(?:{alternance})(?![^\W_])\)?")


def charger_regles(chemin: str | Path) -> Regles:
    """Lève OSError si le fichier est illisible, yaml.YAMLError, KeyError ou
    ValueError s'il est mal formé."""
    data = yaml.safe_load(Path(chemin).read_text(encoding="utf-8")) or {}
    lieu = data.get("lieu", {})
    titre = data.get("titre", {})
    nl = data.get("neerlandais", {})
    technos = data.get("technos", {})
    domaines = data.get("domaines", {})
    return Regles(
        communes_acceptees=_mot_entier(lieu.get("communes_acceptees", [])),
        lieux_refuses=_mot_entier(lieu.get("lieux_refuses", [])),
        pays_non_precis=_bas(lieu.get("pays_non_precis")),
        plages_codes_postaux=_plages(lieu.get("plages_codes_postaux")),
        provinces_refusees=frozenset(
            sans_accents(p) for p in lieu.get("provinces_refusees") or []
        ),
        jours_en_ligne_max=(
            int(lieu["jours_en_ligne_max"]) if "jours_en_ligne_max" in lieu else None
        ),
        contrats_refuses=frozenset(_bas(data.get("contrats_refuses"))),
        titre_stage=_mot_entier(titre.get("stage", [])),
        titre_senior=_mot_entier(titre.get("senior", [])),
        titre_formateur=_mot_entier(titre.get("formateur", [])),
        titre_robotique=_mot_entier(titre.get("robotique", [])),
        titre_cloud_reseau=_mot_entier(titre.get("cloud_reseau", [])),
        titre_analyse=_mot_entier(titre.get("analyse", [])),
        titre_automatisation=_bas(titre.get("automatisation")),
        neerlandais=_bas(nl.get("mots")),
        tournures_atout=_bas(nl.get("tournures_atout")),
        ia_sous_chaine=_bas(technos.get("ia_sous_chaine")),
        ia_mot_entier=_mot_entier(technos.get("ia_mot_entier", [])),
        auto_sous_chaine=_bas(technos.get("automatisation_sous_chaine")),
        auto_mot_entier=_mot_entier(technos.get("automatisation_mot_entier", [])),
        domaines_ia=frozenset(domaines.get("ia", [])),
        domaines_techniques=frozenset(domaines.get("techniques", [])),
        domaines_developpeur=frozenset(domaines.get("developpeur", [])),
        domaines_data=frozenset(domaines.get("data", [])),
        niveaux_a_etudier=frozenset(data.get("niveaux_a_etudier", [])),
        niveaux_premier_groupe=frozenset(data.get("niveaux_premier_groupe", [])),
        jours_recents=int(data["jours_recents"]),
        marqueurs_titre=_marqueurs(data.get("marqueurs_titre", [])),
    )
