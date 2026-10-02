"""
Relance de la catégorisation sur les offres sans catégorie.

Usage:
    python -m orchestrator.job_search.rescore
    python -m orchestrator.job_search.rescore --profile profiles/gregoire.yaml --dry-run

Réextraction ciblée (TCK-211) — ne reprend que les offres dont `extraction_version`
diffère de la version courante (modèle + prompt + schéma). Interruptible : chaque
offre est écrite dès qu'elle est faite, un nouveau lancement reprend les restantes.
Ordre : vue candidat d'abord, puis parfait → reve → atteignable → le reste.
    python -m orchestrator.job_search.rescore --re-extract-stale --vue-candidat --categories parfait
    python -m orchestrator.job_search.rescore --re-extract-stale --categories parfait,reve,atteignable
    python -m orchestrator.job_search.rescore --re-extract-stale --random --limit 10
"""

import argparse
import os
from collections import Counter
from datetime import datetime, timezone

from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH, REPO_ROOT


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-categorize offers missing category"
    )
    parser.add_argument("--profile", default=str(PROFILE_PATH))
    parser.add_argument(
        "--dry-run", action="store_true", help="Affiche sans écrire en base"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recalcule toutes les offres (y compris déjà scorées)",
    )
    parser.add_argument(
        "--re-extract",
        action="store_true",
        help="Force ré-extraction LLM (ignore les facts en cache)",
    )
    parser.add_argument(
        "--re-extract-stale",
        action="store_true",
        help="Réextrait les offres dont extraction_version diffère de la version courante (TCK-211)",
    )
    parser.add_argument(
        "--vue-candidat",
        action="store_true",
        help="Restreint aux zones de profiles/vue_candidat.yaml",
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="Catégories courantes à traiter, séparées par des virgules "
        "(parfait,reve,atteignable,hors,hors_perimetre)",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Nombre maximum d'offres traitées"
    )
    parser.add_argument(
        "--random",
        action="store_true",
        help="Ordre aléatoire (avec --limit : un échantillon)",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    from orchestrator.job_search.matching.profile import load_profile
    from orchestrator.job_search.scoring.aliases import canonicalize, load_alias_table
    from orchestrator.job_search.scoring.attainability import compute_attainability
    from orchestrator.job_search.scoring.categorize import categorize
    from orchestrator.job_search.scoring.desirability import compute_desirability
    from orchestrator.job_search.scoring.extractor import (
        extract_facts,
        extraction_version,
    )
    from orchestrator.job_search.scoring.filters import apply_hard_filters
    from orchestrator.job_search.scoring.hors_perimetre import derive_hors_perimetre
    from orchestrator.job_search.sources.base import JobOffer
    from orchestrator.job_search.storage.db import get_connection, init_db
    from orchestrator.job_search.storage.offers import save_offer

    model = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    profile, profile_hash = load_profile(args.profile)
    alias_table = load_alias_table(ALIAS_PATH)
    print(f"[rescore] profil : {profile.profile_id} ({profile.role_ceiling.value})")

    conn = get_connection()
    init_db(conn)

    current_version = extraction_version(model)

    # Garde-fou (TCK-211) : sans Ollama, extract_facts renvoie un fallback vide
    # qui écraserait les faits existants. On refuse de démarrer.
    if args.re_extract or args.re_extract_stale:
        import ollama

        try:
            listed = ollama.Client(host=host).list()
        except Exception as exc:
            raise SystemExit(
                f"[rescore] Ollama injoignable sur {host} ({exc}). Lance l'app Ollama ou `ollama serve`, puis relance."
            )
        models = (
            listed.get("models", [])
            if isinstance(listed, dict)
            else getattr(listed, "models", [])
        )
        available = {
            (m.get("model") or m.get("name"))
            if isinstance(m, dict)
            else (getattr(m, "model", None) or getattr(m, "name", None))
            for m in models
        }
        if model not in available and f"{model}:latest" not in available:
            raise SystemExit(
                f"[rescore] modèle {model} absent d'Ollama (disponibles : {sorted(available)})."
            )
    # EXE-98 : une offre en attente, à refaire ou illisible n'est jamais touchée par
    # le rescore, dans aucun mode — c'est le /run qui la reprend (architecture.md TCK-273)
    conditions: list[str] = [
        "(o.filtered_out = 0 OR o.filtered_out IS NULL)",
        "o.extraction_status IS NULL",
    ]
    params: list = []
    order_params: list = []

    if args.re_extract_stale:
        conditions.append("(o.extraction_version IS NULL OR o.extraction_version != ?)")
        params.append(current_version)
        print(f"[rescore] version courante : {current_version}")
    elif not args.force:
        conditions.append("o.category IS NULL AND o.hors_perimetre_reason IS NULL")

    if args.categories:
        wanted = [c.strip() for c in args.categories.split(",") if c.strip()]
        cat_conds = []
        plain = [c for c in wanted if c != "hors_perimetre"]
        if plain:
            cat_conds.append(f"o.category IN ({','.join('?' * len(plain))})")
            params.extend(plain)
        if "hors_perimetre" in wanted:
            cat_conds.append("o.hors_perimetre_reason IS NOT NULL")
        conditions.append("(" + " OR ".join(cat_conds) + ")")

    zone_sql = "0"
    if args.vue_candidat or args.re_extract_stale:
        from api.view_profile import build_view_clauses

        zone_conds, zone_params = build_view_clauses()
        if zone_conds:
            zone_sql = "(" + " OR ".join(zone_conds) + ")"
            if args.vue_candidat:
                conditions.append(zone_sql)
                params.extend(zone_params)
            order_params = list(zone_params)

    if args.random:
        order_sql = "RANDOM()"
        order_params = []
    elif args.re_extract_stale:
        # Du plus intéressant au moins intéressant : zone candidat, puis catégorie
        order_sql = (
            f"CASE WHEN {zone_sql} THEN 0 ELSE 1 END, "
            "CASE o.category WHEN 'parfait' THEN 0 WHEN 'reve' THEN 1 "
            "WHEN 'atteignable' THEN 2 ELSE 3 END, o.fetched_at DESC"
        )
    else:
        order_sql = "o.fetched_at DESC"
        order_params = []

    limit_sql = f"LIMIT {int(args.limit)}" if args.limit else ""
    rows = conn.execute(
        f"""
        SELECT o.source, o.source_id, o.fingerprint, o.title, o.description, o.description_raw,
               o.company, o.location, o.remote, o.contract_type, o.nature_contract,
               o.alternance, o.full_time, o.company_size, o.experience_required,
               o.rome_code, o.rome_label, o.url, o.fetched_at, o.extracted_facts_json,
               o.category
        FROM offers o
        WHERE {" AND ".join(conditions)}
        ORDER BY {order_sql}
        {limit_sql}
        """,
        params + order_params,
    ).fetchall()

    print(f"[rescore] {len(rows)} offres à scorer", flush=True)
    if args.dry_run:
        print("[rescore] --dry-run : aucune écriture")

    # Clés profil canonicalisées (pour exclure du rapport unmatched)
    canonical_profile_keys = {canonicalize(k, alias_table) for k in profile.skills} - {
        None
    }

    n_ok = n_fail = 0
    unmatched_counter: Counter[str] = Counter()

    for i, r in enumerate(rows, 1):
        offer = JobOffer(
            source=r["source"],
            source_id=r["source_id"],
            fingerprint=r["fingerprint"],
            title=r["title"] or "",
            description=r["description"] or "",
            description_raw=r["description_raw"],
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

        print(
            f"[rescore] ({i}/{len(rows)}) [{r['category'] or '-'}] {offer.title[:55]}",
            flush=True,
        )

        filtered_out, filter_reason = apply_hard_filters(
            offer, profile.search_criteria, profile.zones
        )
        if filtered_out:
            print(f"           → filtré : {filter_reason}")
            if not args.dry_run:
                save_offer(conn, offer, filtered_out=True, filter_reason=filter_reason)
            n_ok += 1
            continue

        # Réutilise les faits déjà extraits si disponibles — 0 LLM (architecture.md §4)
        facts = None
        version = None  # écrit seulement si l'extraction est refaite ici
        if not (args.re_extract or args.re_extract_stale) and r["extracted_facts_json"]:
            try:
                from orchestrator.job_search.sources.base import ExtractedFacts

                facts = ExtractedFacts.model_validate_json(r["extracted_facts_json"])
            except Exception:
                facts = None

        if facts is None:
            facts = extract_facts(offer, model=model, host=host)
            # Une extraction en échec n'est pas marquée : elle sera retentée au prochain run
            version = None if facts.parse_failed else current_version

        offer = offer.model_copy(update={"extracted_facts": facts})

        # Accumule les techs inconnues (ni alias, ni exclu, ni profil) pour le rapport
        for t in facts.techs_required:
            c = canonicalize(t.name, alias_table)
            if (
                c is not None
                and c not in alias_table._index
                and c not in canonical_profile_keys
            ):
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
            if facts.parse_failed:
                n_fail += 1
            if not args.dry_run:
                save_offer(
                    conn,
                    offer,
                    perimetre_causes=causes_str,
                    techs_matched=a.techs_matched,
                    techs_missing=a.techs_missing,
                    extraction_version=version,
                )
            n_ok += 1
            continue

        cat = categorize(d.score, a.score)

        flag = " ⚠ parse_failed" if facts.parse_failed else ""
        prev = r["category"] or "-"
        moved = f"  (était {prev})" if prev != cat.value else ""
        print(f"           → [{cat.value}]{flag}{moved}")

        if not args.dry_run:
            save_offer(
                conn,
                offer,
                category=cat,
                perimetre_causes=[],
                techs_matched=a.techs_matched,
                techs_missing=a.techs_missing,
                extraction_version=version,
            )
            n_ok += 1
        else:
            n_ok += 1

        if facts.parse_failed:
            n_fail += 1

    # Rapport unmatched — techs inconnues triées par fréquence
    unmatched_path = REPO_ROOT / "data" / "unmatched_techs.txt"
    unmatched_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{tech:<30s} {count}" for tech, count in unmatched_counter.most_common()]
    unmatched_path.write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
    )
    print(f"[rescore] {len(lines)} techs inconnues → {unmatched_path}")

    if not args.dry_run:
        print(f"\n[rescore] terminé — {n_ok} scorées, {n_fail} parse_failed")
    else:
        print(f"\n[rescore] dry-run terminé — {n_ok} analysées, {n_fail} parse_failed")


if __name__ == "__main__":
    main()
