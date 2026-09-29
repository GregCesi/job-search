"""Chaîne d'une offre nouvelle : filtre dur → extraction (LLM, 1 appel) → scoring
(Python) → porte hors périmètre → persistance.

Une seule implémentation, appelée par la boucle du /run (`run.py`) et par l'ajout
à la main (`ajout/service.py`, EXE-79) : pour une offre et des faits extraits donnés,
les deux rendent le même classement.
"""

import sqlite3
from dataclasses import dataclass, field

from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.ad_language import detect_ad_language
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.scoring.attainability import compute_attainability
from orchestrator.job_search.scoring.categorize import Category, categorize
from orchestrator.job_search.scoring.desirability import compute_desirability
from orchestrator.job_search.scoring.extractor import extract_facts, extraction_version
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.scoring.hors_perimetre import derive_hors_perimetre
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.storage.offers import save_offer


@dataclass
class OfferOutcome:
    """Ce que la chaîne a fait d'une offre. Une seule des trois issues est remplie."""

    filter_reason: str | None = None
    perimetre_causes: list[str] = field(default_factory=list)
    category: Category | None = None
    parse_failed: bool = False


def process_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
) -> OfferOutcome:
    """Filtre, extrait, score, classe et persiste une offre déjà dédupliquée."""
    filtered_out, filter_reason = apply_hard_filters(
        offer, profile.search_criteria, profile.zones
    )
    if filtered_out:
        ad_lang = detect_ad_language(offer.description or "")
        save_offer(
            conn,
            offer,
            filtered_out=True,
            filter_reason=filter_reason,
            ad_language=ad_lang,
        )
        return OfferOutcome(filter_reason=filter_reason)

    facts = extract_facts(offer, model=model, host=host)
    offer = offer.model_copy(update={"extracted_facts": facts})

    d = compute_desirability(facts, profile.search_criteria, profile, alias_table)
    a = compute_attainability(facts, profile, alias_table)

    # Gate hors-périmètre APRÈS d/a — scores conservés intacts (0 LLM, §4)
    hp_causes = derive_hors_perimetre(
        facts,
        title=offer.title,
        description=offer.description,
        contract_type=offer.contract_type,
        nature_contract=offer.nature_contract,
        alternance=offer.alternance,
    )
    ad_lang = detect_ad_language(offer.description or "")
    version = None if facts.parse_failed else extraction_version(model)
    if hp_causes:
        causes_str = [c.value for c in hp_causes]
        save_offer(
            conn,
            offer,
            perimetre_causes=causes_str,
            techs_matched=a.techs_matched,
            techs_missing=a.techs_missing,
            ad_language=ad_lang,
            extraction_version=version,
        )
        return OfferOutcome(
            perimetre_causes=causes_str, parse_failed=facts.parse_failed
        )

    cat = categorize(d.score, a.score)
    save_offer(
        conn,
        offer,
        category=cat,
        techs_matched=a.techs_matched,
        techs_missing=a.techs_missing,
        ad_language=ad_lang,
        extraction_version=version,
    )
    return OfferOutcome(category=cat, parse_failed=facts.parse_failed)
