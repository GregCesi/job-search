"""python -m orchestrator.job_search.fiche <offer_id> — imprime le prompt complet (lecture seule)."""

import sqlite3
import sys

from orchestrator.job_search.fiche.cascade import identify_employer
from orchestrator.job_search.fiche.prompt import build_prompt
from orchestrator.job_search.paths import DB_PATH


def main() -> None:
    offer_id = int(sys.argv[1])
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    offer = conn.execute(
        "SELECT title, company, location, url, description, description_raw FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    if offer is None:
        sys.exit(f"offre {offer_id} introuvable")
    print(build_prompt(offer, identify_employer(offer_id, conn)))


if __name__ == "__main__":
    main()
