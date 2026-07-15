#!/usr/bin/env python3
"""Backfill one-shot : description_raw + re-dérivation Markdown (chantier HTML→MD).

Pour chaque offre existante :
  1. description_raw = description actuelle (le brut récupérable)
  2. description = html_to_markdown(description_raw)  (Markdown dérivé)

- 0 LLM, 0 re-pull source, Python pur.
- Idempotent : ne re-traite que les offres dont description_raw est NULL.
- --dry-run : affiche les conversions sans écrire.

Usage:
    python backfill_description_raw.py              # exécution réelle
    python backfill_description_raw.py --dry-run    # inspection sans écriture
"""

import argparse
import sqlite3

from orchestrator.job_search.paths import DB_PATH
from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.storage.db import init_db


def backfill(dry_run: bool = False) -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    rows = conn.execute(
        "SELECT id, source, title, description FROM offers WHERE description_raw IS NULL"
    ).fetchall()

    if not rows:
        print("Rien à backfiller — toutes les offres ont déjà description_raw.")
        conn.close()
        return

    print(f"{len(rows)} offres à traiter (description_raw IS NULL)\n")

    for row in rows:
        raw = row["description"] or ""
        md = html_to_markdown(raw)
        changed = md != raw.strip()

        if dry_run:
            tag = "CONVERT" if changed else "KEEP"
            print(f"[{tag}] #{row['id']} ({row['source']}) {row['title'][:60]}")
            if changed:
                print(f"  raw (100c): {raw[:100]}")
                print(f"  md  (100c): {md[:100]}")
                print()
        else:
            conn.execute(
                "UPDATE offers SET description_raw = ?, description = ? WHERE id = ?",
                (raw, md, row["id"]),
            )

    if not dry_run:
        conn.commit()
        print(f"✓ {len(rows)} offres mises à jour.")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill description_raw + Markdown")
    parser.add_argument("--dry-run", action="store_true", help="Inspecter sans écrire")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
