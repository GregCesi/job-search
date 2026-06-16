"""
Orchestrateur principal — run matinal.

Usage:
    python -m orchestrator.job_search.run
    python -m orchestrator.job_search.run --profile profiles/gregoire.yaml --max 150
"""
import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Job search morning run")
    parser.add_argument("--profile", default="profiles/gregoire.yaml")
    parser.add_argument("--max", type=int, default=150, dest="max_results")
    parser.add_argument("--since-hours", type=int, default=24)
    parser.add_argument("--no-remotive", action="store_true", help="Disable Remotive source")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from orchestrator.job_search.digest.formatter import generate_digest
    from orchestrator.job_search.matching.embedder import Embedder
    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.attainability import compute_attainability
    from orchestrator.job_search.scoring.categorize import categorize
    from orchestrator.job_search.scoring.desirability import compute_desirability
    from orchestrator.job_search.scoring.extractor import extract_facts
    from orchestrator.job_search.scoring.filters import apply_hard_filters
    from orchestrator.job_search.scoring.hors_perimetre import derive_hors_perimetre
    from orchestrator.job_search.sources.base import JobOffer, Source
    from orchestrator.job_search.sources.france_travail import FranceTravailSource
    from orchestrator.job_search.sources.remotive import RemotiveSource
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.dedup import filter_new
    from orchestrator.job_search.storage.offers import get_offers_since, save_offer
    from orchestrator.job_search.storage.purge import purge_irrelevant

    model = os.getenv("OLLAMA_MODEL", "llama3")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    run_at = datetime.now(timezone.utc)
    print(f"[run] démarrage {run_at.strftime('%Y-%m-%d %H:%M')} UTC", flush=True)

    # 1. Profil
    profile, profile_hash = load_profile(args.profile)
    print(f"[run] profil : {profile.profile_id} role_ceiling={profile.role_ceiling.value} (hash={profile_hash[:8]}…)")

    # 2. DB
    conn = get_connection()
    init_db(conn)

    # 3. Embedder
    embedder = Embedder()
    re_embedded = embedder.embed_profile(profile, profile_hash)
    print(f"[run] profil {'ré-' if re_embedded else 'non ré-'}embeddé")

    # 4. Fetch
    sources: list[Source] = [FranceTravailSource(max_results=args.max_results)]
    if not args.no_remotive:
        sources.append(RemotiveSource())

    all_offers: list[JobOffer] = []
    for src in sources:
        label = type(src).__name__
        print(f"[run] fetch {label}…", flush=True)
        batch = src.fetch()
        print(f"[run] {label}: {len(batch)} offres")
        all_offers.extend(batch)
    print(f"[run] {len(all_offers)} offres récupérées (total)")

    # 5. Dédup
    new_offers = filter_new(conn, all_offers)
    print(f"[run] {len(new_offers)} nouvelles ({len(all_offers) - len(new_offers)} déjà vues)")

    # 6. Filtre dur + Extract (LLM, 1 appel/offre) + Score (Python) + Persist
    for i, offer in enumerate(new_offers, 1):
        print(f"[run] ({i}/{len(new_offers)}) {offer.title[:55]}", flush=True)

        filtered_out, filter_reason = apply_hard_filters(offer, profile.search_criteria)
        if filtered_out:
            save_offer(conn, offer, filtered_out=True, filter_reason=filter_reason)
            print(f"         → filtré : {filter_reason}")
            continue

        embedder.add_offer(offer)

        facts = extract_facts(offer, model=model, host=host)
        offer = offer.model_copy(update={"extracted_facts": facts})

        # Gate hors-périmètre : court-circuite la catégorisation (0 LLM, §4)
        hp_reason = derive_hors_perimetre(facts)
        if hp_reason is not None:
            flag = " ⚠ parse_failed" if facts.parse_failed else ""
            save_offer(conn, offer, hors_perimetre_reason=hp_reason.value)
            print(f"         → hors_perimetre: {hp_reason.value}{flag}")
            continue

        d = compute_desirability(facts, profile.search_criteria, profile)
        a = compute_attainability(facts, profile)
        cat = categorize(d.score, a.score)
        save_offer(conn, offer, category=cat)

        flag = " ⚠ parse_failed" if facts.parse_failed else ""
        print(f"         → [{cat.value}]{flag}")

    # 7. Purge offres non pertinentes
    purged = purge_irrelevant(conn)
    if purged:
        print(f"[run] {purged} offres purgées (out_of_reach + peu désirables)")

    # 8. Digest
    since = run_at - timedelta(hours=args.since_hours)
    scored = get_offers_since(conn, since)
    digest = generate_digest(scored, run_at=run_at)
    print()
    print(digest)

    digest_path = Path(f"data/digest_{run_at.strftime('%Y%m%d_%H%M')}.txt")
    digest_path.write_text(digest)
    print(f"[run] digest → {digest_path}")


if __name__ == "__main__":
    main()
