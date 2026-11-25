"""Écriture de la page autonome : le gabarit `gabarit.html` et ses données.

Les données entrent dans un bloc `<script type="application/json">` ; `</`
y est échappé pour qu'aucun texte ne ferme le bloc. La page ne charge rien
d'ailleurs : styles et script sont dans le gabarit.
"""

from __future__ import annotations

import json
from pathlib import Path

GABARIT = Path(__file__).with_name("gabarit.html")
MARQUE = "__DONNEES__"


def rendre_page(donnees: dict) -> str:
    charge = json.dumps(donnees, ensure_ascii=False, sort_keys=True)
    return GABARIT.read_text(encoding="utf-8").replace(
        MARQUE, charge.replace("</", "<\\/")
    )


def ecrire_page(donnees: dict, sortie: Path) -> None:
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(rendre_page(donnees), encoding="utf-8")
