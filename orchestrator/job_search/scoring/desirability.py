"""
Calcul de désirabilité — l'offre m'intéresse-t-elle ?

Fonction pure (faits + offre + critères profil) → Desirability.
Aucun appel LLM. Recalculable sans coût si le profil change (architecture.md §4).
"""
from pydantic import BaseModel

from orchestrator.job_search.matching.profile import SearchCriteria
from orchestrator.job_search.sources.base import ExtractedFacts, JobOffer

# Mapping profil → codes typeContrat France Travail
_PROFILE_TO_FT: dict[str, set[str]] = {
    "cdi": {"CDI"},
    "freelance": {"LIB"},
    "cdd": {"CDD"},
}


class Desirability(BaseModel):
    score: float        # 0-100, agrégé côté code
    detail: dict        # détail par critère — observable


def _domain_score(domain: str, preferred: list[str]) -> float:
    return 1.0 if domain in preferred else 0.0


def _location_score(offer: JobOffer, locations: list[str]) -> float:
    if offer.remote and "remote" in locations:
        return 1.0
    if "strasbourg_area" in locations:
        loc = (offer.location or "").upper()
        if loc.startswith("67") or "STRASBOURG" in loc or "BAS-RHIN" in loc:
            return 1.0
    return 0.0


def _contract_score(offer: JobOffer, contract_types: list[str]) -> float:
    if offer.alternance:
        return 0.0
    ct = (offer.contract_type or "").upper()
    preferred_codes: set[str] = set()
    for pref in contract_types:
        preferred_codes.update(_PROFILE_TO_FT.get(pref, set()))
    if ct in preferred_codes:
        return 1.0
    if ct == "CDD":
        return 0.2  # acceptable mais non préféré
    return 0.0


def compute_desirability(
    offer: JobOffer,
    facts: ExtractedFacts,
    criteria: SearchCriteria,
) -> Desirability:
    """
    Calcule la désirabilité d'une offre par rapport aux critères du profil.
    Weights : domain 40 %, location 35 %, contract 20 %, full_time 5 %.
    """
    d = _domain_score(facts.domain, criteria.domains)
    l = _location_score(offer, criteria.locations)
    c = _contract_score(offer, criteria.contract_types)
    f = 0.0 if offer.full_time is False else 1.0  # None → on ne pénalise pas

    score = round((0.40 * d + 0.35 * l + 0.20 * c + 0.05 * f) * 100, 1)

    return Desirability(
        score=score,
        detail={
            "domain":   {"score": d, "value": facts.domain,       "preferred": criteria.domains},
            "location": {"score": l, "remote": offer.remote,      "location": offer.location},
            "contract": {"score": c, "type": offer.contract_type, "alternance": offer.alternance},
            "full_time": {"score": f, "value": offer.full_time},
        },
    )
