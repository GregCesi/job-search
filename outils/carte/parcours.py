"""Vue d'ensemble et parcours de la carte (EXE-215), lus dans le fichier de textes.

Une étape de parcours cite un élément de la carte et un seul : un fichier
(`fichier`), une route (`route`, sous la forme « POST /chemin ») ou une table
(`table`). Elle peut nommer une fonction (`fonction`) et renvoyer à une règle
(`regle`). Une étape dont l'élément manque à la carte est une erreur : la
commande rend 1 et nomme le parcours et le numéro de l'étape.
"""

from __future__ import annotations

from outils.carte.lecture import Textes

GENRES = ("fichier", "route", "table")
_COUCHE_DU_GENRE = {"route": "route", "table": "table"}


def _genre(etape: dict) -> tuple[str, str] | None:
    cites = [(g, str(etape[g])) for g in GENRES if g in etape]
    return cites[0] if len(cites) == 1 else None


def _couche(genre: str, element: str, donnees: dict) -> str | None:
    if genre in _COUCHE_DU_GENRE:
        present = element in donnees.get(genre + "s", {})
        return _COUCHE_DU_GENRE[genre] if present else None
    if element in donnees.get("fichiers_front", {}):
        return "écran"
    fichier = donnees["fichiers"].get(element)
    return fichier.get("couche") if fichier else None


def parcours_de_la_carte(textes: Textes, donnees: dict) -> tuple[list[dict], list[str]]:
    """Les parcours prêts pour la page, et les erreurs : étape sans élément ou
    dont l'élément manque à la carte."""
    rendus: list[dict] = []
    erreurs: list[str] = []
    for p in textes.parcours:
        nom = str(p.get("nom", ""))
        etapes = []
        for n, etape in enumerate(p.get("etape", []), 1):
            cite = _genre(etape)
            if cite is None:
                erreurs.append(
                    f"parcours « {nom} », étape {n} : l'étape doit citer un "
                    "fichier, une route ou une table, et un seul"
                )
                continue
            genre, element = cite
            couche = _couche(genre, element, donnees)
            if couche is None:
                erreurs.append(
                    f"parcours « {nom} », étape {n} : {genre} absent de la carte : "
                    f"{element}"
                )
                continue
            etapes.append(
                {
                    "genre": genre,
                    "element": element,
                    "couche": couche,
                    "phrase": str(etape.get("phrase", "")),
                    "fonction": str(etape.get("fonction", "")),
                    "regle": str(etape.get("regle", "")),
                }
            )
        rendus.append({"id": str(p.get("id", "")), "nom": nom, "etapes": etapes})
    return rendus, erreurs


def ensemble(textes: Textes) -> dict:
    """Les blocs de la vue d'ensemble et leurs flèches, tels qu'écrits, avec la
    place de chaque bloc sur le dessin (colonne, ligne) et le libellé court de
    chaque flèche (EXE-216). Une place absente vaut -1 : la page en choisit une."""
    blocs = [
        {
            "id": str(b["id"]),
            "nom": str(b["nom"]),
            "role": str(b.get("role", "")),
            "lien": str(b.get("lien", "")),
            "colonne": int(b.get("colonne", -1)),
            "ligne": int(b.get("ligne", -1)),
        }
        for b in textes.blocs
    ]
    fleches = [
        {
            "de": str(f["de"]),
            "vers": str(f["vers"]),
            "libelle": str(f["libelle"]),
            "court": str(f.get("court", "")),
        }
        for f in textes.fleches_blocs
    ]
    return {"blocs": blocs, "fleches": fleches}
