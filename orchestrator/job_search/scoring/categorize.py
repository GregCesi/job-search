"""
Catégorisation désirabilité × atteignabilité → 4 cases (L11) + score intra-case (L12).

Fonction pure. 0 LLM (architecture.md §4).
Le score ne sort jamais de sa case — jamais comparé entre cases.
"""
from enum import Enum

from pydantic import BaseModel


class Category(str, Enum):
    parfait    = "parfait"      # désirable ET atteignable
    reve       = "reve"         # désirable, PAS atteignable (cible de progression)
    atteignable = "atteignable" # atteignable, PEU désirable (filet de sécurité)
    hors       = "hors"         # ni l'un ni l'autre


class ScoredOffer(BaseModel):
    category: Category
    score_in_category: float   # tri DANS la case — jamais comparé entre cases
    desirability: float        # axe brut conservé (observabilité)
    attainability: float       # axe brut conservé


# Seuils de catégorisation (calibrables sur les 60 offres — DECISIONS.md)
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


def score_in_category(category: Category, desirability: float, attainability: float) -> float:
    """
    Score de tri DANS une case. Ne sort jamais de sa case.

    parfait     → désirabilité (on veut le plus désirable en tête)
    reve        → désirabilité (pile distincte, aspirationnelle)
    atteignable → atteignabilité (on veut le plus faisable en tête)
    hors        → max(désirabilité, atteignabilité) (le moins mauvais en tête)
    """
    if category == Category.parfait:
        return round(desirability, 1)
    if category == Category.reve:
        return round(desirability, 1)
    if category == Category.atteignable:
        return round(attainability, 1)
    return round(max(desirability, attainability), 1)


def score_offer(desirability: float, attainability: float) -> ScoredOffer:
    """Point d'entrée unique : produit catégorie + score intra-case."""
    cat = categorize(desirability, attainability)
    sic = score_in_category(cat, desirability, attainability)
    return ScoredOffer(
        category=cat,
        score_in_category=sic,
        desirability=desirability,
        attainability=attainability,
    )
