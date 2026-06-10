#!/usr/bin/env python3
"""
Replay extract_facts on N existing offers to populate data/traces/extract_facts.jsonl.

Usage:
    python replay_traces.py
    python replay_traces.py --n 20 --seed 42

Lecture seule SQLite — n'écrit RIEN dans offers/verdicts/human_reviews.
Lancer depuis la racine du repo.
"""
import argparse
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from orchestrator.job_search.scoring.extractor import extract_facts
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.storage.db import get_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay extract_facts on existing offers")
    parser.add_argument("--n", type=int, default=20, help="Nombre d'offres (défaut : 20)")
    parser.add_argument("--seed", type=int, default=42, help="Seed aléatoire reproductible (défaut : 42)")
    args = parser.parse_args()

    model = os.getenv("OLLAMA_MODEL", "llama3")
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT source, source_id, fingerprint, title, description,
               company, location, remote, contract_type, nature_contract,
               alternance, full_time, company_size, experience_required,
               rome_code, rome_label, url, fetched_at
        FROM offers
        WHERE (filtered_out = 0 OR filtered_out IS NULL)
          AND description IS NOT NULL
          AND description != ''
        """
    ).fetchall()

    if not rows:
        print("[replay] Aucune offre avec description trouvée en base.")
        return

    sample = random.Random(args.seed).sample(rows, min(args.n, len(rows)))

    print(f"[replay] {len(rows)} offres disponibles → tirage seed={args.seed}, n={len(sample)}")
    print(f"[replay] traces → data/traces/extract_facts.jsonl", flush=True)

    for i, r in enumerate(sample, 1):
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
            fetched_at=(
                datetime.fromisoformat(r["fetched_at"])
                if r["fetched_at"]
                else datetime.now(timezone.utc)
            ),
        )
        print(f"[replay] ({i}/{len(sample)}) {offer.title[:55]}", flush=True)
        facts = extract_facts(offer, model=model, host=host)
        flag = " ⚠ parse_failed" if facts.parse_failed else ""
        print(
            f"           → domain={facts.domain}  "
            f"seniority={facts.seniority_required.value}  "
            f"techs={len(facts.techs_required)}{flag}"
        )

    print(f"\n[replay] terminé — {len(sample)} traces écrites dans data/traces/extract_facts.jsonl")


if __name__ == "__main__":
    main()
