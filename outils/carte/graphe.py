"""Graphe des imports directs, lu par grimp sans importer ni exécuter le code.

grimp parse les fichiers ; il ne retrouve les paquets que par leur
emplacement sur `sys.path`, c'est pourquoi la racine lue y est placée en tête.
`cache_dir=None` : grimp n'écrit aucun dossier de cache dans le dépôt.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import grimp

PAQUETS = ("api", "orchestrator", "tests")


def imports_directs(racine: Path) -> dict[str, set[str]]:
    """Pour chaque module des paquets présents sous `racine`, les modules de ces
    mêmes paquets qu'il importe directement."""
    paquets = [p for p in PAQUETS if (racine / p).is_dir()]
    if not paquets:
        return {}
    sys.path.insert(0, str(racine))
    importlib.invalidate_caches()
    try:
        graphe = grimp.build_graph(*paquets, cache_dir=None)
    finally:
        sys.path.remove(str(racine))
    return {m: set(graphe.find_modules_directly_imported_by(m)) for m in graphe.modules}


def chemin_de_test(module: str, racine: Path) -> str | None:
    """`tests.test_cv` → `tests/test_cv.py` s'il existe sous `racine`."""
    if not module.startswith("tests."):
        return None
    base = module.replace(".", "/")
    for chemin in (f"{base}.py", f"{base}/__init__.py"):
        if (racine / chemin).is_file():
            return chemin
    return None
