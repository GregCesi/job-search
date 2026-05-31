"""
Orchestrateur principal — run matinal.

Usage:
    python -m job_search.run
    python -m job_search.run --profile profiles/gregoire.yaml --max 150
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Job search morning run")
    parser.add_argument("--profile", default="profiles/gregoire.yaml")
    parser.add_argument("--max", type=int, default=150, dest="max_results")
    parser.add_argument("--since-hours", type=int, default=24)
    args = parser.parse_args()

    # Imports ici pour garder --help instantané
    from job_search.digest.formatter import generate_digest
    from job_search.matching.embedder import Embedder
    from job_search.matching.profile import load_profile
    from job_search.scoring.scorer import score_offer
    from job_search.sources.france_travail import FranceTravailSource
    from job_search.storage.db import get_connection, init_db
    from job_search.storage.dedup import filter_new
    from job_search.storage.offers import get_offers_since, save_offer

    run_at = datetime.now(timezone.utc)
    print(f"[run] démarrage {run_at.strftime('%Y-%m-%d %H:%M')} UTC", flush=True)

    # 1. Profil
    profile, profile_hash = load_profile(args.profile)
    print(f"[run] profil : {profile.profile_id} (hash={profile_hash[:8]}…)")

    # 2. DB
    conn = get_connection()
    init_db(conn)

    # 3. Embedder
    embedder = Embedder()
    re_embedded = embedder.embed_profile(profile, profile_hash)
    print(f"[run] profil {'ré-' if re_embedded else 'non ré-'}embeddé")

    # 4. Fetch
    print(f"[run] fetch France Travail (max={args.max_results})…", flush=True)
    source = FranceTravailSource(max_results=args.max_results)
    all_offers = source.fetch()
    print(f"[run] {len(all_offers)} offres récupérées")

    # 5. Dédup
    new_offers = filter_new(conn, all_offers)
    print(f"[run] {len(new_offers)} nouvelles ({len(all_offers) - len(new_offers)} déjà vues)")

    # 6. Embed + Score + Persist
    for i, offer in enumerate(new_offers, 1):
        print(f"[run] ({i}/{len(new_offers)}) {offer.title[:55]}", flush=True)
        embedder.add_offer(offer)
        result = score_offer(offer, profile)
        save_offer(conn, offer, result)
        flag = " ⚠ parse_failed" if result.parse_failed else ""
        print(f"         → {result.global_score:.1f}/100{flag}")

    # 7. Digest
    since = run_at - timedelta(hours=args.since_hours)
    scored = get_offers_since(conn, since, min_score=0.0)
    digest = generate_digest(scored, run_at=run_at)
    print()
    print(digest)

    digest_path = Path(f"data/digest_{run_at.strftime('%Y%m%d_%H%M')}.txt")
    digest_path.write_text(digest)
    print(f"[run] digest → {digest_path}")


if __name__ == "__main__":
    main()
