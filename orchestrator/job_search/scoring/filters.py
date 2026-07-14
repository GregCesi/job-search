"""
Filtres durs pré-scoring — défaut 2 (architecture.md §4, 0 LLM).

apply_hard_filters(offer, criteria, zones) -> (filtered_out: bool, reason: str | None)

Règles :
- contract : alternance/stage → toujours out ;
             si contract_types renseigné, seuls les types listés passent
- location : remote OK OU zone matching (depuis profil.zones) → passe ; sinon out
"""
from __future__ import annotations

from orchestrator.job_search.matching.profile import SearchCriteria, Zone
from orchestrator.job_search.sources.base import JobOffer

# Codes typeContrat France Travail qui signalent un stage / apprentissage
_STAGE_CODES = {"STA", "STG", "APP", "PRO"}

# Mots-clés dans nature_contract signalant stage/apprentissage (fallback si code absent)
_STAGE_KEYWORDS = ("stage", "apprentissage", "apprenti", "alternance")

# Mapping code contrat France Travail → clé profil
_CONTRACT_MAP: dict[str, str] = {
    "CDI": "cdi",
    "CDD": "cdd",
    "LIB": "freelance",
    "MIS": "mis",
}


def apply_hard_filters(
    offer: JobOffer,
    criteria: SearchCriteria,
    zones: dict[str, Zone] | None = None,
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

    if criteria.contract_types and ct:
        mapped = _CONTRACT_MAP.get(ct, ct.lower())
        if mapped not in criteria.contract_types:
            return True, f"contract:{mapped}"

    # --- Localisation ---
    remote_ok = offer.remote and "remote" in criteria.locations

    location_ok = False
    loc = (offer.location or "").upper()
    for area_name in criteria.locations:
        if area_name == "remote":
            continue
        zone = (zones or {}).get(area_name)
        if not zone:
            continue
        if any(loc.startswith(d) for d in zone.dept):
            location_ok = True
            break
        if any(kw.upper() in loc for kw in zone.keywords):
            location_ok = True
            break

    if not remote_ok and not location_ok:
        return True, "location:hors_zone"

    return False, None
