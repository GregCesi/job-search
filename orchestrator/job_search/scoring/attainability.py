"""
Calcul d'atteignabilité — puis-je décrocher cette offre maintenant ?

Fonction pure (faits + profil) → Attainability.
Matching = recouvrement de listes (architecture.md §4). Aucun LLM.
"""
from enum import Enum

from pydantic import BaseModel

from orchestrator.job_search.matching.profile import MasteryLevel, Profile
from orchestrator.job_search.sources.base import ExtractedFacts, SeniorityLevel

_SENIORITY_ORDER: dict[SeniorityLevel, int] = {
    SeniorityLevel.junior: 0,
    SeniorityLevel.intermediate: 1,
    SeniorityLevel.senior: 2,
    SeniorityLevel.lead: 3,
}

# Niveaux de maîtrise considérés comme "connu" pour le matching
_KNOWN = {MasteryLevel.working, MasteryLevel.confirmed}

# Alias de technos équivalentes (équivalences évidentes seulement — architecture.md §4).
# postgres → sql, sqlite → sql, etc. Pas de jugement de niveau (chantier 2).
_TECH_ALIASES: dict[str, str] = {
    # Famille SQL → "sql"
    "postgresql": "sql",
    "postgres":   "sql",
    "mysql":      "sql",
    "mariadb":    "sql",
    "mssql":      "sql",
    "bigquery":   "sql",
    "snowflake":  "sql",
    "supabase":   "sql",
    # SQLite variante
    "sqlite3":    "sqlite",
    # LangChain écosystème
    "langsmith":  "langchain",
}


def _canonical(tech: str) -> str:
    """Normalise une techno vers son alias canonique si équivalence évidente."""
    return _TECH_ALIASES.get(tech.lower(), tech.lower())


class ReachLevel(str, Enum):
    at_level = "at_level"
    one_step_up = "one_step_up"
    out_of_reach = "out_of_reach"


class Attainability(BaseModel):
    level: ReachLevel
    techs_matched: list[str]
    techs_missing: list[str]   # observable par construction
    seniority_gap: int          # >0 = offre au-dessus, 0 = même palier, <0 = en-dessous


def compute_attainability(facts: ExtractedFacts, profile: Profile) -> Attainability:
    """
    Calcule l'atteignabilité de l'offre par rapport au profil.
    Règle : gap >= 2 → out_of_reach ; gap == 1 → one_step_up ; gap <= 0 → at_level.
    Si gap == 1 ET couverture techno < 25 % → out_of_reach (trop loin sur les deux axes).
    """
    gap = (
        _SENIORITY_ORDER[facts.seniority_required]
        - _SENIORITY_ORDER[profile.seniority]
    )

    techs_matched = [
        t for t in facts.techs_required
        if profile.tech_level(_canonical(t)) in _KNOWN
    ]
    techs_missing = [
        t for t in facts.techs_required
        if profile.tech_level(_canonical(t)) not in _KNOWN  # None + notions = gap réel
    ]

    n_req = len(facts.techs_required)
    coverage = len(techs_matched) / n_req if n_req > 0 else 1.0

    if gap >= 2:
        level = ReachLevel.out_of_reach
    elif gap == 1:
        level = (
            ReachLevel.out_of_reach
            if n_req > 0 and coverage < 0.25
            else ReachLevel.one_step_up
        )
    else:
        level = ReachLevel.at_level

    return Attainability(
        level=level,
        techs_matched=techs_matched,
        techs_missing=techs_missing,
        seniority_gap=gap,
    )
