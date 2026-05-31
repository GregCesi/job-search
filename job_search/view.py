"""
Affiche le détail d'une offre (description + scoring) avant de juger.

Usage:
    python -m job_search.view --offer-id 3
    python -m job_search.view          # liste interactive
"""
import argparse
import json
import textwrap


def _print_offer(row) -> None:
    score = row["score"] or 0.0
    remote = " · remote" if row["remote"] else ""
    print()
    print("═" * 70)
    print(f"  {row['title']}")
    print(f"  {row['company'] or '?'} — {row['location'] or '?'}{remote} — {row['contract_type'] or '?'}")
    print(f"  Score : {score:.1f}/100")
    print("─" * 70)

    if row["criteria_json"]:
        try:
            for c in json.loads(row["criteria_json"]):
                key = c["key"].replace("_", " ")
                print(f"  · {key:<18} {c['score']:>4}/10  {c['justification'][:65]}")
        except (json.JSONDecodeError, KeyError):
            pass
        print("─" * 70)

    desc = row["description"] or "(description non disponible — relance un run pour la stocker)"
    for line in textwrap.wrap(desc, width=68):
        print(f"  {line}")

    print("─" * 70)
    print(f"  {row['url']}")
    print("═" * 70)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Voir le détail d'une offre")
    parser.add_argument("--offer-id", type=int)
    args = parser.parse_args()

    from job_search.storage.db import get_connection, init_db

    conn = get_connection()
    init_db(conn)

    if args.offer_id:
        row = conn.execute(
            "SELECT * FROM offers WHERE id = ?", (args.offer_id,)
        ).fetchone()
        if row is None:
            print(f"Offre id={args.offer_id} introuvable.")
            return
        _print_offer(row)
        return

    # Mode interactif : liste puis choix
    rows = conn.execute(
        """
        SELECT id, title, company, score FROM offers
        WHERE score IS NOT NULL
        ORDER BY score DESC LIMIT 30
        """
    ).fetchall()
    if not rows:
        print("Aucune offre scorée. Lance : python -m job_search.run")
        return

    print(f"\n{'ID':>4}  {'Score':>6}  Titre")
    print("─" * 70)
    for r in rows:
        print(f"{r['id']:>4}  {r['score']:>6.1f}  {r['title'][:52]}  ({r['company'] or '?'})")

    print()
    try:
        offer_id = int(input("ID à afficher : ").strip())
    except (EOFError, KeyboardInterrupt, ValueError):
        return

    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    if row is None:
        print(f"Offre id={offer_id} introuvable.")
        return
    _print_offer(row)


if __name__ == "__main__":
    main()
