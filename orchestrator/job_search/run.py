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
    from orchestrator.job_search.ingestion import process_offer
    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.aliases import load_alias_table
    from orchestrator.job_search.sources.base import JobOffer, Source
    from orchestrator.job_search.sources.eures import EuresSource
    from orchestrator.job_search.sources.france_travail import FranceTravailSource
    from orchestrator.job_search.sources.indeed_file import IndeedFileSource
    from orchestrator.job_search.sources.remotive import RemotiveSource
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.dedup import filter_new
    from orchestrator.job_search.storage.offers import get_offers_since

    model = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    run_at = datetime.now(timezone.utc)
    print(f"[run] démarrage {run_at.strftime('%Y-%m-%d %H:%M')} UTC", flush=True)

    # 1. Profil + alias
    profile, profile_hash = load_profile(args.profile)
    alias_table = load_alias_table(ALIAS_PATH)
    print(
        f"[run] profil : {profile.profile_id} role_ceiling={profile.role_ceiling.value} (hash={profile_hash[:8]}…)"
    )

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

    # 5. Filtre dur + Extract (LLM, 1 appel/offre) + Score (Python) + Persist
    #    — chaîne partagée avec l'ajout à la main (ingestion.py, EXE-79)
    for i, offer in enumerate(new_offers, 1):
        print(f"[run] ({i}/{len(new_offers)}) {offer.title[:55]}", flush=True)

        outcome = process_offer(
            conn, offer, profile, alias_table, model=model, host=host
        )
        if outcome.filter_reason is not None:
            print(f"         → filtré : {outcome.filter_reason}")
            continue

        flag = " ⚠ parse_failed" if outcome.parse_failed else ""
        if outcome.perimetre_causes:
            causes = ",".join(outcome.perimetre_causes)
            print(f"         → hors_perimetre: {causes}{flag}")
            continue

        print(f"         → [{outcome.category.value}]{flag}")

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
