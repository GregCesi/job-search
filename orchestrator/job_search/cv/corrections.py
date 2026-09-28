"""Corrections manuelles du bloc compétences d'un CV généré (EXE-59, H1).

Frontière (architecture.md §4) : une correction est un calcul Python pur sur les
groupes/notions déjà produits par la génération — elle ne décide ni ne consulte
jamais le modèle (critère 13). Ce module ne touche ni à la DB ni au disque ;
la persistance vit dans `cv/service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.job_search.cv.skills import SkillGroup


class SkillAlreadyPresentError(ValueError):
    """La compétence est déjà présente dans un groupe ou dans les notions (critère 7)."""


class SkillNotFoundError(ValueError):
    """La compétence à retirer n'est présente ni dans un groupe ni dans les notions."""


class UnknownGroupError(ValueError):
    """Le groupe cible d'un ajout déclaré maîtrisé n'existe pas dans le CV."""


@dataclass(frozen=True)
class CorrectionOutcome:
    groupes: list[SkillGroup]
    notions: list[str]
    groupe: str | None  # groupe touché (ajout maîtrisé / retrait dans un groupe)
    maitrisee: bool  # True si l'action porte sur un groupe, False si sur les notions


def _all_items_lower(groupes: list[SkillGroup], notions: list[str]) -> set[str]:
    result = {item.lower() for g in groupes for item in g.items}
    result |= {n.lower() for n in notions}
    return result


def add_skill(
    groupes: list[SkillGroup],
    notions: list[str],
    competence: str,
    maitrisee: bool,
    groupe: str | None,
) -> CorrectionOutcome:
    """Ajoute `competence` en fin de groupe (déclarée maîtrisée) ou en fin de
    « Notions en : » (déclarée non maîtrisée) — critères 1, 3, 4. Refuse si la
    compétence est déjà présente, sous n'importe quelle forme (critère 7).
    """
    if competence.lower() in _all_items_lower(groupes, notions):
        raise SkillAlreadyPresentError(competence)

    if maitrisee:
        if groupe is None:
            raise UnknownGroupError("groupe requis pour un ajout déclaré maîtrisé")
        idx = next((i for i, g in enumerate(groupes) if g.label == groupe), None)
        if idx is None:
            raise UnknownGroupError(groupe)
        new_groupes = list(groupes)
        new_groupes[idx] = SkillGroup(
            label=groupes[idx].label, items=[*groupes[idx].items, competence]
        )
        return CorrectionOutcome(
            groupes=new_groupes, notions=list(notions), groupe=groupe, maitrisee=True
        )

    return CorrectionOutcome(
        groupes=list(groupes),
        notions=[*notions, competence],
        groupe=None,
        maitrisee=False,
    )


def remove_skill(
    groupes: list[SkillGroup], notions: list[str], competence: str
) -> CorrectionOutcome:
    """Retire `competence` de son groupe ou des notions (critères 5, 6). Lève si
    elle n'est présente ni dans un groupe ni dans les notions.
    """
    comp_lower = competence.lower()
    for i, g in enumerate(groupes):
        if comp_lower in {item.lower() for item in g.items}:
            new_items = [item for item in g.items if item.lower() != comp_lower]
            new_groupes = list(groupes)
            new_groupes[i] = SkillGroup(label=g.label, items=new_items)
            return CorrectionOutcome(
                groupes=new_groupes,
                notions=list(notions),
                groupe=g.label,
                maitrisee=True,
            )
    if comp_lower in {n.lower() for n in notions}:
        new_notions = [n for n in notions if n.lower() != comp_lower]
        return CorrectionOutcome(
            groupes=list(groupes), notions=new_notions, groupe=None, maitrisee=False
        )
    raise SkillNotFoundError(competence)
