"""
Catégorisation désirabilité × atteignabilité → 4 cases.

Fonction pure. 0 LLM (architecture.md §4).
d/a sont des détails de calcul internes — jamais persistés ni exposés.
"""
from enum import Enum


class Category(str, Enum):
    parfait    = "parfait"      # désirable ET atteignable
    reve       = "reve"         # désirable, PAS atteignable (cible de progression)
    atteignable = "atteignable" # atteignable, PEU désirable (filet de sécurité)
    hors       = "hors"         # ni l'un ni l'autre


# Seuils de catégorisation (calibrables — DECISIONS.md)
DESIRABILITY_THRESHOLD = 50.0   # score > seuil → "désirable"
ATTAINABILITY_THRESHOLD = 40.0  # score > seuil → "atteignable"


def categorize(desirability: float, attainability: float) -> Category:
    """
    Croisement de 2 seuils → 1 case parmi 4.
    Fonction pure, aucun état externe.
    """
    is_desired    = desirability  > DESIRABILITY_THRESHOLD
    is_attainable = attainability > ATTAINABILITY_THRESHOLD

    if is_desired and is_attainable:
        return Category.parfait
    if is_desired and not is_attainable:
        return Category.reve
    if not is_desired and is_attainable:
        return Category.atteignable
    return Category.hors
