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

# Après 3 essais en échec (le 1er + 2 reprises), une offre devient « illisible »
# et les runs suivants n'appellent plus le modèle pour elle (architecture.md TCK-273).
_MAX_EXTRACTION_ATTEMPTS = 3


@dataclass
class OfferOutcome:
    """Ce que la chaîne a fait d'une offre. Une seule des issues est remplie."""

    filter_reason: str | None = None
    perimetre_causes: list[str] = field(default_factory=list)
    category: Category | None = None
    parse_failed: bool = False
    # EXE-98 — None = succès (ou filtrée) | pending | retry | unreadable
    extraction_status: str | None = None
    extraction_attempts: int = 0


@dataclass
class RegisterOutcome:
    """Issue de `register_offer` : filtrée, ou enregistrée en attente d'extraction."""

    filtered: bool = False
    filter_reason: str | None = None


def register_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
) -> RegisterOutcome:
    """Filtre dur — aucun appel LLM. Une offre filtrée est persistée comme telle ;
    une offre qui passe est enregistrée « en attente d'extraction » avant tout appel
    au modèle (critère 1, EXE-98)."""
    filtered_out, filter_reason = apply_hard_filters(
        offer, profile.search_criteria, profile.zones
    )
    ad_lang = detect_ad_language(offer.description or "")
    if filtered_out:
        save_offer(
            conn,
            offer,
            filtered_out=True,
            filter_reason=filter_reason,
            ad_language=ad_lang,
        )
        return RegisterOutcome(filtered=True, filter_reason=filter_reason)

    save_offer(
        conn,
        offer,
        extraction_status="pending",
        extraction_attempts=0,
        ad_language=ad_lang,
    )
    return RegisterOutcome(filtered=False)


def extract_and_score(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
    attempts_before: int = 0,
) -> OfferOutcome:
    """Un essai d'extraction (1 appel LLM, retries internes compris) pour une offre
    déjà enregistrée en attente ou à refaire. Échec : incrémente les essais, aucun
    fait de repli n'est persisté ni scoré (architecture.md, exception TCK-273).
    Succès (y compris dégradé) : score, classe et persiste comme avant ce ticket."""
    facts = extract_facts(offer, model=model, host=host)
    if facts is None:
        attempts = attempts_before + 1
        status = "unreadable" if attempts >= _MAX_EXTRACTION_ATTEMPTS else "retry"
        save_offer(
            conn,
            offer,
            extraction_status=status,
            extraction_attempts=attempts,
        )
        return OfferOutcome(extraction_status=status, extraction_attempts=attempts)

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
            extraction_status=None,
            extraction_attempts=0,
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
        extraction_status=None,
        extraction_attempts=0,
    )
    return OfferOutcome(category=cat, parse_failed=facts.parse_failed)


def process_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
) -> OfferOutcome:
    """Filtre, extrait (1 essai), score, classe et persiste une offre déjà
    dédupliquée. Compose `register_offer` + `extract_and_score` (EXE-98) : le /run
    appelle les deux étapes séparément pour pouvoir reprendre, dans une passe à
    part, les offres laissées « en attente » par un run interrompu."""
    registered = register_offer(conn, offer, profile)
    if registered.filtered:
        return OfferOutcome(filter_reason=registered.filter_reason)
    return extract_and_score(
        conn, offer, profile, alias_table, model=model, host=host, attempts_before=0
    )
