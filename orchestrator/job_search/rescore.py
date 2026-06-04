"""
L11 — Relance du scoring sur les offres sans désirabilité/atteignabilité.

Usage:
    python -m orchestrator.job_search.rescore
    python -m orchestrator.job_search.rescore --profile profiles/gregoire.yaml --dry-run
"""
import argparse
import os
from datetime import datetime, timezone


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-score offers missing double-axis scores")
    parser.add_argument("--profile", default="profiles/gregoire.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans écrire en base")
    parser.add_argument("--force", action="store_true", help="Recalcule toutes les offres (y compris déjà scorées)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.attainability import compute_attainability
    from orchestrator.job_search.scoring.categorize import score_offer
    from orchestrator.job_search.scoring.desirability import compute_desirability
    from orchestrator.job_search.scoring.extractor import extract_facts
    from orchestrator.job_search.scoring.filters import apply_hard_filters
    from orchestrator.job_search.sources.base import JobOffer
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.offers import save_offer
    from orchestrator.job_search.storage.purge import purge_irrelevant

    model = os.getenv("OLLAMA_MODEL", "llama3")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    profile, profile_hash = load_profile(args.profile)
    print(f"[rescore] profil : {profile.profile_id} ({profile.role_ceiling.value})")

    conn = get_connection()
    init_db(conn)

    desirability_cond = "" if args.force else "AND desirability IS NULL"
    rows = conn.execute(
        f"""
        SELECT source, source_id, fingerprint, title, description,
               company, location, remote, contract_type, nature_contract,
               alternance, full_time, company_size, experience_required,
               rome_code, rome_label, url, fetched_at, extracted_facts_json
        FROM offers
        WHERE (filtered_out = 0 OR filtered_out IS NULL)
          {desirability_cond}
        ORDER BY fetched_at DESC
        """
    ).fetchall()

    print(f"[rescore] {len(rows)} offres à scorer", flush=True)
    if args.dry_run:
        print("[rescore] --dry-run : aucune écriture")

    n_ok = n_fail = 0
    for i, r in enumerate(rows, 1):
        offer = JobOffer(
            source=r["source"],
            source_id=r["source_id"],
            fingerprint=r["fingerprint"],
            title=r["title"] or "",
            description=r["description"] or "",
            company=r["company"],
            location=r["location"],
            remote=bool(r["remote"]),
            contract_type=r["contract_type"],
            nature_contract=r["nature_contract"],
            alternance=bool(r["alternance"] or False),
            full_time=(None if r["full_time"] is None else bool(r["full_time"])),
            company_size=r["company_size"],
            experience_required=r["experience_required"],
            rome_code=r["rome_code"],
            rome_label=r["rome_label"],
            url=r["url"] or "",
            fetched_at=datetime.fromisoformat(r["fetched_at"])
            if r["fetched_at"]
            else datetime.now(timezone.utc),
        )

        print(f"[rescore] ({i}/{len(rows)}) {offer.title[:55]}", flush=True)

        filtered_out, filter_reason = apply_hard_filters(offer, profile.search_criteria)
        if filtered_out:
            print(f"           → filtré : {filter_reason}")
            if not args.dry_run:
                save_offer(conn, offer, None, None, filtered_out=True, filter_reason=filter_reason)
            n_ok += 1
            continue

        # Réutilise les faits déjà extraits si disponibles — 0 LLM (architecture.md §4)
        facts = None
        if r["extracted_facts_json"]:
            try:
                from orchestrator.job_search.sources.base import ExtractedFacts
                facts = ExtractedFacts.model_validate_json(r["extracted_facts_json"])
            except Exception:
                facts = None

        if facts is None:
            facts = extract_facts(offer, model=model, host=host)

        offer = offer.model_copy(update={"extracted_facts": facts})
        d = compute_desirability(facts, profile.search_criteria, profile)
        a = compute_attainability(facts, profile)
        s = score_offer(d.score, a.score)

        flag = " ⚠ parse_failed" if facts.parse_failed else ""
        print(
            f"           → d={d.score:.1f}  a={a.score:.1f}  [{s.category.value}]"
            f"  blocked={a.blocked_by}{flag}"
        )

        if not args.dry_run:
            save_offer(conn, offer, d, a, scored=s)
            n_ok += 1
        else:
            n_ok += 1

        if facts.parse_failed:
            n_fail += 1

    if not args.dry_run:
        purged = purge_irrelevant(conn)
        print(f"\n[rescore] terminé — {n_ok} scorées, {n_fail} parse_failed, {purged} purgées")
    else:
        print(f"\n[rescore] dry-run terminé — {n_ok} analysées, {n_fail} parse_failed")


if __name__ == "__main__":
    main()
