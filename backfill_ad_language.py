#!/usr/bin/env python3
"""Backfill : ad_language sur les offres existantes.

- 0 LLM — uniquement langdetect (offline).
- Idempotent : ne traite que les offres dont ad_language IS NULL.
- --dry-run : affiche les détections sans écrire.

Usage:
    python backfill_ad_language.py              # exécution réelle
    python backfill_ad_language.py --dry-run    # inspection sans écriture
"""

import argparse
import sqlite3

from orchestrator.job_search.paths import DB_PATH
from orchestrator.job_search.scoring.ad_language import detect_ad_language
from orchestrator.job_search.storage.db import init_db


def backfill(dry_run: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    rows = conn.execute(
        "SELECT id, source, title, description FROM offers WHERE ad_language IS NULL"
    ).fetchall()

    if not rows:
        print("Rien à backfiller — toutes les offres ont déjà ad_language.")
        conn.close()
        return

    print(f"{len(rows)} offres à traiter (ad_language IS NULL)\n")

    counts: dict[str, int] = {}
    for row in rows:
        text = row["description"] or ""
        lang = detect_ad_language(text)
        counts[lang] = counts.get(lang, 0) + 1

        if dry_run:
            print(f"[{lang}] #{row['id']} ({row['source']}) {(row['title'] or '')[:60]}")
        else:
            conn.execute(
                "UPDATE offers SET ad_language = ? WHERE id = ?",
                (lang, row["id"]),
            )

    if not dry_run:
        conn.commit()
        print(f"✓ {len(rows)} offres mises à jour.")

    print("\nRépartition :", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ad_language")
    parser.add_argument("--dry-run", action="store_true", help="Inspecter sans écrire")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
