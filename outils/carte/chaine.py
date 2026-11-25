"""La chaîne de l'écran à la table (EXE-214), ajoutée aux données de la carte :
écrans, routes, tables, couche et appels directs à la base de chaque fichier.

Un appel du front rejoint une route quand leurs segments sont égaux un à un,
une variable du gabarit valant un paramètre entre accolades, et que la méthode
est la même. Ce qui ne se relie pas va dans « À vérifier », sous les seuls mots
« appel sans route trouvée », « adresse illisible », « Aucun appel trouvé dans
le front. » et « table illisible ».
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

from outils.carte.assemblage import PAS_DE_PHRASE, Carte
from outils.carte.base import (
    AccesTables,
    acces_tables,
    appels_directs,
    est_stockage,
    tables_creees,
)
from outils.carte.front import FichierFront, lire_front, segments_de_route
from outils.carte.lecture import Textes
from outils.carte.routes import Route, lire_routes

ECRANS = {
    "id": "ecrans",
    "nom": "Écrans",
    "role": "Pages, composants et stores du front Nuxt, sous web/app/ : "
    "ils appellent l'API par son adresse.",
}


def _arbre(racine: Path, chemin: str) -> tuple[ast.Module, str]:
    texte = (racine / chemin).read_text(encoding="utf-8")
    try:
        return ast.parse(texte), texte
    except SyntaxError:
        return ast.Module(body=[], type_ignores=[]), texte


def _relier(
    front: list[FichierFront], routes: list[Route]
) -> tuple[dict[str, dict], dict[str, set[str]], dict[str, list[dict]]]:
    """Données des fichiers du front, appelants de chaque route, non reliés."""
    formes = [(r, segments_de_route(r.chemin)) for r in routes]
    appelee_par: dict[str, set[str]] = defaultdict(set)
    a_verifier: dict[str, list[dict]] = {"appels_sans_route": [], "adresses": []}
    donnees = {}
    for f in front:
        appels = []
        for a in f.appels:
            trouvees = sorted(
                r.id
                for r, segs in formes
                if a.segments is not None
                and r.methode == a.methode
                and segs == a.segments
            )
            for rid in trouvees:
                appelee_par[rid].add(f.chemin)
            entree = {
                "fichier": f.chemin,
                "ligne": a.ligne,
                "methode": a.methode,
                "adresse": a.adresse,
            }
            if a.segments is None:
                a_verifier["adresses"].append(entree)
            elif not trouvees:
                a_verifier["appels_sans_route"].append(entree)
            appels.append(
                {
                    "ligne": a.ligne,
                    "methode": a.methode,
                    "adresse": a.adresse,
                    "lisible": a.segments is not None,
                    "routes": trouvees,
                }
            )
        donnees[f.chemin] = {
            "lignes": f.lignes,
            "appels": appels,
            "routes": sorted({r for a in appels for r in a["routes"]}),
            "stores": f.stores,
            "composants": f.composants,
        }
    return donnees, appelee_par, a_verifier


def _tables(
    racine: Path, chemins: list[str]
) -> tuple[set[str], dict[str, AccesTables], dict[str, int]]:
    arbres = {c: _arbre(racine, c) for c in chemins}
    tables: set[str] = set()
    for arbre, _ in arbres.values():
        tables |= tables_creees(arbre)
    acces = {c: acces_tables(arbre, tables) for c, (arbre, _) in arbres.items()}
    appels = {c: appels_directs(texte) for c, (_, texte) in arbres.items()}
    return tables, acces, appels


def _signaler(a_verifier: dict[str, list[dict]]) -> list[str]:
    lignes = []
    for cle, libelle in (
        ("appels_sans_route", "appel sans route trouvée"),
        ("adresses", "adresse illisible"),
    ):
        for e in a_verifier[cle]:
            lignes.append(
                f"{libelle} : {e['fichier']}:{e['ligne']} {e['methode']} {e['adresse']}"
            )
    for e in a_verifier["tables_illisibles"]:
        lignes.append(f"table illisible : {e['fichier']}:{e['ligne']}")
    return lignes


def completer(carte: Carte, racine: Path, textes: Textes) -> None:
    """Ajoute la chaîne aux données de `carte` et ses signalements."""
    d = carte.donnees
    fichiers_py = sorted(d["fichiers"])
    routes = lire_routes(racine)
    front = lire_front(racine)
    donnees_front, appelee_par, a_verifier = _relier(front, routes)
    tables, acces, appels = _tables(racine, fichiers_py)

    routes_par_fichier: dict[str, list[str]] = defaultdict(list)
    for r in routes:
        routes_par_fichier[r.fichier].append(r.id)
    lue_par: dict[str, list[str]] = {t: [] for t in tables}
    ecrite_par: dict[str, list[str]] = {t: [] for t in tables}
    a_verifier["tables_illisibles"] = []
    for chemin in fichiers_py:
        f = d["fichiers"][chemin]
        f["couche"] = (
            "route"
            if routes_par_fichier.get(chemin)
            else ("stockage" if est_stockage(chemin) else "métier")
        )
        f["appels_base"] = appels[chemin]
        f["routes"] = routes_par_fichier.get(chemin, [])
        f["tables_lues"] = sorted(acces[chemin].lues)
        f["tables_ecrites"] = sorted(acces[chemin].ecrites)
        for t in acces[chemin].lues:
            lue_par[t].append(chemin)
        for t in acces[chemin].ecrites:
            ecrite_par[t].append(chemin)
        a_verifier["tables_illisibles"] += [
            {"fichier": chemin, "ligne": n} for n in acces[chemin].illisibles
        ]

    for chemin, f in donnees_front.items():
        phrase = textes.phrases.get(chemin)
        if phrase is None:
            carte.signalements.append(f"fichier sans phrase : {chemin}")
        f["phrase"] = phrase or PAS_DE_PHRASE
        f["systeme"] = ECRANS["id"]

    d["routes"] = {
        r.id: {
            "methode": r.methode,
            "chemin": r.chemin,
            "fichier": r.fichier,
            "fonction": r.fonction,
            "ligne": r.ligne,
            "base": r.base,
            "appelee_par": sorted(appelee_par.get(r.id, ())),
        }
        for r in routes
    }
    a_verifier["routes_sans_appel"] = [r.id for r in routes if r.id not in appelee_par]
    d["tables"] = {
        t: {"lue_par": sorted(lue_par[t]), "ecrite_par": sorted(ecrite_par[t])}
        for t in sorted(tables)
    }
    hors = sorted(
        ((c, n) for c, n in appels.items() if n and not est_stockage(c)),
        key=lambda cn: (-cn[1], cn[0]),
    )
    d["base"] = {"hors_stockage": sum(n for _, n in hors), "fichiers": hors}
    d["fichiers_front"] = donnees_front
    if donnees_front:
        d["ecrans"] = {**ECRANS, "fichiers": sorted(donnees_front)}
    d["a_verifier"] = a_verifier
    carte.signalements.extend(_signaler(a_verifier))
