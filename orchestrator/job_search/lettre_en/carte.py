"""État de la version anglaise tel que la carte de la lettre l'affiche
(EXE-209) : le front n'en calcule rien (frontend.md).

Python pur : ni base ni modèle.
"""

from __future__ import annotations

GENERER = "Générer la version anglaise"
REGENERER = "Régénérer la version anglaise"
MESSAGE_PERIMEE = (
    "La version anglaise date d'avant ta dernière modification du texte français"
)


def carte_anglaise(texte_fr: str | None, version: dict | None) -> dict:
    """`texte_fr` : texte français courant d'une lettre terminée, `None` si la
    lettre n'est pas terminée. `version` : la version anglaise stockée, ou
    `None`.

    Bouton : « Générer » sans version anglaise (critère 1), « Régénérer » quand
    le texte français a changé depuis la traduction (critère 14), aucun sinon."""
    if texte_fr is None:
        return {
            "disponible": False,
            "texte": None,
            "perimee": False,
            "message": None,
            "bouton": None,
        }
    if version is None:
        return {
            "disponible": True,
            "texte": None,
            "perimee": False,
            "message": None,
            "bouton": GENERER,
        }
    perimee = version["texte_fr_source"] != texte_fr
    return {
        "disponible": True,
        "texte": version["texte"],
        "perimee": perimee,
        "message": MESSAGE_PERIMEE if perimee else None,
        "bouton": REGENERER if perimee else None,
    }
