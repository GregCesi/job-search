"""Vérification d'expiration des offres retenues (EXE-76), étendue à toute
offre désignée explicitement depuis un onglet de la vue candidat (EXE-78), et
lecture du parcours de candidature des mêmes offres (EXE-217).

Deux déclencheurs, et aucun autre (EXE-217, H7) : POST /offers/check-expirations,
et la fin d'un run, pour les offres des files « À postuler » et « À étudier »
(`expiration.fin_de_run`). Jamais le rescore, un changement de profil, le
démarrage de l'API ni l'affichage d'une file. Pour chaque offre concernée,
interroge son URL en base et son URL employeur optionnelle, recalcule l'état
expiré/non-expiré — cf. H2 d'EXE-76 —, puis lit son parcours de candidature.
"""

import json
import sqlite3
from datetime import datetime, timezone

import requests

from orchestrator.job_search.parcours.service import lire_parcours
from orchestrator.job_search.suivi import storage as suivi_storage

TIMEOUT_SECONDS = 10
_CLOSED_CODES = {404, 410}


def check_url(url: str) -> tuple[int | None, str]:
    """Suit les redirections et rend le code de réponse final, ou None si l'URL
    n'a pas répondu (erreur réseau ou dépassement du délai)."""
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(url, allow_redirects=True, timeout=TIMEOUT_SECONDS)
        return resp.status_code, checked_at
    except requests.exceptions.RequestException:
        return None, checked_at


def compute_expired(status_codes: list[int], previous_expired: bool) -> bool:
    """404/410 sur une des URL de l'offre → expirée, quel que soit le reste.
    Sinon, un 2xx recalcule l'état à non-expirée. Sans signal (aucune URL
    n'a répondu, ou seulement des codes ni fermés ni ouverts) → état conservé."""
    if any(code in _CLOSED_CODES for code in status_codes):
        return True
    if any(200 <= code < 300 for code in status_codes):
        return False
    return previous_expired


def run_expiration_check(
    conn: sqlite3.Connection, offer_ids: list[int] | None = None
) -> None:
    """Vérifie les URL des offres concernées et persiste l'état recalculé dans
    `expirations`. Ne touche jamais `offers` ni le tri des offres.

    `offer_ids=None` (comportement d'avant EXE-78) : seules les offres
    retenues sont vérifiées. `offer_ids` désigné : exactement ces offres, quel
    que soit leur verdict — l'appelant garantit qu'elles existent toutes.
    Le parcours de candidature des mêmes offres est lu ensuite (EXE-217)."""
    if offer_ids is not None:
        if not offer_ids:
            rows = []
        else:
            placeholders = ",".join("?" for _ in offer_ids)
            rows = conn.execute(
                f"""
                SELECT o.id AS offer_id, o.url AS offer_url, e.employer_url, e.expired
                FROM offers o
                LEFT JOIN expirations e ON e.offer_id = o.id
                WHERE o.id IN ({placeholders})
                """,
                offer_ids,
            ).fetchall()
    else:
        retenues = suivi_storage.offer_ids_retenues(conn)
        if not retenues:
            rows = []
        else:
            placeholders = ",".join("?" for _ in retenues)
            rows = conn.execute(
                f"""
                SELECT o.id AS offer_id, o.url AS offer_url, e.employer_url, e.expired
                FROM offers o
                LEFT JOIN expirations e ON e.offer_id = o.id
                WHERE o.id IN ({placeholders})
                """,
                retenues,
            ).fetchall()

    for row in rows:
        urls = [u for u in (row["offer_url"], row["employer_url"]) if u]
        checks = [(u, *check_url(u)) for u in urls]
        status_codes = [code for _, code, _ in checks if code is not None]
        previous_expired = bool(row["expired"]) if row["expired"] is not None else False
        expired = compute_expired(status_codes, previous_expired)
        now = datetime.now(timezone.utc).isoformat()
        checks_json = json.dumps(
            [
                {"url": u, "status_code": code, "checked_at": checked_at}
                for u, code, checked_at in checks
            ],
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT INTO expirations (offer_id, employer_url, expired, last_checked_at, checks_json)
            VALUES (?, NULL, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                expired         = excluded.expired,
                last_checked_at = excluded.last_checked_at,
                checks_json     = excluded.checks_json
            """,
            (row["offer_id"], int(expired), now, checks_json),
        )
    conn.commit()
    lire_parcours(conn, [row["offer_id"] for row in rows])
