"""
Filtres durs pré-scoring — défaut 2 (architecture.md §4, 0 LLM).

apply_hard_filters(offer, criteria) -> (filtered_out: bool, reason: str | None)

Règles :
- contract : alternance/stage → out ; CDI, CDD, LIB (freelance), MIS, autres → passe
- location : remote OK OU zone matching → passe ; sinon out
"""
from orchestrator.job_search.matching.profile import SearchCriteria
from orchestrator.job_search.sources.base import JobOffer

# Codes typeContrat France Travail qui signalent un stage / apprentissage
_STAGE_CODES = {"STA", "STG", "APP", "PRO"}

# Mots-clés dans nature_contract signalant stage/apprentissage (fallback si code absent)
_STAGE_KEYWORDS = ("stage", "apprentissage", "apprenti", "alternance")

# Registre des zones géographiques reconnues.
# dept_prefixes : début du code postal/dept dans le champ location.
# keywords : mots-clés supplémentaires matchés dans location (uppercase).
AREA_RULES: dict[str, dict] = {
    "strasbourg_area": {"dept_prefixes": ["67"], "keywords": ["STRASBOURG", "BAS-RHIN"]},
    "reims_area":      {"dept_prefixes": ["51"], "keywords": ["REIMS", "MARNE"]},
    "paris_area":      {"dept_prefixes": ["75", "92", "93", "94"], "keywords": ["PARIS", "ILE-DE-FRANCE"]},
    "lyon_area":       {"dept_prefixes": ["69"], "keywords": ["LYON", "RHONE", "RHÔNE"]},
    "toulouse_area":   {"dept_prefixes": ["31"], "keywords": ["TOULOUSE", "HAUTE-GARONNE"]},
}


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
    loc = (offer.location or "").upper()
    for area_name in criteria.locations:
        rule = AREA_RULES.get(area_name)
        if not rule:
            continue
        if any(loc.startswith(p) for p in rule["dept_prefixes"]):
            location_ok = True
            break
        if any(kw in loc for kw in rule["keywords"]):
            location_ok = True
            break

    if not remote_ok and not location_ok:
        return True, "location:hors_zone"

    return False, None
