"""
Purge des offres non pertinentes (architecture.md §4 + IMPLEMENTATION.md L9).

Condition de purge (les deux doivent être vraies) :
  1. attainability = 'out_of_reach'
  2. desirability < seuil (défaut 40.0)

Les offres avec un verdict humain ne sont JAMAIS purgées (séparation offers/verdicts).
"""
import sqlite3


def purge_irrelevant(
    conn: sqlite3.Connection,
    desirability_threshold: float = 40.0,
) -> int:
    """
    Supprime les offres out_of_reach ET peu désirables sans verdict.
    Retourne le nombre de lignes supprimées.
    """
    cur = conn.execute(
        """
        DELETE FROM offers
        WHERE attainability = 'out_of_reach'
          AND desirability < ?
          AND id NOT IN (SELECT offer_id FROM verdicts WHERE offer_id IS NOT NULL)
        """,
        (desirability_threshold,),
    )
    conn.commit()
    return cur.rowcount
