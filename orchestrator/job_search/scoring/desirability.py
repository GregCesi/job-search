"""
Calcul de désirabilité — l'offre m'intéresse-t-elle ?

Fonction pure (faits + critères profil) → Desirability.
Aucun appel LLM. Recalculable sans coût si le profil change (architecture.md §4).

Phase 1 : contract / location / full_time retirés — traités comme filtres durs en amont.
Phase 2 : domain passe de binaire à gradué par distance au cœur-cible.
"""
from pydantic import BaseModel

from orchestrator.job_search.matching.profile import Profile, SearchCriteria
from orchestrator.job_search.scoring.aliases import AliasTable, canonicalize
from orchestrator.job_search.scoring.attainability import _canonical_profile_desires
from orchestrator.job_search.sources.base import ExtractedFacts

# Gradient de distance au domaine cible (profil Grégoire : AI Engineering).
# Calculé côté code, jamais produit en bloc par le LLM (architecture.md §3).
# 1.0 = cœur-cible, 0.0 = hors-domaine.
_DOMAIN_GRADIENT: dict[str, float] = {
    "ai_engineering":   1.0,   # cœur — AI/ML Engineer, LLM, agents, RAG
    "data_science":     0.4,   # adjacent — ML/stats, overlap mais pas cœur-cible
    "data_engineering": 0.5,   # adjacent — Python pipelines, SQL, data infra
    "backend":          0.5,   # adjacent — FastAPI/Python back, APIs REST
    "fullstack":        0.25,  # éloigné — charge frontend non désirable
    "devops":           0.2,   # périphérique — infra/cloud, peu de code métier
    "embedded":         0.1,   # très éloigné
    "other":            0.0,   # hors-domaine — commercial, management, support
}


class Desirability(BaseModel):
    score: float        # 0-100, agrégé côté code
    detail: dict        # détail par critère — observable


# Facteur minimal quand desire=0 sur toutes les technos connues (calibrable)
_DESIRE_FLOOR = 0.5


def _desire_factor(facts: ExtractedFacts, profile: Profile, table: AliasTable) -> float:
    """
    Facteur d'envie-techno ∈ [_DESIRE_FLOOR, 1.0].
    Inconnu neutre : si aucune techno de l'offre n'est dans le profil → 1.0.
    desire=0 sur toutes les connues → _DESIRE_FLOOR (score de domaine divisé par 2 max).
    desire=10 sur toutes → 1.0 (pas de modification).
    Techs exclues (canonicalize → None) ignorées.
    """
    canonical_desires = _canonical_profile_desires(profile, table)
    desires: list[int] = []
    for t in facts.techs_required:
        c = canonicalize(t.name, table)
        if c is None:
            continue  # exclu
        desire = canonical_desires.get(c)
        if desire is not None:
            desires.append(desire)
    if not desires:
        return 1.0  # inconnu = neutre
    mean_desire = sum(desires) / len(desires) / 10.0  # → [0, 1]
    return _DESIRE_FLOOR + (1.0 - _DESIRE_FLOOR) * mean_desire


def _domain_score(domain: str) -> float:
    """
    Distance graduée au domaine cible. Retourne 0.0 pour tout domaine inconnu.
    Indépendant du profil : la distance est une propriété de l'offre relative au cœur-cible.
    """
    return _DOMAIN_GRADIENT.get(domain.lower(), 0.0)


def compute_desirability(
    facts: ExtractedFacts,
    criteria: SearchCriteria,
    profile: Profile | None = None,
    table: AliasTable | None = None,
) -> Desirability:
    """
    Calcule la désirabilité d'une offre.
    = domain_gradient × desire_factor × 100.
    desire_factor : envie moyenne sur les technos connues de l'offre (inconnu neutre = 1.0).
    profile=None : modulation désactivée (desire_factor=1.0).
    """
    d = _domain_score(facts.domain)
    factor = _desire_factor(facts, profile, table) if (profile is not None and table is not None) else 1.0
    score = round(d * factor * 100, 1)

    return Desirability(
        score=score,
        detail={
            "domain": {
                "score": d,
                "value": facts.domain,
                "preferred": criteria.domains,
                "gradient": _DOMAIN_GRADIENT.get(facts.domain.lower(), 0.0),
            },
            "desire": {
                "factor": round(factor, 3),
                "active": profile is not None,
            },
        },
    )
