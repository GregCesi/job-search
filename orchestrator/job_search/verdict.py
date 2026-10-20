"""
Saisie de verdict humain sur une offre — passe par le module d'états
(TCK-311, EXE-193) : seuls les gestes Retenir et Écarter.

Usage non-interactif :
    python -m job_search.verdict --offer-id 3 --status retenir

Usage interactif (liste les offres récentes, demande id + geste) :
    python -m job_search.verdict
"""

import argparse

from orchestrator.job_search.suivi import etats
from orchestrator.job_search.suivi import storage as suivi_storage

_GESTES_PERMIS = {etats.RETENIR, etats.ECARTER}


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


def _record_verdict(conn, offer_id: int, geste: str) -> None:
    row = conn.execute(
        "SELECT id, title FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"Offre id={offer_id} introuvable.")

    nouvel_etat = suivi_storage.appliquer_geste(conn, offer_id, geste)
    print(f"✓ Geste '{geste}' enregistré pour : {row['title']} → {nouvel_etat}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enregistrer un verdict sur une offre")
    parser.add_argument("--offer-id", type=int, help="ID SQLite de l'offre")
    parser.add_argument(
        "--status", choices=list(_GESTES_PERMIS), help="retenir | ecarter"
    )
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
        geste = input(f"Geste [{' | '.join(sorted(_GESTES_PERMIS))}] : ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAnnulé.")
        return

    if geste not in _GESTES_PERMIS:
        print(f"Geste invalide : '{geste}'. Valeurs acceptées : {_GESTES_PERMIS}")
        return

    _record_verdict(conn, offer_id, geste)


if __name__ == "__main__":
    main()
