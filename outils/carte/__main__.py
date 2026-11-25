"""`python -m outils.carte` : régénère la carte du code, depuis la racine du dépôt.

Rend 0 et imprime les signalements (fichier non rangé, fichier sans phrase,
appel sans route trouvée, adresse illisible, table illisible, et ce qui a changé
depuis le relevé d'avant), deux lignes de résumé, puis, en dernière ligne, le
chemin de la page écrite. Réécrit le relevé `docs/carte/graphe.json`.
Rend 1, sans écrire ni la page ni le relevé, si le fichier de textes contredit
le disque ou si une étape de parcours cite un élément absent de la carte.

Usage : .venv/bin/python -m outils.carte [--racine R] [--textes T] [--sortie S]
        [--releve G]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from outils.carte.assemblage import assembler
from outils.carte.chaine import completer
from outils.carte.graphe import imports_directs
from outils.carte.lecture import (
    ErreurTextes,
    charger_textes,
    fichiers_de_la_carte,
    verifier_textes,
)
from outils.carte.page import ecrire_page
from outils.carte.parcours import ensemble, parcours_de_la_carte
from outils.carte.releve import comparer, ecrire_releve, lire_releve, releve

TEXTES_DEFAUT = Path("docs/carte/textes.toml")
SORTIE_DEFAUT = Path("docs/carte/index.html")
RELEVE_DEFAUT = Path("docs/carte/graphe.json")


def _commit_court(racine: Path) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=racine,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else "inconnu"


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parseur = argparse.ArgumentParser(
        prog="python -m outils.carte", description="Régénère la carte du code."
    )
    parseur.add_argument("--racine", type=Path, default=Path.cwd())
    parseur.add_argument("--textes", type=Path, default=None)
    parseur.add_argument("--sortie", type=Path, default=None)
    parseur.add_argument("--releve", type=Path, default=None)
    return parseur.parse_args(argv)


def _pluriel(n: int, mot: str, pluriel: str | None = None) -> str:
    return f"{n} {mot if n == 1 else (pluriel or mot + 's')}"


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    racine = args.racine.resolve()
    textes_chemin = args.textes or racine / TEXTES_DEFAUT
    sortie = (args.sortie or racine / SORTIE_DEFAUT).resolve()
    chemin_releve = (args.releve or racine / RELEVE_DEFAUT).resolve()
    try:
        textes = charger_textes(textes_chemin)
    except ErreurTextes as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1
    erreurs = verifier_textes(textes, racine)
    for erreur in erreurs:
        print(f"erreur : {erreur}", file=sys.stderr)
    if erreurs:
        return 1

    fichiers = fichiers_de_la_carte(racine)
    entete = {
        "genere_le": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "commit": _commit_court(racine),
    }
    carte = assembler(fichiers, textes, imports_directs(racine), racine, entete)
    completer(carte, racine, textes)
    parcours, erreurs = parcours_de_la_carte(textes, carte.donnees)
    for erreur in erreurs:
        print(f"erreur : {erreur}", file=sys.stderr)
    if erreurs:
        return 1
    nouveau = releve(carte.donnees)
    ancien = lire_releve(chemin_releve)
    changements = [] if ancien is None else comparer(ancien, nouveau)
    carte.donnees["parcours"] = parcours
    carte.donnees["ensemble"] = ensemble(textes)
    carte.donnees["positions"] = textes.positions
    carte.donnees["depuis"] = {"premier": ancien is None, "changements": changements}
    ecrire_page(carte.donnees, sortie)
    ecrire_releve(nouveau, chemin_releve)

    for signalement in carte.signalements + changements:
        print(f"signalé : {signalement}")
    print(
        f"Carte : {_pluriel(carte.nb_fichiers, 'fichier')}, "
        f"{_pluriel(carte.nb_fleches, 'flèche')} entre fichiers, "
        f"{_pluriel(carte.nb_systemes, 'système')}."
    )
    d = carte.donnees
    print(
        f"Chaîne : {_pluriel(len(d['fichiers_front']), 'écran')}, "
        f"{_pluriel(len(d['routes']), 'route')}, "
        f"{_pluriel(len(d['tables']), 'table')}, "
        f"{_pluriel(d['base']['hors_stockage'], 'appel direct', 'appels directs')} "
        "à la base hors stockage."
    )
    print(sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
