"""Assemblage des données de la carte : fichiers, systèmes, flèches et signalements.

Une phrase vient de la docstring du fichier, sinon du fichier de textes ; à
défaut, la page affiche `PAS_DE_PHRASE` et la commande le signale. Rien n'est
inventé.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from outils.carte.graphe import chemin_de_test
from outils.carte.lecture import Fichier, Textes

PAS_DE_PHRASE = "Pas de phrase pour ce fichier."
AUTRES_ID = "autres"
AUTRES_NOM = "Autres (à ranger)"
AUTRES_ROLE = "Fichiers qu'aucun système du fichier de textes ne range encore."


@dataclass
class Carte:
    donnees: dict
    signalements: list[str] = field(default_factory=list)
    nb_fichiers: int = 0
    nb_fleches: int = 0
    nb_systemes: int = 0


def _phrase(fichier: Fichier, textes: Textes) -> str | None:
    return fichier.phrase_docstring or textes.phrases.get(fichier.chemin)


def _liens(
    fichiers: list[Fichier], imports: dict[str, set[str]], racine: Path
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, set[str]]]:
    """Importe, importé par (entre fichiers de la carte) et tests importeurs."""
    par_module = {f.module: f.chemin for f in fichiers}
    importe = {f.chemin: set() for f in fichiers}
    importe_par = {f.chemin: set() for f in fichiers}
    tests = {f.chemin: set() for f in fichiers}
    for module, cibles in imports.items():
        source = par_module.get(module)
        test = None if source else chemin_de_test(module, racine)
        for cible in cibles:
            chemin_cible = par_module.get(cible)
            if chemin_cible is None or chemin_cible == source:
                continue
            if source:
                importe[source].add(chemin_cible)
                importe_par[chemin_cible].add(source)
            elif test:
                tests[chemin_cible].add(test)
    return importe, importe_par, tests


def _systemes(textes: Textes, presents: set[str]) -> tuple[list[dict], dict[str, str]]:
    systemes = []
    systeme_de: dict[str, str] = {}
    for s in textes.systemes:
        fichiers = [f for f in s.fichiers if f in presents]
        systemes.append(
            {"id": s.id, "nom": s.nom, "role": s.role, "fichiers": sorted(fichiers)}
        )
        systeme_de.update({f: s.id for f in fichiers})
    return systemes, systeme_de


def _fleches(importe: dict[str, set[str]], systeme_de: dict[str, str]) -> list[dict]:
    compte: Counter[tuple[str, str]] = Counter()
    for source, cibles in importe.items():
        for cible in cibles:
            de, vers = systeme_de[source], systeme_de[cible]
            if de != vers:
                compte[(de, vers)] += 1
    return [
        {"de": de, "vers": vers, "n": n}
        for (de, vers), n in sorted(compte.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def assembler(
    fichiers: list[Fichier],
    textes: Textes,
    imports: dict[str, set[str]],
    racine: Path,
    entete: dict,
) -> Carte:
    importe, importe_par, tests = _liens(fichiers, imports, racine)
    systemes, systeme_de = _systemes(textes, {f.chemin for f in fichiers})
    signalements: list[str] = []
    autres = [f.chemin for f in fichiers if f.chemin not in systeme_de]
    for chemin in autres:
        systeme_de[chemin] = AUTRES_ID
        signalements.append(f"fichier nouveau qu'aucun système ne range : {chemin}")
    donnees_fichiers = {}
    for f in fichiers:
        phrase = _phrase(f, textes)
        if phrase is None:
            signalements.append(f"fichier sans phrase : {f.chemin}")
        donnees_fichiers[f.chemin] = {
            "systeme": systeme_de[f.chemin],
            "phrase": phrase or PAS_DE_PHRASE,
            "lignes": f.lignes,
            "importe": sorted(importe[f.chemin]),
            "importe_par": sorted(importe_par[f.chemin]),
            "tests": sorted(tests[f.chemin]),
        }
    donnees = {
        **entete,
        "systemes": systemes,
        "autres": autres,
        "autres_systeme": {"id": AUTRES_ID, "nom": AUTRES_NOM, "role": AUTRES_ROLE},
        "fichiers": donnees_fichiers,
        "fleches": _fleches(importe, systeme_de),
    }
    return Carte(
        donnees=donnees,
        signalements=signalements,
        nb_fichiers=len(fichiers),
        nb_fleches=sum(len(c) for c in importe.values()),
        nb_systemes=len(systemes),
    )
