"""CLI — ajoute des offres (par identifiant) au jeu de référence (TCK-221, EXE-107).

Usage:
    python -m orchestrator.job_search.reference.ajouter --ids 123,456
"""

import argparse
from pathlib import Path

from orchestrator.job_search.reference.dataset import JEU_PATH, add_offers
from orchestrator.job_search.storage.db import get_connection, init_db


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ajoute des offres au jeu de référence"
    )
    parser.add_argument(
        "--ids", required=True, help="Identifiants d'offres, séparés par des virgules"
    )
    parser.add_argument("--jeu", default=str(JEU_PATH))
    args = parser.parse_args()

    ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]

    conn = get_connection()
    init_db(conn)
    report = add_offers(conn, ids, jeu_path=Path(args.jeu))
    conn.close()

    print(
        f"[reference] {len(report.added)} offre(s) ajoutée(s), non relue(s) : {report.added}"
    )
    if report.skipped_existing:
        print(
            f"[reference] {len(report.skipped_existing)} déjà présente(s), "
            f"inchangée(s) : {report.skipped_existing}"
        )
    if report.skipped_no_facts:
        print(
            f"[reference] {len(report.skipped_no_facts)} sans faits extraits "
            f"en base, ignorée(s) : {report.skipped_no_facts}"
        )


if __name__ == "__main__":
    main()
