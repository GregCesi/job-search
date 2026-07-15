"""
Relance de la catégorisation sur les offres sans catégorie.

Usage:
    python -m orchestrator.job_search.rescore
    python -m orchestrator.job_search.rescore --profile profiles/gregoire.yaml --dry-run
"""
import argparse
import os
from collections import Counter
from datetime import datetime, timezone

from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH, REPO_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-categorize offers missing category")
    parser.add_argument("--profile", default=str(PROFILE_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Affiche sans écrire en base")
    parser.add_argument("--force", action="store_true", help="Recalcule toutes les offres (y compris déjà scorées)")
    parser.add_argument("--re-extract", action="store_true", help="Force ré-extraction LLM (ignore les facts en cache)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.aliases import canonicalize, load_alias_table
    from orchestrator.job_search.scoring.attainability import compute_attainability
    from orchestrator.job_search.scoring.categorize import categorize
    from orchestrator.job_search.scoring.desirability import compute_desirability
    from orchestrator.job_search.scoring.extractor import extract_facts
    from orchestrator.job_search.scoring.hors_perimetre import derive_hors_perimetre
    from orchestrator.job_search.scoring.filters import apply_hard_filters
    from orchestrator.job_search.sources.base import JobOffer
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.offers import save_offer

    model = os.getenv("OLLAMA_MODEL", "llama3")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    profile, profile_hash = load_profile(args.profile)
    alias_table = load_alias_table(ALIAS_PATH)
    print(f"[rescore] profil : {profile.profile_id} ({profile.role_ceiling.value})")

    conn = get_connection()
    init_db(conn)

    if args.force:
        score_cond = ""  # toutes les offres (y compris déjà gatées/scorées)
    else:
        score_cond = "AND category IS NULL AND hors_perimetre_reason IS NULL"
    rows = conn.execute(
        f"""
        SELECT source, source_id, fingerprint, title, description,
               company, location, remote, contract_type, nature_contract,
               alternance, full_time, company_size, experience_required,
               rome_code, rome_label, url, fetched_at, extracted_facts_json
        FROM offers
        WHERE (filtered_out = 0 OR filtered_out IS NULL)
          {score_cond}
        ORDER BY fetched_at DESC
        """
    ).fetchall()

    print(f"[rescore] {len(rows)} offres à scorer", flush=True)
    if args.dry_run:
        print("[rescore] --dry-run : aucune écriture")

    # Clés profil canonicalisées (pour exclure du rapport unmatched)
    canonical_profile_keys = {
        canonicalize(k, alias_table)
        for k in profile.skills
    } - {None}

    n_ok = n_fail = 0
    unmatched_counter: Counter[str] = Counter()

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

        filtered_out, filter_reason = apply_hard_filters(offer, profile.search_criteria, profile.zones)
        if filtered_out:
            print(f"           → filtré : {filter_reason}")
            if not args.dry_run:
                save_offer(conn, offer, filtered_out=True, filter_reason=filter_reason)
            n_ok += 1
            continue

        # Réutilise les faits déjà extraits si disponibles — 0 LLM (architecture.md §4)
        facts = None
        if not args.re_extract and r["extracted_facts_json"]:
            try:
                from orchestrator.job_search.sources.base import ExtractedFacts
                facts = ExtractedFacts.model_validate_json(r["extracted_facts_json"])
            except Exception:
                facts = None

        if facts is None:
            facts = extract_facts(offer, model=model, host=host)

        offer = offer.model_copy(update={"extracted_facts": facts})

        # Accumule les techs inconnues (ni alias, ni exclu, ni profil) pour le rapport
        for t in facts.techs_required:
            c = canonicalize(t.name, alias_table)
            if c is not None and c not in alias_table._index and c not in canonical_profile_keys:
                unmatched_counter[c] += 1

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
        if hp_causes:
            flag = " ⚠ parse_failed" if facts.parse_failed else ""
            causes_str = [c.value for c in hp_causes]
            print(f"           → hors_perimetre: {','.join(causes_str)}{flag}")
            if not args.dry_run:
                save_offer(conn, offer,
                           perimetre_causes=causes_str,
                           techs_matched=a.techs_matched, techs_missing=a.techs_missing)
            n_ok += 1
            continue

        cat = categorize(d.score, a.score)

        flag = " ⚠ parse_failed" if facts.parse_failed else ""
        print(f"           → [{cat.value}]{flag}")

        if not args.dry_run:
            save_offer(conn, offer, category=cat,
                       perimetre_causes=[],
                       techs_matched=a.techs_matched, techs_missing=a.techs_missing)
            n_ok += 1
        else:
            n_ok += 1

        if facts.parse_failed:
            n_fail += 1

    # Rapport unmatched — techs inconnues triées par fréquence
    unmatched_path = REPO_ROOT / "data" / "unmatched_techs.txt"
    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{tech:<30s} {count}" for tech, count in unmatched_counter.most_common()]
    unmatched_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"[rescore] {len(lines)} techs inconnues → {unmatched_path}")

    if not args.dry_run:
        print(f"\n[rescore] terminé — {n_ok} scorées, {n_fail} parse_failed")
    else:
        print(f"\n[rescore] dry-run terminé — {n_ok} analysées, {n_fail} parse_failed")


if __name__ == "__main__":
    main()
