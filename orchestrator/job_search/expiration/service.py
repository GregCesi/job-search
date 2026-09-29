"""Vérification d'expiration des offres retenues (EXE-76).

Action explicite (jamais déclenchée par l'ingestion, le rescore ou un changement
de profil) : pour chaque offre retenue, interroge son URL en base et son URL
employeur optionnelle, et recalcule l'état expiré/non-expiré — cf. H2 du ticket.
"""

import json
import sqlite3
from datetime import datetime, timezone

import requests

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


def run_expiration_check(conn: sqlite3.Connection) -> None:
    """Vérifie les URL de chaque offre retenue et persiste l'état recalculé
    dans `expirations`. Ne touche jamais `offers` ni `verdicts`."""
    rows = conn.execute(
        """
        SELECT o.id AS offer_id, o.url AS offer_url, e.employer_url, e.expired
        FROM offers o
        JOIN verdicts v ON v.offer_id = o.id
        LEFT JOIN expirations e ON e.offer_id = o.id
        WHERE v.status = 'retenu'
        """
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
