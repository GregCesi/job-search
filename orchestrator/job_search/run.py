"""
Orchestrateur principal — run matinal.

Usage:
    python -m orchestrator.job_search.run
    python -m orchestrator.job_search.run --profile profiles/gregoire.yaml --max 150
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH, REPO_ROOT


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
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    from orchestrator.job_search.digest.formatter import generate_digest
    from orchestrator.job_search.ingestion import (
        register_offer,
        resolve_category_second_pass,
        resolve_unreadable_with_precision,
        run_tri,
    )
    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.aliases import load_alias_table
    from orchestrator.job_search.scoring.categorize import Category
    from orchestrator.job_search.scoring.extractor import (
        OllamaUnavailable,
        ensure_models_available,
    )
    from orchestrator.job_search.sources.base import JobOffer, Source
    from orchestrator.job_search.sources.eures import EuresSource
    from orchestrator.job_search.sources.france_travail import FranceTravailSource
    from orchestrator.job_search.sources.indeed_file import IndeedFileSource
    from orchestrator.job_search.sources.remotive import RemotiveSource
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.dedup import filter_new
    from orchestrator.job_search.storage.offers import get_offers_since, offer_from_row

    # Modèle de tri (EXE-99, nouveau) — modèle de précision : OLLAMA_MODEL,
    # même emplacement qu'avant ce ticket (critère 15).
    tri_model = os.getenv("OLLAMA_MODEL_TRI", "llama3")
    precision_model = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

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

    # 2. DB
    conn = get_connection()
    init_db(conn)

    # 3. Fetch — zones résolues depuis le profil
    active_zones = {
        name: profile.zones[name]
        for name in profile.search_criteria.locations
        if name in profile.zones
    }
    kw = profile.search_criteria.keywords
    ft_codes = [(zone, code) for zone in active_zones.values() for code in zone.insee]
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

    all_offers: list[JobOffer] = []
    for src in sources:
        label = type(src).__name__
        print(f"[run] fetch {label}…", flush=True)
        batch = src.fetch()
        print(f"[run] {label}: {len(batch)} offres")
        all_offers.extend(batch)
    print(f"[run] {len(all_offers)} offres récupérées (total)")

    # 4. Dédup
    new_offers = filter_new(conn, all_offers)
    print(
        f"[run] {len(new_offers)} nouvelles ({len(all_offers) - len(new_offers)} déjà vues)"
    )

    # 5a. Filtre dur + mise en attente — chaque offre nouvelle qui passe est
    #     enregistrée « en attente d'extraction » avant tout appel LLM (EXE-98)
    for i, offer in enumerate(new_offers, 1):
        registered = register_offer(conn, offer, profile)
        if registered.filtered:
            print(
                f"[run] ({i}/{len(new_offers)}) {offer.title[:55]} "
                f"→ filtré : {registered.filter_reason}"
            )

    # 5b. Tri (LLM, modèle de tri) + Score (Python) + Persist — reprend TOUTES
    #     les offres en attente ou à refaire, y compris celles laissées par un
    #     run précédent interrompu (EXE-98). Chaque offre est triée avant que la
    #     première seconde passe n'ait lieu (EXE-99, critère 11).
    pending_rows = conn.execute(
        "SELECT * FROM offers WHERE extraction_status IN ('pending', 'retry') "
        "ORDER BY fetched_at"
    ).fetchall()
    print(
        f"[run] {len(pending_rows)} offres à trier (en attente + à refaire)",
        flush=True,
    )

    # (offer, extraction_attempts avant ce run) — le tri n'a pas pu les lire.
    a_relire_non_lues: list[tuple[JobOffer, int]] = []
    n_triees = 0

    for i, row in enumerate(pending_rows, 1):
        pending_offer = offer_from_row(row)
        print(
            f"[run] tri ({i}/{len(pending_rows)}) {pending_offer.title[:55]}",
            flush=True,
        )
        n_triees += 1

        tri = run_tri(
            conn, pending_offer, profile, alias_table, model=tri_model, host=host
        )
        if tri.needs_second_pass and tri.second_pass_reason == "unreadable":
            a_relire_non_lues.append((pending_offer, row["extraction_attempts"] or 0))
        elif tri.needs_second_pass:
            print(
                f"         → [{tri.outcome.category.value}] en attente de seconde passe"
            )
        elif tri.outcome.perimetre_causes:
            causes = ",".join(tri.outcome.perimetre_causes)
            print(f"         → hors_perimetre: {causes}")
        else:
            print(f"         → [{tri.outcome.category.value}]")

    # 5c. Seconde passe (LLM, modèle de précision) — parfait, puis rêve, puis
    #     les offres que le tri n'a pas lues (EXE-99, critère 12). Les offres
    #     « second_pass_pending » d'un run précédent sont reprises ici aussi,
    #     sans rappeler le modèle de tri (critère 8).
    n_relues = 0
    for cat in (Category.parfait, Category.reve):
        rows = conn.execute(
            "SELECT * FROM offers WHERE extraction_status = 'second_pass_pending' "
            "AND category = ? ORDER BY fetched_at",
            (cat.value,),
        ).fetchall()
        for row in rows:
            offer = offer_from_row(row)
            print(f"[run] seconde passe [{cat.value}] {offer.title[:55]}", flush=True)
            n_relues += 1
            outcome = resolve_category_second_pass(
                conn,
                offer,
                profile,
                alias_table,
                model=precision_model,
                host=host,
                tri_category=cat,
                second_pass_attempts_before=row["second_pass_attempts"] or 0,
            )
            if outcome.extraction_status == "second_pass_pending":
                print(
                    f"         → en attente de seconde passe (essai {outcome.second_pass_attempts})"
                )
            else:
                print(f"         → [{outcome.category.value}]")

    for offer, attempts_before in a_relire_non_lues:
        print(f"[run] seconde passe [non lue] {offer.title[:55]}", flush=True)
        n_relues += 1
        outcome = resolve_unreadable_with_precision(
            conn,
            offer,
            profile,
            alias_table,
            model=precision_model,
            host=host,
            attempts_before=attempts_before,
        )
        if outcome.extraction_status == "retry":
            print(f"         → à refaire (essai {outcome.extraction_attempts})")
        elif outcome.extraction_status == "unreadable":
            print("         → illisible")
        else:
            print(f"         → [{outcome.category.value}]")

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
    print(
        f"[run] extraction — {n_pending} en attente, {n_retry} à refaire, "
        f"{n_unreadable} illisibles"
    )
    print(
        f"[run] {n_triees} offres triées, {n_relues} relues, "
        f"{n_second_pass_pending} en attente de seconde passe"
    )

    # 6. Digest
    since = run_at - timedelta(hours=args.since_hours)
    scored = get_offers_since(conn, since)
    digest = generate_digest(scored, run_at=run_at)
    print()
    print(digest)

    digest_path = REPO_ROOT / f"data/digest_{run_at.strftime('%Y%m%d_%H%M')}.txt"
    digest_path.write_text(digest)
    print(f"[run] digest → {digest_path}")


if __name__ == "__main__":
    main()
