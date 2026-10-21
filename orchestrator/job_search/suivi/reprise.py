"""Reprise unique de `verdicts` (d'avant TCK-311) vers le module d'états —
critères 18-26 du ticket EXE-193.

Appelée une seule fois par `storage.db.run_reprise_candidatures`, jamais
directement : c'est lui qui pose la copie de sécurité, valide les lignes et le
marqueur « déjà reprise », dans une transaction unique (EXE-200, critères
1-10) — cette fonction n'ouvre ni ne commite aucune transaction elle-même.
Lecture seule de `verdicts`, jamais réécrite ni effacée ici.
"""

import sqlite3
from datetime import datetime, timezone

from . import etats

# Reprise vers RETENUE, puis CANDIDATURE_ENVOYEE si une date d'envoi existe
# (`envoyee_at` pour « retenu », ou systématiquement pour « candidaté », qui
# n'avait pas cette colonne séparée — critère 24).
_VERS_RETENUE = {"retenu", "candidaté"}
# Reprise directe vers ECARTEE, sans motif (critère 22, 24).
_VERS_ECARTEE = {"rejeté", "masqué"}
# Revue hors périmètre : axe à part, hors du tri (critère 23).
_VALEURS_REVUE = {"hors_perimetre_ok", "hors_perimetre_faux_pos"}

# Toute valeur de `verdicts.status` qu'une reprise sait traiter (EXE-200,
# critère 9) — une valeur hors de cet ensemble est inutilisable.
VALEURS_CONNUES = _VERS_RETENUE | _VERS_ECARTEE | _VALEURS_REVUE


class VerdictInutilisable(ValueError):
    """Une ligne de `verdicts` n'a pas de valeur utilisable pour la reprise
    (critère 9) : nomme l'offre et la valeur fautive. Le démarrage s'arrête
    avant toute copie et toute écriture (`storage.db.run_reprise_candidatures`)."""

    def __init__(self, offer_id, champ: str, valeur) -> None:
        self.offer_id = offer_id
        self.champ = champ
        self.valeur = valeur
        super().__init__(
            f"verdicts : offre {offer_id}, champ {champ!r} inutilisable ({valeur!r})"
        )


def valider_verdicts(conn: sqlite3.Connection) -> None:
    """Lecture seule (critère 9) : lève `VerdictInutilisable` si une ligne a un
    statut vide ou inconnu, ou une date de création vide — avant toute écriture
    de la reprise."""
    rows = conn.execute("SELECT offer_id, status, created_at FROM verdicts").fetchall()
    for row in rows:
        offer_id, status, created_at = row[0], row[1], row[2]
        if not status or status not in VALEURS_CONNUES:
            raise VerdictInutilisable(offer_id, "status", status)
        if not created_at:
            raise VerdictInutilisable(offer_id, "created_at", created_at)


def migrer_verdicts(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT offer_id, status, created_at, envoyee_at FROM verdicts ORDER BY id"
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()

    for row in rows:
        offer_id = row["offer_id"]
        status = row["status"]
        created_at = row["created_at"]
        envoyee_at = row["envoyee_at"]

        if status in _VALEURS_REVUE:
            conn.execute(
                "INSERT INTO revues_hors_perimetre (offer_id, valeur, created_at) "
                "VALUES (?, ?, ?) ON CONFLICT(offer_id) DO UPDATE SET "
                "valeur = excluded.valeur, created_at = excluded.created_at",
                (offer_id, status, created_at),
            )
            continue

        if status in _VERS_RETENUE:
            _ecrire_evenement(
                conn,
                offer_id,
                etats.RETENIR,
                etats.A_TRIER,
                etats.RETENUE,
                created_at,
                now,
            )
            etat_final = etats.RETENUE
            if status == "candidaté" or envoyee_at is not None:
                date_envoi = envoyee_at if status == "retenu" else created_at
                _ecrire_evenement(
                    conn,
                    offer_id,
                    etats.MARQUER_ENVOYEE,
                    etats.RETENUE,
                    etats.CANDIDATURE_ENVOYEE,
                    date_envoi,
                    now,
                )
                etat_final = etats.CANDIDATURE_ENVOYEE
            _poser_etat(conn, offer_id, etat_final)
        elif status in _VERS_ECARTEE:
            _ecrire_evenement(
                conn,
                offer_id,
                etats.ECARTER,
                etats.A_TRIER,
                etats.ECARTEE,
                created_at,
                now,
            )
            _poser_etat(conn, offer_id, etats.ECARTEE)


def _ecrire_evenement(
    conn: sqlite3.Connection,
    offer_id: int,
    geste: str,
    etat_depart: str,
    etat_arrivee: str,
    effet_at: str,
    enregistre_at: str,
) -> None:
    conn.execute(
        "INSERT INTO historique_gestes (offer_id, geste, etat_depart, etat_arrivee, "
        "motif, effet_at, enregistre_at, annule_at) VALUES (?, ?, ?, ?, NULL, ?, ?, NULL)",
        (offer_id, geste, etat_depart, etat_arrivee, effet_at, enregistre_at),
    )


def _poser_etat(conn: sqlite3.Connection, offer_id: int, etat: str) -> None:
    conn.execute(
        "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?) "
        "ON CONFLICT(offer_id) DO UPDATE SET etat = excluded.etat",
        (offer_id, etat),
    )
