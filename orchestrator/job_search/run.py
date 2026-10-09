"""
Orchestrateur principal — run matinal.

Usage:
    python -m orchestrator.job_search.run
    python -m orchestrator.job_search.run --profile profiles/gregoire.yaml --max 150
"""

import argparse
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH, REPO_ROOT

# EXE-100, critères 11/13 — 3 offres de suite sans réponse du modèle (vide ou
# modèle injoignable) arrêtent la phase en cours. Pas configurable : c'est un
# signal de panne, pas un réglage de volume (ceux-là vivent dans les variables
# d'environnement ci-dessous).
_NO_RESPONSE_STREAK_LIMIT = 3


@dataclass
class _TriPhaseReport:
    n_triees: int = 0
    a_relire_non_lues: list[tuple] = field(default_factory=list)
    stopped_no_response: bool = False


@dataclass
class _SecondPassReport:
    n_relues: int = 0
    # EXE-116, critère 8 — parmi `n_relues`, combien portaient kind="no_tech".
    n_relues_no_tech: int = 0
    batches_done: int = 0
    pause_seconds_total: float = 0.0
    stop_reason: str | None = None  # None | "cap" | "no_response"


@dataclass
class _SecondPassEntry:
    offer: object
    kind: str  # "category" | "unreadable" | "no_tech" (EXE-116)
    category: object | None = None
    attempts_before: int = 0


def _tri_phase(
    conn, pending_rows, profile, alias_table, *, tri_model, host
) -> _TriPhaseReport:
    """Trie chaque offre en attente/à refaire avec le modèle de tri. Arrête la
    phase après 3 offres de suite sans réponse du modèle (EXE-100, critère 11) :
    les offres non encore triées restent en attente d'extraction, et les 3 de
    la série qui ont déclenché l'arrêt ne comptent aucun essai (critère 12) —
    elles ne rejoignent donc jamais la file de seconde passe ci-dessous. Une
    réponse illisible mais non vide (critère 14) ne compte pas dans cette
    série : elle réhabilite le tampon accumulé jusque-là."""
    from orchestrator.job_search.ingestion import run_tri
    from orchestrator.job_search.storage.offers import offer_from_row

    a_relire_non_lues: list[tuple] = []
    streak_buffer: list[tuple] = []
    n_triees = 0
    stopped = False

    for row in pending_rows:
        offer = offer_from_row(row)
        print(f"[run] tri {offer.title[:55]}", flush=True)
        tri = run_tri(conn, offer, profile, alias_table, model=tri_model, host=host)
        n_triees += 1

        if (
            tri.needs_second_pass
            and tri.second_pass_reason == "unreadable"
            and tri.no_response
        ):
            streak_buffer.append((offer, row["extraction_attempts"] or 0))
            if len(streak_buffer) >= _NO_RESPONSE_STREAK_LIMIT:
                stopped = True
                streak_buffer = []
                print("         → tri arrêté : 3 offres de suite sans réponse")
                break
            continue

        a_relire_non_lues.extend(streak_buffer)
        streak_buffer = []

        if tri.needs_second_pass and tri.second_pass_reason == "unreadable":
            a_relire_non_lues.append((offer, row["extraction_attempts"] or 0))
        elif tri.needs_second_pass and tri.second_pass_reason == "no_tech":
            print("         → [sans techno] en attente de seconde passe")
        elif tri.needs_second_pass:
            print(
                f"         → [{tri.outcome.category.value}] en attente de seconde passe"
            )
        elif tri.outcome.perimetre_causes:
            causes = ",".join(tri.outcome.perimetre_causes)
            print(f"         → hors_perimetre: {causes}")
        elif tri.outcome.extraction_status == "missing_text":
            # EXE-117 — le tri a trouvé un texte devenu trop court (ex.
            # rattrapée par rattraper_filtre_contrat) sans appeler le modèle.
            print("         → texte manquant")
        else:
            print(f"         → [{tri.outcome.category.value}]")

    a_relire_non_lues.extend(streak_buffer)
    return _TriPhaseReport(
        n_triees=n_triees,
        a_relire_non_lues=a_relire_non_lues,
        stopped_no_response=stopped,
    )


def _resolve_second_pass_entry(
    conn, entry: _SecondPassEntry, profile, alias_table, *, model, host
):
    from orchestrator.job_search.ingestion import (
        resolve_category_second_pass,
        resolve_unreadable_with_precision,
    )

    if entry.kind in ("category", "no_tech"):
        return resolve_category_second_pass(
            conn,
            entry.offer,
            profile,
            alias_table,
            model=model,
            host=host,
            tri_category=entry.category,
            second_pass_attempts_before=entry.attempts_before,
        )
    return resolve_unreadable_with_precision(
        conn,
        entry.offer,
        profile,
        alias_table,
        model=model,
        host=host,
        attempts_before=entry.attempts_before,
    )


def _second_pass_batches(
    conn,
    queue: list[_SecondPassEntry],
    profile,
    alias_table,
    *,
    tri_model: str,
    precision_model: str,
    host: str,
    batch_size: int,
    pause_seconds: float,
    max_batches: int,
) -> _SecondPassReport:
    """Traite `queue` (parfait, puis rêve, puis non lues, puis sans techno —
    ordre posé par EXE-99/EXE-116, jamais changé ici) par lots de `batch_size`,
    avec une pause entre deux lots (jamais après le dernier) et un plafond de
    `max_batches` lots
    (EXE-100, critères 1-4, 9). Décharge le modèle de tri avant le premier lot
    (critère 5) et le modèle de précision au début de chaque pause (critère 6).
    Arrête les lots après 3 offres de suite sans réponse du modèle (critère 13)."""
    from orchestrator.job_search.scoring.extractor import unload_model

    report = _SecondPassReport()
    unload_model(host, tri_model)

    streak = 0
    idx = 0
    total = len(queue)
    stopped_by_streak = False

    while idx < total:
        batch = queue[idx : idx + batch_size]
        for entry in batch:
            outcome = _resolve_second_pass_entry(
                conn, entry, profile, alias_table, model=precision_model, host=host
            )
            report.n_relues += 1
            if entry.kind == "no_tech":
                report.n_relues_no_tech += 1
            print(f"[run] seconde passe {entry.offer.title[:55]}", flush=True)
            if outcome.no_response:
                streak += 1
                if streak >= _NO_RESPONSE_STREAK_LIMIT:
                    stopped_by_streak = True
                    break
            else:
                streak = 0
                if outcome.extraction_status == "second_pass_pending":
                    print(
                        f"         → en attente de seconde passe "
                        f"(essai {outcome.second_pass_attempts})"
                    )
                elif outcome.extraction_status == "retry":
                    print(f"         → à refaire (essai {outcome.extraction_attempts})")
                elif outcome.extraction_status == "unreadable":
                    print("         → illisible")
                elif outcome.category is not None:
                    print(f"         → [{outcome.category.value}]")
                elif outcome.perimetre_causes:
                    causes = ",".join(outcome.perimetre_causes)
                    print(f"         → hors_perimetre: {causes}")

        idx += len(batch)
        report.batches_done += 1

        if stopped_by_streak:
            report.stop_reason = "no_response"
            break
        if report.batches_done >= max_batches:
            if idx < total:
                report.stop_reason = "cap"
            break
        if idx >= total:
            break

        unload_model(host, precision_model)
        time.sleep(pause_seconds)
        report.pause_seconds_total += pause_seconds

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Job search morning run")
    parser.add_argument("--profile", default=str(PROFILE_PATH))
    parser.add_argument("--max", type=int, default=150, dest="max_results")
    parser.add_argument("--since-hours", type=int, default=24)
    parser.add_argument(
        "--no-remotive", action="store_true", help="Disable Remotive source"
    )
    parser.add_argument(
        "--no-indeed", action="store_true", help="Disable Indeed file source"
    )
    parser.add_argument("--no-eures", action="store_true", help="Disable EURES source")
    parser.add_argument(
        "--no-actiris", action="store_true", help="Disable Actiris source"
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    from orchestrator.job_search.digest.formatter import generate_digest
    from orchestrator.job_search.ingestion import (
        rattraper_filtre_contrat,
        rattraper_offres_categorisees_sans_texte,
        rattraper_sans_techno_tri,
        rattraper_texte_recu,
        register_offer,
    )
    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.aliases import load_alias_table
    from orchestrator.job_search.scoring.categorize import Category
    from orchestrator.job_search.scoring.extractor import (
        OllamaUnavailable,
        ensure_models_available,
        extraction_version,
        unload_model,
    )
    from orchestrator.job_search.sources.actiris import ActirisSource
    from orchestrator.job_search.sources.base import JobOffer, Source
    from orchestrator.job_search.sources.eures import EuresSource
    from orchestrator.job_search.sources.france_travail import FranceTravailSource
    from orchestrator.job_search.sources.indeed_file import IndeedFileSource
    from orchestrator.job_search.sources.remotive import RemotiveSource
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.dedup import filter_new
    from orchestrator.job_search.storage.offers import get_offers_since, offer_from_row
    from orchestrator.job_search.tracking import extraction_stats
    from orchestrator.job_search.tracking.mlflow_tracking import RunTracker

    # Modèle de tri (EXE-99, nouveau) — modèle de précision : OLLAMA_MODEL,
    # même emplacement qu'avant ce ticket (critère 15).
    tri_model = os.getenv("OLLAMA_MODEL_TRI", "llama3")
    precision_model = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # EXE-100, critères 3/4/9 — réglables par configuration, sans toucher au code.
    batch_size = int(os.getenv("SECOND_PASS_BATCH_SIZE", "10"))
    pause_seconds = float(os.getenv("SECOND_PASS_PAUSE_SECONDS", "300"))
    max_batches = int(os.getenv("SECOND_PASS_MAX_BATCHES", "5"))

    # EXE-163, critère 4 — réglables par configuration, sans toucher au code.
    actiris_since_days = int(os.getenv("ACTIRIS_SINCE_DAYS", "3"))
    actiris_detail_cap = int(os.getenv("ACTIRIS_DETAIL_CAP", "200"))

    run_at = datetime.now(timezone.utc)
    print(f"[run] démarrage {run_at.strftime('%Y-%m-%d %H:%M')} UTC", flush=True)

    # 1. Profil + alias
    profile, profile_hash = load_profile(args.profile)
    alias_table = load_alias_table(ALIAS_PATH)
    print(
        f"[run] profil : {profile.profile_id} role_ceiling={profile.role_ceiling.value} (hash={profile_hash[:8]}…)"
    )

    # 1.5 Ollama joignable + les deux modèles installés — sinon le run refuse de
    # démarrer, rien n'est écrit en base (EXE-99, critère 16).
    try:
        ensure_models_available(host, [tri_model, precision_model])
    except OllamaUnavailable as exc:
        print(f"[run] {exc}")
        return

    # EXE-105 — un run MLflow sous l'expérience « run-pipeline », avec les
    # réglages de ce run en paramètres. Si MLflow ne peut pas écrire (stockage
    # absent, verrouillé ou illisible), `tracker` reste inactif : tous ses
    # appels plus bas deviennent des no-op, et le run de la pipeline va au
    # bout sans lui (critère 9).
    tracker = RunTracker()
    tracker.start(
        {
            "tri_model": tri_model,
            "precision_model": precision_model,
            "tri_extraction_version": extraction_version(tri_model),
            "precision_extraction_version": extraction_version(precision_model),
            "batch_size": batch_size,
            "pause_seconds": pause_seconds,
            "max_batches": max_batches,
        }
    )

    # Valeurs par défaut : le bloc `finally` ci-dessous les journalise même si
    # une étape antérieure à leur calcul a levé une exception, pour que le run
    # MLflow porte les chiffres atteints (critère 8).
    n_offres_recuperees = 0
    n_offres_nouvelles = 0
    n_offres_filtrees = 0
    n_offres_rattrapees = 0
    n_offres_sans_texte_rattrapees = 0
    n_offres_sans_techno_rattrapees = 0
    n_offres_texte_recu = 0
    n_triees = 0
    n_relues = 0
    n_sans_techno_relues = 0
    n_sans_techno_changed = 0
    n_pending = 0
    n_retry = 0
    n_unreadable = 0
    n_texte_manquant = 0
    n_second_pass_pending = 0
    category_counts: Counter = Counter()
    n_hors_perimetre = 0
    tri_duration = 0.0
    second_pass_duration = 0.0
    second_pass_report = _SecondPassReport()
    stats = extraction_stats.ExtractionStats()
    digest_path = None
    stop_reason_final = "erreur"

    try:
        # 2. DB
        conn = get_connection()
        init_db(conn)

        # 2.5 Rattrapage filtre de contrat (EXE-114) — réévalue les offres déjà
        #     écartées contract:permanent/contract:full-time avec le filtre
        #     corrigé, avant que les offres en attente ne soient listées (5b) :
        #     une offre rattrapée qui n'est plus écartée est triée par ce run.
        n_offres_rattrapees = rattraper_filtre_contrat(conn, profile)
        print(f"[run] {n_offres_rattrapees} offres rattrapées (filtre contrat)")

        # 2.6 Rattrapage texte manquant (EXE-115, critère 7) — une offre déjà
        #     catégorisée ou hors-périmètre dont le texte nettoyé fait moins de
        #     50 caractères perd ses faits, sa catégorie et sa cause, et repasse
        #     « texte manquant ». Avant le fetch : ce run la trie si une source
        #     lui rapporte son texte juste après (2.7).
        n_offres_sans_texte_rattrapees = rattraper_offres_categorisees_sans_texte(conn)
        print(
            f"[run] {n_offres_sans_texte_rattrapees} offres repassées "
            "texte manquant (rattrapage)"
        )

        # 2.7 Rattrapage sans techno (EXE-116, critère 7) — une offre déjà
        #     persistée comme définitive hors-périmètre « sans techno » par le
        #     modèle de tri repasse en attente de seconde passe : ce run la
        #     relit avec le modèle de précision (5c), sans rappeler le tri.
        n_offres_sans_techno_rattrapees = rattraper_sans_techno_tri(conn, tri_model)
        print(
            f"[run] {n_offres_sans_techno_rattrapees} offres sans techno "
            "rattrapées (attente de seconde passe)"
        )

        # 3. Fetch — zones résolues depuis le profil
        active_zones = {
            name: profile.zones[name]
            for name in profile.search_criteria.locations
            if name in profile.zones
        }
        kw = profile.search_criteria.keywords
        ft_codes = [
            (zone, code) for zone in active_zones.values() for code in zone.insee
        ]
        per_source = max(30, args.max_results // max(len(ft_codes), 1))
        sources: list[Source] = [
            FranceTravailSource(keywords=kw, commune=code, max_results=per_source)
            for _zone, code in ft_codes
        ] or [FranceTravailSource(keywords=kw, max_results=args.max_results)]
        if not args.no_remotive:
            sources.append(RemotiveSource())
        if not args.no_indeed:
            sources.append(IndeedFileSource())
        if not args.no_eures and "belgique_area" in active_zones:
            sources.append(EuresSource(keywords=kw))
        if not args.no_actiris and "belgique_area" in active_zones:
            sources.append(
                ActirisSource(
                    since_days=actiris_since_days, detail_cap=actiris_detail_cap
                )
            )

        all_offers: list[JobOffer] = []
        for src in sources:
            label = type(src).__name__
            print(f"[run] fetch {label}…", flush=True)
            batch = src.fetch()
            print(f"[run] {label}: {len(batch)} offres")
            all_offers.extend(batch)
        n_offres_recuperees = len(all_offers)
        print(f"[run] {len(all_offers)} offres récupérées (total)")

        # 3.5 Rattrapage texte reçu (EXE-115, critère 6) — une offre en texte
        #     manquant dont ce fetch rapporte cette fois un texte suffisant
        #     repasse en attente d'extraction ; ce run la trie plus bas (5b).
        n_offres_texte_recu = rattraper_texte_recu(conn, all_offers)
        print(f"[run] {n_offres_texte_recu} offres ont retrouvé leur texte")

        # 4. Dédup
        new_offers = filter_new(conn, all_offers)
        n_offres_nouvelles = len(new_offers)
        print(
            f"[run] {len(new_offers)} nouvelles ({len(all_offers) - len(new_offers)} déjà vues)"
        )

        # 5a. Filtre dur + mise en attente — chaque offre nouvelle qui passe est
        #     enregistrée « en attente d'extraction » avant tout appel LLM (EXE-98)
        for i, offer in enumerate(new_offers, 1):
            registered = register_offer(conn, offer, profile)
            if registered.filtered:
                n_offres_filtrees += 1
                print(
                    f"[run] ({i}/{len(new_offers)}) {offer.title[:55]} "
                    f"→ filtré : {registered.filter_reason}"
                )
            elif registered.missing_text:
                print(
                    f"[run] ({i}/{len(new_offers)}) {offer.title[:55]} → texte manquant"
                )

        # 5b. Tri (LLM, modèle de tri) + Score (Python) + Persist — reprend TOUTES
        #     les offres en attente ou à refaire, y compris celles laissées par un
        #     run précédent interrompu (EXE-98). Chaque offre est triée avant que la
        #     première seconde passe n'ait lieu (EXE-99, critère 11). Arrêt anticipé
        #     après 3 offres de suite sans réponse du modèle (EXE-100, critère 11).
        pending_rows = conn.execute(
            "SELECT * FROM offers WHERE extraction_status IN ('pending', 'retry') "
            "ORDER BY fetched_at"
        ).fetchall()
        print(
            f"[run] {len(pending_rows)} offres à trier (en attente + à refaire)",
            flush=True,
        )

        # EXE-105 — chronomètre le tri et collecte, par modèle, la durée et
        # l'échec de chaque appel LLM de la cascade (tri + seconde passe),
        # pour les métriques MLflow du run (critères 5-6).
        with extraction_stats.collect() as stats:
            tri_started = time.perf_counter()
            tri_report = _tri_phase(
                conn,
                pending_rows,
                profile,
                alias_table,
                tri_model=tri_model,
                host=host,
            )
            tri_duration = time.perf_counter() - tri_started
            n_triees = tri_report.n_triees

            # 5c. Seconde passe (LLM, modèle de précision) — parfait, puis rêve,
            #     puis les offres que le tri n'a pas lues (EXE-99, critère 12),
            #     puis les offres « sans techno » (EXE-116, critères 1-2).
            #     Les offres « second_pass_pending » d'un run précédent sont
            #     reprises ici aussi, sans rappeler le modèle de tri (critère 8).
            #     EXE-100 : traitées par lots avec pause (critères 1-9) et arrêt
            #     sur absence de réponse (critère 13).
            second_pass_queue: list[_SecondPassEntry] = []
            for cat in (Category.parfait, Category.reve):
                rows = conn.execute(
                    "SELECT * FROM offers WHERE extraction_status = 'second_pass_pending' "
                    "AND category = ? ORDER BY fetched_at",
                    (cat.value,),
                ).fetchall()
                for row in rows:
                    second_pass_queue.append(
                        _SecondPassEntry(
                            offer=offer_from_row(row),
                            kind="category",
                            category=cat,
                            attempts_before=row["second_pass_attempts"] or 0,
                        )
                    )
            for offer, attempts_before in tri_report.a_relire_non_lues:
                second_pass_queue.append(
                    _SecondPassEntry(
                        offer=offer, kind="unreadable", attempts_before=attempts_before
                    )
                )
            # EXE-116 — en dernier, après les trois premiers groupes.
            # `extraction_version IS NOT NULL` exclut les offres jamais lues par
            # aucun modèle (pas de version) — ce cas ne doit jamais être relu.
            rows_sans_techno = conn.execute(
                "SELECT * FROM offers WHERE extraction_status = 'second_pass_pending' "
                "AND hors_perimetre_reason = 'no_tech' "
                "AND extraction_version IS NOT NULL ORDER BY fetched_at"
            ).fetchall()
            no_tech_entries = [
                _SecondPassEntry(
                    offer=offer_from_row(row),
                    kind="no_tech",
                    attempts_before=row["second_pass_attempts"] or 0,
                )
                for row in rows_sans_techno
            ]
            second_pass_queue.extend(no_tech_entries)

            second_pass_started = time.perf_counter()
            second_pass_report = _second_pass_batches(
                conn,
                second_pass_queue,
                profile,
                alias_table,
                tri_model=tri_model,
                precision_model=precision_model,
                host=host,
                batch_size=batch_size,
                pause_seconds=pause_seconds,
                max_batches=max_batches,
            )
            second_pass_duration = time.perf_counter() - second_pass_started

            # EXE-116, critère 8 — parmi les offres sans techno mises en file
            # (ordre de file = ordre de traitement, cf. EXE-99), les premières
            # `n_relues_no_tech` sont celles effectivement relues ; les autres
            # (plafond atteint) restent en attente, inchangées.
            relued_no_tech = no_tech_entries[: second_pass_report.n_relues_no_tech]
            n_sans_techno_relues = len(relued_no_tech)
            n_sans_techno_changed = 0
            for entry in relued_no_tech:
                row = conn.execute(
                    "SELECT hors_perimetre_reason FROM offers "
                    "WHERE source = ? AND source_id = ?",
                    (entry.offer.source, entry.offer.source_id),
                ).fetchone()
                if row is not None and row["hors_perimetre_reason"] != "no_tech":
                    n_sans_techno_changed += 1
        n_relues = second_pass_report.n_relues

        n_pending = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE extraction_status = 'pending'"
        ).fetchone()[0]
        n_retry = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE extraction_status = 'retry'"
        ).fetchone()[0]
        n_unreadable = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE extraction_status = 'unreadable'"
        ).fetchone()[0]
        n_second_pass_pending = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE extraction_status = 'second_pass_pending'"
        ).fetchone()[0]
        n_texte_manquant = conn.execute(
            "SELECT COUNT(*) FROM offers WHERE extraction_status = 'missing_text'"
        ).fetchone()[0]
        print(
            f"[run] extraction — {n_pending} en attente, {n_retry} à refaire, "
            f"{n_unreadable} illisibles, {n_texte_manquant} texte manquant"
        )
        print(
            f"[run] {n_triees} offres triées, {n_relues} relues, "
            f"{n_second_pass_pending} en attente de seconde passe"
        )
        print(
            f"[run] {n_sans_techno_relues} offres sans techno relues, "
            f"{n_sans_techno_changed} ont changé de verdict"
        )

        reason_txt = {
            "cap": "plafond de lots atteint",
            "no_response": "modèle sans réponse",
            None: "terminé",
        }[second_pass_report.stop_reason]
        run_duration = (datetime.now(timezone.utc) - run_at).total_seconds()
        print(
            f"[run] seconde passe — {second_pass_report.batches_done} lots, "
            f"pauses {second_pass_report.pause_seconds_total:.0f}s, "
            f"run {run_duration:.0f}s, arrêt: {reason_txt}"
        )

        # EXE-105, critère 4 — catégorie finale et hors-périmètre, comptés
        # seulement parmi les offres nouvelles de ce run (pas tout l'historique
        # en base), et seulement si finalisées (`extraction_status IS NULL`).
        # Une offre classée parfait/rêve par le tri porte déjà sa catégorie en
        # base alors qu'elle attend encore la seconde passe (EXE-98, critère 2) :
        # sans ce filtre, elle compterait deux fois — ici, puis à nouveau une
        # fois la seconde passe terminée.
        for offer in new_offers:
            row = conn.execute(
                "SELECT category, perimetre_causes, extraction_status FROM offers "
                "WHERE source = ? AND source_id = ?",
                (offer.source, offer.source_id),
            ).fetchone()
            if row is None:
                continue
            cat, causes, extraction_status = row
            if extraction_status is not None:
                continue
            if cat:
                category_counts[cat] += 1
            elif causes:
                n_hors_perimetre += 1

        # 6. Digest
        since = run_at - timedelta(hours=args.since_hours)
        scored = get_offers_since(conn, since)
        digest = generate_digest(scored, run_at=run_at)
        print()
        print(digest)

        digest_path = REPO_ROOT / f"data/digest_{run_at.strftime('%Y%m%d_%H%M')}.txt"
        digest_path.write_text(digest)
        print(f"[run] digest → {digest_path}")

        stop_reason_final = second_pass_report.stop_reason or "termine"
    except BaseException:
        stop_reason_final = "erreur"
        raise
    finally:
        # EXE-100, critères 7/8 — à la fin d'un run qui va au bout comme sur une
        # erreur ou une interruption au clavier, les deux modèles sont déchargés
        # avant de rendre la main.
        unload_model(host, tri_model)
        unload_model(host, precision_model)

        # EXE-105, critère 8 — le run MLflow existe même si le run s'arrête sur
        # le plafond, sur l'absence de réponse du modèle ou sur une erreur : il
        # porte les chiffres atteints jusque-là et la raison de l'arrêt.
        run_duration_final = (datetime.now(timezone.utc) - run_at).total_seconds()
        tracker.log_metrics(
            {
                "offres_recuperees": float(n_offres_recuperees),
                "offres_nouvelles": float(n_offres_nouvelles),
                "offres_filtrees": float(n_offres_filtrees),
                "offres_triees": float(n_triees),
                "offres_relues": float(n_relues),
                "offres_en_attente_extraction": float(n_pending),
                "offres_a_refaire": float(n_retry),
                "offres_illisibles": float(n_unreadable),
                "offres_en_attente_seconde_passe": float(n_second_pass_pending),
                "categorie_parfait": float(
                    category_counts.get(Category.parfait.value, 0)
                ),
                "categorie_reve": float(category_counts.get(Category.reve.value, 0)),
                "categorie_atteignable": float(
                    category_counts.get(Category.atteignable.value, 0)
                ),
                "categorie_hors": float(category_counts.get(Category.hors.value, 0)),
                "offres_hors_perimetre": float(n_hors_perimetre),
                "tri_extractions_echouees": float(stats.failure_count(tri_model)),
                "tri_duree_mediane_s": stats.median_duration(tri_model),
                "precision_extractions_echouees": float(
                    stats.failure_count(precision_model)
                ),
                "precision_duree_mediane_s": stats.median_duration(precision_model),
                "duree_run_s": run_duration_final,
                "duree_tri_s": tri_duration,
                "duree_seconde_passe_s": second_pass_duration,
                "duree_pauses_s": second_pass_report.pause_seconds_total,
            }
        )
        tracker.log_param("stop_reason", stop_reason_final)
        if digest_path is not None:
            tracker.log_artifact(digest_path)
        tracker.end()


if __name__ == "__main__":
    main()
