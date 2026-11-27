"""Vérification d'expiration des offres retenues (EXE-76), étendue à toute
offre désignée explicitement depuis un onglet de la vue candidat (EXE-78), et
lecture du parcours de candidature des mêmes offres (EXE-217).

Deux déclencheurs, et aucun autre (EXE-217, H7) : POST /offers/check-expirations,
et la fin d'un run, pour les offres des files « À postuler » et « À étudier »
(`expiration.fin_de_run`). Jamais le rescore, un changement de profil, le
démarrage de l'API ni l'affichage d'une file.

Le verdict vient du parcours (EXE-218) : une offre dont le parcours dit « fermée »
est expirée, une offre dont il dit « ouverte » ne l'est plus. Un parcours
« non vérifiable » ne change rien, sauf une URL employeur saisie à la main qui
répond. Un parcours qui n'a pas pu être lu laisse le calcul d'avant, sur les
codes de l'URL de l'offre et de l'URL employeur (cf. H2 d'EXE-76). Dans tous les
cas, un code 404 ou 410 d'une de ces URL expire l'offre, comme avant.

Une vérification lancée avec des identifiants lit aussi, une seule fois, le
parcours des offres déjà traitées qui n'ont jamais été lues (EXE-219, H4) : leur
clé de comparaison sort des files les offres de même lien. Cette lecture ne
donne aucun verdict d'expiration.
"""

import json
import sqlite3
from datetime import datetime, timezone

import requests

from orchestrator.job_search.parcours import stockage as parcours_stockage
from orchestrator.job_search.parcours.ouverture import FERMEE, OUVERTE
from orchestrator.job_search.parcours.service import ouvrir_lecteur, verifier_parcours
from orchestrator.job_search.suivi import etats
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


def decider(
    ouverture: str | None,
    codes_offre: list[int],
    codes_employeur: list[int],
    previous_expired: bool,
) -> bool:
    """Le verdict d'expiration, du parcours d'abord (EXE-218)."""
    if any(code in _CLOSED_CODES for code in codes_offre + codes_employeur):
        return True
    if ouverture == FERMEE:
        return True
    if ouverture == OUVERTE:
        return False
    if ouverture is None:
        return compute_expired(codes_offre + codes_employeur, previous_expired)
    return compute_expired(codes_employeur, previous_expired)


def _offres(conn: sqlite3.Connection, offer_ids: list[int] | None) -> list:
    ids = suivi_storage.offer_ids_retenues(conn) if offer_ids is None else offer_ids
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        f"""
        SELECT o.id AS offer_id, o.url AS offer_url, e.employer_url, e.expired
        FROM offers o
        LEFT JOIN expirations e ON e.offer_id = o.id
        WHERE o.id IN ({placeholders})
        """,
        list(ids),
    ).fetchall()


def _traitees_jamais_lues(conn: sqlite3.Connection, exclues: list[int]) -> list[int]:
    """Les offres dont l'état n'est pas « à trier » et dont le parcours n'a jamais
    été lu, hors `exclues` (EXE-219)."""
    lues = parcours_stockage.offres_lues(conn) | set(exclues)
    return sorted(
        oid
        for oid, etat in suivi_storage.etat_map(conn).items()
        if etat != etats.A_TRIER and oid not in lues
    )


def _codes(checks: list[tuple[str, int | None, str]]) -> list[int]:
    return [code for _, code, _ in checks if code is not None]


def run_expiration_check(
    conn: sqlite3.Connection, offer_ids: list[int] | None = None
) -> None:
    """Vérifie les offres concernées et persiste l'état recalculé dans
    `expirations`. Ne touche jamais `offers` ni le tri des offres.

    `offer_ids=None` (comportement d'avant EXE-78) : seules les offres
    retenues sont vérifiées. `offer_ids` désigné : exactement ces offres, quel
    que soit leur verdict — l'appelant garantit qu'elles existent toutes.
    Le parcours de candidature de chaque offre est lu et gardé (EXE-217), et
    donne le verdict (EXE-218). Avec `offer_ids`, le parcours des offres déjà
    traitées jamais lues est lu aussi, sans verdict (EXE-219)."""
    lecteur = ouvrir_lecteur()
    for row in _offres(conn, offer_ids):
        offre = [(u, *check_url(u)) for u in (row["offer_url"],) if u]
        employeur = [(u, *check_url(u)) for u in (row["employer_url"],) if u]
        ouverture = verifier_parcours(conn, row["offer_id"], lecteur)
        previous_expired = bool(row["expired"]) if row["expired"] is not None else False
        expired = decider(ouverture, _codes(offre), _codes(employeur), previous_expired)
        now = datetime.now(timezone.utc).isoformat()
        checks_json = json.dumps(
            [
                {"url": u, "status_code": code, "checked_at": checked_at}
                for u, code, checked_at in offre + employeur
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
    if offer_ids is not None:
        for oid in _traitees_jamais_lues(conn, offer_ids):
            verifier_parcours(conn, oid, lecteur)
    conn.commit()
