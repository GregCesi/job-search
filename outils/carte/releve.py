"""Relevé de la carte (EXE-215) : `docs/carte/graphe.json`, et ce qui a changé
depuis le relevé d'avant.

Le relevé porte les fichiers, les flèches entre fichiers, les routes, les
tables lues et écrites par fichier et les appels directs à la base par fichier.
Il ne porte ni date ni commit, et s'écrit trié : deux lancements sur le même
code l'écrivent à l'identique, octet pour octet.
"""

from __future__ import annotations

import json
from pathlib import Path

from outils.carte.base import est_stockage


def releve(donnees: dict) -> dict:
    fichiers = donnees["fichiers"]
    tables = {
        c: {"lues": f["tables_lues"], "ecrites": f["tables_ecrites"]}
        for c, f in fichiers.items()
        if f.get("tables_lues") or f.get("tables_ecrites")
    }
    return {
        "fichiers": sorted([*fichiers, *donnees.get("fichiers_front", {})]),
        "fleches": sorted(
            [c, cible] for c, f in fichiers.items() for cible in f["importe"]
        ),
        "routes": {rid: r["fichier"] for rid, r in donnees.get("routes", {}).items()},
        "tables": tables,
        "appels_base": {
            c: f["appels_base"] for c, f in fichiers.items() if f.get("appels_base")
        },
    }


def lire_releve(chemin: Path) -> dict | None:
    if not chemin.is_file():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def ecrire_releve(contenu: dict, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(contenu, ensure_ascii=False, sort_keys=True, indent=1)
    chemin.write_text(texte + "\n", encoding="utf-8")


def _hors_stockage(appels: dict[str, int]) -> int:
    return sum(n for c, n in appels.items() if not est_stockage(c))


def comparer(avant: dict, apres: dict) -> list[str]:
    """Les changements, un par ligne, dans un ordre fixe."""
    lignes: list[str] = []
    f_avant, f_apres = set(avant.get("fichiers", [])), set(apres["fichiers"])
    lignes += [f"fichier nouveau : {c}" for c in sorted(f_apres - f_avant)]
    lignes += [f"fichier disparu : {c}" for c in sorted(f_avant - f_apres)]
    fl_avant = {tuple(f) for f in avant.get("fleches", [])}
    fl_apres = {tuple(f) for f in apres["fleches"]}
    lignes += [f"flèche nouvelle : {a} → {b}" for a, b in sorted(fl_apres - fl_avant)]
    lignes += [f"flèche disparue : {a} → {b}" for a, b in sorted(fl_avant - fl_apres)]
    ap_avant, ap_apres = avant.get("appels_base", {}), apres["appels_base"]
    for c in sorted(set(ap_avant) | set(ap_apres)):
        n_avant, n_apres = ap_avant.get(c, 0), ap_apres.get(c, 0)
        if n_avant != n_apres:
            lignes.append(f"appels directs à la base : {c} : {n_avant} → {n_apres}")
    h_avant, h_apres = _hors_stockage(ap_avant), _hors_stockage(ap_apres)
    if h_avant != h_apres:
        lignes.append(f"hors stockage : {h_avant} → {h_apres}")
    return lignes
