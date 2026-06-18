"""
Calcul d'atteignabilité — puis-je décrocher cette offre maintenant ?

Fonction pure (faits + profil) → Attainability.
Matching = recouvrement de listes (architecture.md §4). Aucun LLM.
"""
from enum import Enum

from pydantic import BaseModel

from orchestrator.job_search.matching.profile import MasteryLevel, Profile
from orchestrator.job_search.scoring.aliases import AliasTable, canonicalize
from orchestrator.job_search.sources.base import ExtractedFacts, SeniorityLevel, TechRequirement

_SENIORITY_ORDER: dict[SeniorityLevel, int] = {
    SeniorityLevel.junior: 0,
    SeniorityLevel.intermediate: 1,
    SeniorityLevel.senior: 2,
    SeniorityLevel.lead: 3,
}

# Niveaux de maîtrise considérés comme "connu" pour le matching
_KNOWN = {MasteryLevel.working, MasteryLevel.confirmed}


# ---------------------------------------------------------------------------
# Phase 3 — atteignabilité refondue (L7→L9). 0 LLM (architecture.md §4).
# ---------------------------------------------------------------------------

# Poids par importance — calibrables (cf. architecture.md §3 + DECISIONS.md)
_IMPORTANCE_WEIGHTS: dict[str, float] = {
    "core":         3.0,
    "required":     2.0,
    "nice_to_have": 0.5,
}


def _canonical_profile_skills(
    profile: Profile, table: AliasTable,
) -> dict[str, int]:
    """Index canonicalisé des skills du profil : {canonical_form: level}."""
    result: dict[str, int] = {}
    for name, entry in profile.skills.items():
        c = canonicalize(name, table)
        if c is not None:  # pas un exclu
            result[c] = entry.level
    return result


def _canonical_profile_desires(
    profile: Profile, table: AliasTable,
) -> dict[str, int]:
    """Index canonicalisé des desires du profil : {canonical_form: desire}."""
    result: dict[str, int] = {}
    for name, entry in profile.skills.items():
        c = canonicalize(name, table)
        if c is not None:
            result[c] = entry.desire
    return result


def _compute_attain_tech(
    techs_required: list[TechRequirement],
    profile: Profile,
    table: AliasTable,
) -> tuple[float, list[str], list[str]]:
    """
    Moyenne pondérée des niveaux profil sur les technos de l'offre.
    attain_tech = Σ(level_i × weight_i) / Σ(weight_i) × 10  → 0-100.
    Techno absente du profil : level=0 (neutre, pas de pénalité explicite mais dilue).
    Techno exclue (canonicalize → None) : retirée du calcul (ni matchée ni manquante).
    Retourne (score, techs_matched, techs_missing).
    """
    if not techs_required:
        return 100.0, [], []

    canonical_levels = _canonical_profile_skills(profile, table)

    weighted_sum = 0.0
    total_weight = 0.0
    matched: list[str] = []
    missing: list[str] = []

    for tech in techs_required:
        canonical = canonicalize(tech.name, table)
        if canonical is None:
            # Exclu (bruit/non-tech) — retiré du calcul
            continue

        weight = _IMPORTANCE_WEIGHTS.get(tech.importance, 1.0)
        level = canonical_levels.get(canonical)

        if level is not None:
            matched.append(tech.name)
            weighted_sum += level * weight
        else:
            missing.append(tech.name)
            # level=0 implicite — contribue 0 au numérateur, weight au dénominateur

        total_weight += weight

    if total_weight == 0:
        return 100.0, [], []

    attain_tech = (weighted_sum / total_weight) * 10
    return round(attain_tech, 1), matched, missing


_ROLE_ORDER: dict[str, int] = {"ic": 0, "lead": 1, "manager": 2}

# Scores du portail gradué (calibrables — DECISIONS.md)
_ATTAIN_ROLE_SCORES: list[float] = [100.0, 40.0, 0.0]  # même cran, +1, +2 et plus


def _compute_attain_role(role_level: str, profile: Profile) -> float:
    """
    Portail gradué : compare le rôle de l'offre au plafond déclaré du profil.
    Même cran ou en-dessous → 100. Un cran au-dessus → 40. Deux crans → 0.
    Non-compensation : ce score est pris en min() avec attain_tech, jamais moyenné.
    """
    offer_rank = _ROLE_ORDER.get(role_level, 0)
    ceiling_rank = _ROLE_ORDER.get(profile.role_ceiling.value, 0)
    gap = offer_rank - ceiling_rank
    gap = max(0, gap)  # en-dessous du plafond = 0 = pas de pénalité
    idx = min(gap, len(_ATTAIN_ROLE_SCORES) - 1)
    return _ATTAIN_ROLE_SCORES[idx]


class Attainability(BaseModel):
    score: float                           # 0-100 = min(attain_tech, attain_role)
    attain_tech: float                     # moyenne pondérée par importance
    attain_role: float                     # portail gradué IC/lead/manager
    techs_matched: list[str]              # observable (conservé)
    techs_missing: list[str]              # observable (conservé)
    blocked_by: str | None                # "tech" | "role" | None — quel axe gouverne


def compute_attainability(facts: ExtractedFacts, profile: Profile, table: AliasTable) -> Attainability:
    """
    Atteignabilité refondue : min(attain_tech, attain_role). 0 LLM (architecture.md §4).
    Non-compensation : un bon axe ne rachète jamais un axe disqualifiant.
    """
    attain_tech, matched, missing = _compute_attain_tech(facts.techs_required, profile, table)
    attain_role = _compute_attain_role(facts.role_level.value, profile)

    score = round(min(attain_tech, attain_role), 1)

    if attain_tech <= attain_role:
        blocked_by = "tech" if attain_tech < attain_role else None
    else:
        blocked_by = "role"

    return Attainability(
        score=score,
        attain_tech=attain_tech,
        attain_role=attain_role,
        techs_matched=matched,
        techs_missing=missing,
        blocked_by=blocked_by,
    )
