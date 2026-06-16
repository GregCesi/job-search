"""
Saisie de verdict humain sur une offre.

Usage non-interactif :
    python -m job_search.verdict --offer-id 3 --status favori

Usage interactif (liste les offres récentes, demande id + statut) :
    python -m job_search.verdict
"""
import argparse
from datetime import datetime, timezone

_VALID_STATUSES = {"favori", "rejeté", "candidaté"}


def _list_recent(conn) -> list:
    return conn.execute(
        """
        SELECT id, title, company, category
        FROM offers
        WHERE category IS NOT NULL
        ORDER BY
            CASE category
                WHEN 'parfait'     THEN 1
                WHEN 'reve'        THEN 2
                WHEN 'atteignable' THEN 3
                WHEN 'hors'        THEN 4
                ELSE 5
            END ASC,
            fetched_at DESC
        LIMIT 30
        """
    ).fetchall()


def _record_verdict(conn, offer_id: int, status: str) -> None:
    # Vérifie que l'offre existe
    row = conn.execute("SELECT id, title FROM offers WHERE id = ?", (offer_id,)).fetchone()
    if row is None:
        raise ValueError(f"Offre id={offer_id} introuvable.")

    conn.execute(
        """
        INSERT INTO verdicts (offer_id, status, created_at)
        VALUES (?, ?, ?)
        """,
        (offer_id, status, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    print(f"✓ Verdict '{status}' enregistré pour : {row['title']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enregistrer un verdict sur une offre")
    parser.add_argument("--offer-id", type=int, help="ID SQLite de l'offre")
    parser.add_argument("--status", choices=list(_VALID_STATUSES), help="favori | rejeté | candidaté")
    args = parser.parse_args()

    from orchestrator.job_search.storage.db import get_connection, init_db

    conn = get_connection()
    init_db(conn)

    # Mode non-interactif
    if args.offer_id and args.status:
        _record_verdict(conn, args.offer_id, args.status)
        return

    # Mode interactif
    offers = _list_recent(conn)
    if not offers:
        print("Aucune offre scorée en base. Lance d'abord : python -m job_search.run")
        return

    print(f"\n{'ID':>4}  {'Catégorie':<12}  Titre")
    print("─" * 70)
    for o in offers:
        cat = o["category"] or "?"
        print(f"{o['id']:>4}  {cat:<12}  {o['title'][:45]}  ({o['company'] or '?'})")

    print()
    try:
        offer_id = int(input("ID de l'offre : ").strip())
        status = input(f"Statut [{' | '.join(sorted(_VALID_STATUSES))}] : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return

    if status not in _VALID_STATUSES:
        print(f"Statut invalide : '{status}'. Valeurs acceptées : {_VALID_STATUSES}")
        return

    _record_verdict(conn, offer_id, status)


if __name__ == "__main__":
    main()
