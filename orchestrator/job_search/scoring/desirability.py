"""
Calcul de désirabilité — l'offre m'intéresse-t-elle ?

Fonction pure (faits + critères profil) → Desirability.
Aucun appel LLM. Recalculable sans coût si le profil change (architecture.md §4).

Phase 1 : contract / location / full_time retirés — traités comme filtres durs en amont.
Phase 2 : domain passe de binaire à gradué par distance au cœur-cible.
"""
from pydantic import BaseModel

from orchestrator.job_search.matching.profile import SearchCriteria
from orchestrator.job_search.sources.base import ExtractedFacts

# Gradient de distance au domaine cible (profil Grégoire : AI Engineering).
# Calculé côté code, jamais produit en bloc par le LLM (architecture.md §3).
# 1.0 = cœur-cible, 0.0 = hors-domaine.
_DOMAIN_GRADIENT: dict[str, float] = {
    "ai_engineering":   1.0,   # cœur — AI/ML Engineer, LLM, agents, RAG
    "data_science":     0.7,   # near-cœur — ML/stats, overlap fort
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


def _domain_score(domain: str) -> float:
    """
    Distance graduée au domaine cible. Retourne 0.0 pour tout domaine inconnu.
    Indépendant du profil : la distance est une propriété de l'offre relative au cœur-cible.
    """
    return _DOMAIN_GRADIENT.get(domain.lower(), 0.0)


def compute_desirability(
    facts: ExtractedFacts,
    criteria: SearchCriteria,
) -> Desirability:
    """
    Calcule la désirabilité d'une offre.
    Phase 2 : un seul critère — domain gradué (0-100).
    criteria conservé en signature pour la traçabilité (preferred domains loggés dans detail).
    """
    d = _domain_score(facts.domain)
    score = round(d * 100, 1)

    return Desirability(
        score=score,
        detail={
            "domain": {
                "score": d,
                "value": facts.domain,
                "preferred": criteria.domains,
                "gradient": _DOMAIN_GRADIENT.get(facts.domain.lower(), 0.0),
            },
        },
    )
