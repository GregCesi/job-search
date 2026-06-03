"""
Filtres durs pré-scoring — défaut 2 (architecture.md §4, 0 LLM).

apply_hard_filters(offer, criteria) -> (filtered_out: bool, reason: str | None)

Règles :
- contract : alternance/stage → out ; CDI, CDD, LIB (freelance), MIS, autres → passe
- location : remote OK OU zone Strasbourg → passe ; sinon out
"""
from orchestrator.job_search.matching.profile import SearchCriteria
from orchestrator.job_search.sources.base import JobOffer

# Codes typeContrat France Travail qui signalent un stage / apprentissage
_STAGE_CODES = {"STA", "STG", "APP", "PRO"}

# Mots-clés dans nature_contract signalant stage/apprentissage (fallback si code absent)
_STAGE_KEYWORDS = ("stage", "apprentissage", "apprenti", "alternance")


def apply_hard_filters(
    offer: JobOffer,
    criteria: SearchCriteria,
) -> tuple[bool, str | None]:
    """
    Retourne (filtered_out, reason).
    filtered_out=True → offre exclue du scoring (jamais supprimée de la base).
    """
    # --- Contrat ---
    if offer.alternance:
        return True, "contract:alternance"

    ct = (offer.contract_type or "").upper().strip()
    if ct in _STAGE_CODES:
        return True, f"contract:{ct.lower()}"

    nature = (offer.nature_contract or "").lower()
    if any(kw in nature for kw in _STAGE_KEYWORDS):
        return True, "contract:stage"

    # --- Localisation ---
    remote_ok = offer.remote and "remote" in criteria.locations

    location_ok = False
    if "strasbourg_area" in criteria.locations:
        loc = (offer.location or "").upper()
        if loc.startswith("67") or "STRASBOURG" in loc or "BAS-RHIN" in loc:
            location_ok = True

    if not remote_ok and not location_ok:
        return True, "location:hors_zone"

    return False, None
