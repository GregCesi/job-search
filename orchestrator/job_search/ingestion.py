"""Chaîne d'une offre nouvelle : filtre dur → extraction (LLM) → scoring
(Python) → porte hors périmètre → persistance.

Une seule implémentation, appelée par la boucle du /run (`run.py`) et par l'ajout
à la main (`ajout/service.py`, EXE-79) : pour une offre et des faits extraits donnés,
les deux rendent le même classement.

EXE-99 (architecture.md, exception TCK-273) — cascade à deux modèles : le modèle
de tri extrait d'abord (`run_tri`). S'il classe l'offre parfait/rêve ou échoue à
la lire, le modèle de précision la relit dans le même run
(`resolve_category_second_pass` / `resolve_unreadable_with_precision`). Les deux
modèles reçoivent le même prompt (`extract_facts`, inchangé) ; seul le nom du
modèle varie.

EXE-116 (architecture.md, exception TCK-273, 3e cas) — une offre que le tri
range hors-périmètre pour la seule cause « sans techno » suit la même seconde
passe que parfait/rêve (`resolve_category_second_pass`, `tri_category=None`),
en dernier dans la file (après parfait, rêve, non lues).
"""

import sqlite3
import time
from dataclasses import dataclass, field

from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.ad_language import detect_ad_language
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.scoring.attainability import (
    Attainability,
    compute_attainability,
)
from orchestrator.job_search.scoring.categorize import Category, categorize
from orchestrator.job_search.scoring.desirability import compute_desirability
from orchestrator.job_search.scoring.extractor import (
    NoResponseFromModel,
    extract_facts,
    extraction_version,
)
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.scoring.hors_perimetre import (
    HorsPerimetreCause,
    derive_hors_perimetre,
)
from orchestrator.job_search.sources.base import ExtractedFacts, JobOffer
from orchestrator.job_search.storage.offers import offer_from_row, save_offer
from orchestrator.job_search.tracking import extraction_stats

# Après 3 essais en échec (le 1er + 2 reprises), une offre devient « illisible »
# et les runs suivants n'appellent plus le modèle pour elle (architecture.md TCK-273).
_MAX_EXTRACTION_ATTEMPTS = 3

# EXE-99 — après 3 secondes passes en échec sur une offre classée parfait/rêve
# par le tri, elle sort de l'attente et garde les faits du tri (critère 9).
_MAX_SECOND_PASS_ATTEMPTS = 3

# EXE-99 — catégories qui déclenchent une seconde passe du modèle de précision.
_SECOND_PASS_CATEGORIES = {Category.parfait, Category.reve}

# EXE-115 (architecture.md, « Offre sans texte ») — en deçà de ce nombre de
# caractères de texte nettoyé, une offre n'est envoyée à aucun modèle.
_MIN_TEXT_LENGTH = 50


def _cleaned_text_len(offer: JobOffer) -> int:
    return len((offer.description or "").strip())


@dataclass
class OfferOutcome:
    """Ce que la chaîne a fait d'une offre. Une seule des issues est remplie."""

    filter_reason: str | None = None
    perimetre_causes: list[str] = field(default_factory=list)
    category: Category | None = None
    parse_failed: bool = False
    # EXE-98/EXE-99/EXE-115 — None = succès (ou filtrée) | pending | retry |
    # unreadable | second_pass_pending | missing_text
    extraction_status: str | None = None
    extraction_attempts: int = 0
    second_pass_attempts: int = 0
    # EXE-100 — vide à chaque tentative, ou modèle injoignable (critère 11),
    # distinct d'une réponse illisible mais non vide (critère 14). Ne compte
    # jamais comme un essai (critères 12/13) : aucune persistance n'accompagne
    # ce cas, l'offre reste dans l'état où elle était avant l'appel.
    no_response: bool = False


@dataclass
class TriOutcome:
    """Issue du modèle de tri (EXE-99). `outcome` est déjà persisté : soit
    définitif (pas de seconde passe), soit transitoire et visible
    (`second_pass_pending`, faits et catégorie du tri). Si le tri a échoué à
    lire l'offre, rien n'est encore persisté — `needs_second_pass=True`,
    `second_pass_reason="unreadable"` — c'est à l'appelant de retenter avec le
    modèle de précision avant de décider du compteur d'essais (critère 10)."""

    outcome: OfferOutcome = field(default_factory=OfferOutcome)
    needs_second_pass: bool = False
    # "category" | "unreadable" | "no_tech" (EXE-116)
    second_pass_reason: str | None = None
    # EXE-100, critère 11 — vrai si le tri n'a pas pu lire l'offre faute de
    # réponse (vide ou modèle injoignable), distinct d'une réponse illisible.
    no_response: bool = False


@dataclass
class RegisterOutcome:
    """Issue de `register_offer` : filtrée, texte manquant, ou enregistrée en
    attente d'extraction."""

    filtered: bool = False
    filter_reason: str | None = None
    # EXE-115 — texte nettoyé trop court : aucun appel LLM, l'offre attend son
    # texte (architecture.md, « Offre sans texte »).
    missing_text: bool = False


def register_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
) -> RegisterOutcome:
    """Filtre dur — aucun appel LLM. Une offre filtrée est persistée comme telle ;
    une offre dont le texte nettoyé fait moins de `_MIN_TEXT_LENGTH` caractères est
    persistée « texte manquant », sans appel au modèle (critère 1, EXE-115) ; une
    offre qui passe les deux est enregistrée « en attente d'extraction » avant tout
    appel au modèle (critère 1, EXE-98)."""
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

    if _cleaned_text_len(offer) < _MIN_TEXT_LENGTH:
        save_offer(
            conn,
            offer,
            extraction_status="missing_text",
            extraction_attempts=0,
            ad_language=ad_lang,
        )
        return RegisterOutcome(filtered=False, missing_text=True)

    save_offer(
        conn,
        offer,
        extraction_status="pending",
        extraction_attempts=0,
        ad_language=ad_lang,
    )
    return RegisterOutcome(filtered=False)


def rattraper_offres_categorisees_sans_texte(conn: sqlite3.Connection) -> int:
    """Critère 7, EXE-115 — une offre déjà en base, non écartée par un filtre, dont
    le texte nettoyé fait moins de `_MIN_TEXT_LENGTH` caractères et qui porte encore
    une catégorie ou une cause hors périmètre (classée avant ce ticket, ou par une
    source qui a d'abord rapporté un texte suffisant puis plus rien) : elle perd ses
    faits, sa catégorie et sa cause, et repasse « texte manquant ». Aucun appel LLM
    (architecture.md §4). Les champs écrits par review humaine (`categorie_corrigee`,
    `remarque`, `reviewed_at`) ne sont pas touchés par `save_offer`."""
    rows = conn.execute(
        "SELECT * FROM offers WHERE filtered_out = 0 "
        "AND (category IS NOT NULL OR perimetre_causes IS NOT NULL)"
    ).fetchall()

    n = 0
    for row in rows:
        offer = offer_from_row(row)
        if _cleaned_text_len(offer) >= _MIN_TEXT_LENGTH:
            continue
        save_offer(
            conn,
            offer,
            extraction_status="missing_text",
            extraction_attempts=0,
            second_pass_attempts=0,
            ad_language=row["ad_language"],
        )
        n += 1
    return n


def rattraper_sans_techno_tri(conn: sqlite3.Connection, tri_model: str) -> int:
    """Critère 7, EXE-116 — une offre déjà en base dont l'extraction_version
    nomme le modèle de tri et dont la cause hors-périmètre est « sans techno »
    (persistée comme définitive avant ce ticket) repasse en attente de seconde
    passe : ce run la relit avec le modèle de précision (architecture.md,
    exception TCK-273, 3e cas). Aucun appel LLM ici."""
    rows = conn.execute(
        "SELECT source, source_id FROM offers "
        "WHERE hors_perimetre_reason = 'no_tech' AND extraction_status IS NULL "
        "AND extraction_version LIKE ?",
        (f"{tri_model}|%",),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE offers SET extraction_status = 'second_pass_pending', "
            "second_pass_attempts = 0 WHERE source = ? AND source_id = ?",
            (row["source"], row["source_id"]),
        )
    conn.commit()
    return len(rows)


def rattraper_texte_recu(conn: sqlite3.Connection, offers: list[JobOffer]) -> int:
    """Critère 6, EXE-115 — une offre déjà en base « texte manquant » dont une
    source rapporte à nouveau un texte de `_MIN_TEXT_LENGTH` caractères ou plus
    (ex. Indeed relit tous les fichiers déposés à chaque run) : le texte est
    enregistré et l'offre repasse en attente d'extraction — ce run la trie plus
    bas. Ne touche aucune offre qui n'est pas en texte manquant."""
    n = 0
    for offer in offers:
        if _cleaned_text_len(offer) < _MIN_TEXT_LENGTH:
            continue
        row = conn.execute(
            "SELECT * FROM offers WHERE (source = ? AND source_id = ?) "
            "OR fingerprint = ? LIMIT 1",
            (offer.source, offer.source_id, offer.fingerprint),
        ).fetchone()
        if row is None or row["extraction_status"] != "missing_text":
            continue
        save_offer(
            conn,
            offer,
            extraction_status="pending",
            extraction_attempts=0,
            ad_language=row["ad_language"],
        )
        n += 1
    return n


# EXE-114 — raisons posées par l'ancienne version du filtre de contrat (table de
# correspondance sans valeur Indeed) : seules celles-ci sont rattrapables.
_RATTRAPABLE_FILTER_REASONS = ("contract:permanent", "contract:full-time")


def rattraper_filtre_contrat(conn: sqlite3.Connection, profile: Profile) -> int:
    """Ré-évalue, avec la version courante d'`apply_hard_filters`, les offres déjà
    écartées sous `contract:permanent` ou `contract:full-time` — raisons produites
    par l'ancienne table de correspondance, qui ne connaissait aucune valeur Indeed
    (EXE-114). Filtre pur Python, aucun appel LLM (architecture.md §4) : une offre
    qui ne doit plus être écartée repasse « en attente d'extraction » et ce run la
    trie ; une offre toujours écartée pour une autre raison garde cette raison.
    Retourne le nombre d'offres rattrapées (résultat changé)."""
    rows = conn.execute(
        "SELECT * FROM offers WHERE filtered_out = 1 AND filter_reason IN (?, ?)",
        _RATTRAPABLE_FILTER_REASONS,
    ).fetchall()

    n_rattrapees = 0
    for row in rows:
        offer = offer_from_row(row)
        filtered_out, filter_reason = apply_hard_filters(
            offer, profile.search_criteria, profile.zones
        )
        if filtered_out and filter_reason == row["filter_reason"]:
            continue

        n_rattrapees += 1
        if filtered_out:
            save_offer(
                conn,
                offer,
                filtered_out=True,
                filter_reason=filter_reason,
                ad_language=row["ad_language"],
            )
        else:
            save_offer(
                conn,
                offer,
                extraction_status="pending",
                extraction_attempts=0,
                ad_language=row["ad_language"],
            )

    return n_rattrapees


def _extract_with_no_response_flag(
    offer: JobOffer, model: str, host: str
) -> tuple[ExtractedFacts | None, bool]:
    """Appelle `extract_facts` (seul point d'appel au LLM, inchangé pour les
    appelants existants) et distingue une absence de réponse (EXE-100, critère
    11) d'une extraction illisible mais non vide (critère 14, `facts is None`
    sans lever).

    EXE-105 — chronomètre cet appel et le signale au collecteur de stats du
    run (no-op hors d'un run suivi, cf. tracking/extraction_stats.py) : échec
    au sens de ce compteur = `facts is None` (illisible ou sans réponse,
    scoring.md), jamais une extraction dégradée (`parse_failed=True` avec
    faits présents)."""
    started = time.perf_counter()
    try:
        facts = extract_facts(offer, model=model, host=host)
        extraction_stats.record(model, time.perf_counter() - started, facts is None)
        return facts, False
    except NoResponseFromModel:
        extraction_stats.record(model, time.perf_counter() - started, True)
        return None, True


def _score(
    facts: ExtractedFacts, offer: JobOffer, profile: Profile, alias_table: AliasTable
) -> tuple[
    JobOffer, Attainability, list[HorsPerimetreCause], str | None, Category | None
]:
    """Calcule d/a, la porte hors-périmètre et la catégorie à partir de faits.
    Ne persiste rien. `cat=None` si hors-périmètre : la gate prime, catégorize()
    n'est même pas appelée (architecture.md §4, étage 5)."""
    offer = offer.model_copy(update={"extracted_facts": facts})
    d = compute_desirability(facts, profile.search_criteria, profile, alias_table)
    a = compute_attainability(facts, profile, alias_table)
    hp_causes = derive_hors_perimetre(
        facts,
        title=offer.title,
        description=offer.description,
        contract_type=offer.contract_type,
        nature_contract=offer.nature_contract,
        alternance=offer.alternance,
    )
    ad_lang = detect_ad_language(offer.description or "")
    cat = None if hp_causes else categorize(d.score, a.score)
    return offer, a, hp_causes, ad_lang, cat


def _persist_final(
    conn: sqlite3.Connection,
    offer: JobOffer,
    facts: ExtractedFacts,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
) -> OfferOutcome:
    """Persiste une extraction réussie comme définitive : hors-périmètre, ou
    catégorie — jamais de seconde passe au-delà de ce point (EXE-99)."""
    offer, a, hp_causes, ad_lang, cat = _score(facts, offer, profile, alias_table)
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
            second_pass_attempts=0,
        )
        return OfferOutcome(
            perimetre_causes=causes_str, parse_failed=facts.parse_failed
        )

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
        second_pass_attempts=0,
    )
    return OfferOutcome(category=cat, parse_failed=facts.parse_failed)


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
    Succès (y compris dégradé) : score, classe et persiste comme avant ce ticket.

    EXE-99 — réutilisée telle quelle pour résoudre le cas « le tri n'a pas pu
    lire l'offre » : appelée avec le modèle de précision, elle compte comme le
    seul essai supplémentaire si les deux modèles échouent (critère 10).

    EXE-100, critères 11-13 — une absence de réponse (vide ou modèle
    injoignable) ne persiste rien et ne compte aucun essai : l'offre reste
    dans son état actuel, à la différence d'une réponse illisible mais non
    vide (comportement EXE-98/99 inchangé)."""
    facts, no_response = _extract_with_no_response_flag(offer, model, host)
    if facts is None:
        if no_response:
            return OfferOutcome(extraction_attempts=attempts_before, no_response=True)
        attempts = attempts_before + 1
        status = "unreadable" if attempts >= _MAX_EXTRACTION_ATTEMPTS else "retry"
        save_offer(
            conn,
            offer,
            extraction_status=status,
            extraction_attempts=attempts,
        )
        return OfferOutcome(extraction_status=status, extraction_attempts=attempts)

    return _persist_final(conn, offer, facts, profile, alias_table, model=model)


def run_tri(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
) -> TriOutcome:
    """Premier appel, modèle de tri (EXE-99, architecture.md TCK-273). Persiste
    immédiatement si l'offre n'a pas besoin de seconde passe (hors-périmètre,
    atteignable, hors), ou si elle en a besoin par catégorie (parfait/rêve) :
    visible tout de suite avec les faits et la catégorie du tri
    (`second_pass_pending`, critère 2 de EXE-98 — la vue candidat la montre).
    Si le tri échoue à lire l'offre, rien n'est persisté ici : c'est à
    l'appelant de retenter avec le modèle de précision avant de décider du
    compteur d'essais (critère 10)."""
    facts, no_response = _extract_with_no_response_flag(offer, model, host)
    if facts is None:
        return TriOutcome(
            needs_second_pass=True,
            second_pass_reason="unreadable",
            no_response=no_response,
        )

    offer, a, hp_causes, ad_lang, cat = _score(facts, offer, profile, alias_table)
    version = None if facts.parse_failed else extraction_version(model)

    if hp_causes:
        causes_str = [c.value for c in hp_causes]
        # EXE-116 — « sans techno » est la seule cause hors-périmètre incertaine
        # (architecture.md, exception TCK-273, 3e cas) : elle attend une seconde
        # passe au lieu d'être persistée comme définitive. mgmt_role/contrat
        # restent définitives, inchangées.
        if HorsPerimetreCause.no_tech in hp_causes:
            save_offer(
                conn,
                offer,
                perimetre_causes=causes_str,
                techs_matched=a.techs_matched,
                techs_missing=a.techs_missing,
                ad_language=ad_lang,
                extraction_version=version,
                extraction_status="second_pass_pending",
                extraction_attempts=0,
                second_pass_attempts=0,
            )
            return TriOutcome(
                outcome=OfferOutcome(
                    perimetre_causes=causes_str,
                    parse_failed=facts.parse_failed,
                    extraction_status="second_pass_pending",
                ),
                needs_second_pass=True,
                second_pass_reason="no_tech",
            )

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
            second_pass_attempts=0,
        )
        return TriOutcome(
            outcome=OfferOutcome(
                perimetre_causes=causes_str, parse_failed=facts.parse_failed
            )
        )

    if cat in _SECOND_PASS_CATEGORIES:
        save_offer(
            conn,
            offer,
            category=cat,
            techs_matched=a.techs_matched,
            techs_missing=a.techs_missing,
            ad_language=ad_lang,
            extraction_version=version,
            extraction_status="second_pass_pending",
            extraction_attempts=0,
            second_pass_attempts=0,
        )
        return TriOutcome(
            outcome=OfferOutcome(
                category=cat,
                parse_failed=facts.parse_failed,
                extraction_status="second_pass_pending",
            ),
            needs_second_pass=True,
            second_pass_reason="category",
        )

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
        second_pass_attempts=0,
    )
    return TriOutcome(
        outcome=OfferOutcome(category=cat, parse_failed=facts.parse_failed)
    )


def resolve_unreadable_with_precision(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
    attempts_before: int = 0,
) -> OfferOutcome:
    """Le tri n'a pas pu lire l'offre : le modèle de précision l'extrait dans le
    même run (architecture.md, TCK-273, critère 4). Échec des deux modèles : un
    seul essai de plus (critère 10) — `extract_and_score` porte déjà cette
    règle, il suffit de l'appeler avec le modèle de précision."""
    return extract_and_score(
        conn,
        offer,
        profile,
        alias_table,
        model=model,
        host=host,
        attempts_before=attempts_before,
    )


def resolve_category_second_pass(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    model: str,
    host: str,
    tri_category: Category | None,
    second_pass_attempts_before: int = 0,
) -> OfferOutcome:
    """Seconde passe sur une offre classée parfait/rêve par le tri (EXE-99).
    Succès : les faits du modèle de précision remplacent ceux du tri et la
    catégorie est recalculée sur eux (critère 5). Échec : l'offre garde les
    faits et la catégorie du tri déjà persistés — une mise à jour ciblée des
    deux seules colonnes concernées, pour ne pas les écraser (critère 7).
    Après `_MAX_SECOND_PASS_ATTEMPTS` échecs, elle sort de l'attente
    (critère 9).

    EXE-100, critère 13 — une absence de réponse ne persiste rien et ne
    compte aucun essai : l'offre reste « en attente de seconde passe »."""
    facts, no_response = _extract_with_no_response_flag(offer, model, host)
    if facts is not None:
        return _persist_final(conn, offer, facts, profile, alias_table, model=model)

    if no_response:
        return OfferOutcome(
            category=tri_category,
            extraction_status="second_pass_pending",
            second_pass_attempts=second_pass_attempts_before,
            no_response=True,
        )

    attempts = second_pass_attempts_before + 1
    status = None if attempts >= _MAX_SECOND_PASS_ATTEMPTS else "second_pass_pending"
    conn.execute(
        "UPDATE offers SET extraction_status = ?, second_pass_attempts = ? "
        "WHERE source = ? AND source_id = ?",
        (status, attempts, offer.source, offer.source_id),
    )
    conn.commit()
    return OfferOutcome(
        category=tri_category, extraction_status=status, second_pass_attempts=attempts
    )


def process_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    profile: Profile,
    alias_table: AliasTable,
    *,
    tri_model: str,
    tri_host: str,
    precision_model: str,
    precision_host: str,
) -> OfferOutcome:
    """Filtre, trie, relit si nécessaire, score, classe et persiste une offre
    déjà dédupliquée — la cascade complète pour une seule offre (EXE-99,
    critère 17 : l'ajout à la main suit la même cascade que le /run). Compose
    `register_offer` + `run_tri` + la résolution de seconde passe adaptée.

    EXE-115 — un texte nettoyé trop court (« texte manquant ») arrête la cascade
    au même point qu'un filtre dur : aucun appel LLM, ici comme dans le /run."""
    registered = register_offer(conn, offer, profile)
    if registered.filtered:
        return OfferOutcome(filter_reason=registered.filter_reason)
    if registered.missing_text:
        return OfferOutcome(extraction_status="missing_text")

    tri = run_tri(conn, offer, profile, alias_table, model=tri_model, host=tri_host)
    if not tri.needs_second_pass:
        return tri.outcome

    if tri.second_pass_reason == "unreadable":
        return resolve_unreadable_with_precision(
            conn,
            offer,
            profile,
            alias_table,
            model=precision_model,
            host=precision_host,
            attempts_before=0,
        )

    return resolve_category_second_pass(
        conn,
        offer,
        profile,
        alias_table,
        model=precision_model,
        host=precision_host,
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )
