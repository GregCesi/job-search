"""Persistance du module d'états du suivi des candidatures (TCK-311, EXE-193).

Seul fichier, avec `reprise.py`, qui exécute une requête SQL sur le tri,
l'étape, l'historique ou la revue hors périmètre (architecture.md) — toute
autre lecture ou écriture de ces notions passe par les fonctions d'ici.
"""

import sqlite3
from datetime import datetime, timezone

from orchestrator.job_search.pieces import (
    DECISION_SANS_LETTRE,
    PRETE,
    cv_statut,
    decision_lettre,
    lettre_statut,
)

from . import etats

_VALEURS_REVUE = {"hors_perimetre_ok", "hors_perimetre_faux_pos"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pieces_pretes(conn: sqlite3.Connection, offer_id: int) -> tuple[bool, bool, bool]:
    cv_row = conn.execute(
        "SELECT marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    lettre_row = conn.execute(
        "SELECT statut, marque_pret_at, decision FROM lettres WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    lettre_sans = decision_lettre(lettre_row) == DECISION_SANS_LETTRE
    return cv_statut(cv_row) == PRETE, lettre_statut(lettre_row) == PRETE, lettre_sans


def pieces_pretes(conn: sqlite3.Connection, offer_id: int) -> tuple[bool, bool, bool]:
    """(cv_pret, lettre_pret, lettre_sans) — exposé pour les routes qui en ont
    besoin hors du module (EXE-200, critères 15-16 ; `lettre_sans` ajouté par
    EXE-196)."""
    return _pieces_pretes(conn, offer_id)


def etat_stocke(conn: sqlite3.Connection, offer_id: int) -> str:
    row = conn.execute(
        "SELECT etat FROM etats_offre WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    return row["etat"] if row is not None else etats.A_TRIER


def etat_map(conn: sqlite3.Connection) -> dict[int, str]:
    """Tous les états stockés, par offer_id — pour les listes (critère 12)
    sans une requête par offre."""
    rows = conn.execute("SELECT offer_id, etat FROM etats_offre").fetchall()
    return {r["offer_id"]: r["etat"] for r in rows}


def tri(conn: sqlite3.Connection, offer_id: int) -> str:
    return etats.tri(etat_stocke(conn, offer_id))


def est_retenue(conn: sqlite3.Connection, offer_id: int) -> bool:
    return tri(conn, offer_id) == etats.RETENUE


def offer_ids_retenues(conn: sqlite3.Connection) -> list[int]:
    placeholders = ",".join("?" * len(etats.ETATS_RETENUS))
    rows = conn.execute(
        f"SELECT offer_id FROM etats_offre WHERE etat IN ({placeholders})",
        tuple(etats.ETATS_RETENUS),
    ).fetchall()
    return [r["offer_id"] for r in rows]


def etape(conn: sqlite3.Connection, offer_id: int) -> str | None:
    etat = etat_stocke(conn, offer_id)
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes(conn, offer_id)
    return etats.etape_affichee(
        etat, cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    )


def historique(
    conn: sqlite3.Connection, offer_id: int
) -> list[etats.EvenementHistorique]:
    rows = conn.execute(
        "SELECT id, geste, etat_depart, etat_arrivee, effet_at, enregistre_at, "
        "motif, annule_at FROM historique_gestes WHERE offer_id = ? ORDER BY id ASC",
        (offer_id,),
    ).fetchall()
    return [
        etats.EvenementHistorique(
            id=r["id"],
            geste=r["geste"],
            etat_depart=r["etat_depart"],
            etat_arrivee=r["etat_arrivee"],
            effet_at=r["effet_at"],
            enregistre_at=r["enregistre_at"],
            motif=r["motif"],
            annule_at=r["annule_at"],
        )
        for r in rows
    ]


def historique_map(
    conn: sqlite3.Connection,
) -> dict[int, list[etats.EvenementHistorique]]:
    rows = conn.execute(
        "SELECT id, offer_id, geste, etat_depart, etat_arrivee, effet_at, "
        "enregistre_at, motif, annule_at FROM historique_gestes ORDER BY offer_id, id ASC"
    ).fetchall()
    result: dict[int, list[etats.EvenementHistorique]] = {}
    for r in rows:
        result.setdefault(r["offer_id"], []).append(
            etats.EvenementHistorique(
                id=r["id"],
                geste=r["geste"],
                etat_depart=r["etat_depart"],
                etat_arrivee=r["etat_arrivee"],
                effet_at=r["effet_at"],
                enregistre_at=r["enregistre_at"],
                motif=r["motif"],
                annule_at=r["annule_at"],
            )
        )
    return result


def gestes_permis(conn: sqlite3.Connection, offer_id: int) -> list[str]:
    etat = etat_stocke(conn, offer_id)
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes(conn, offer_id)
    hist = historique(conn, offer_id)
    return etats.gestes_permis_effectifs(
        etat,
        cv_pret=cv_pret,
        lettre_pret=lettre_pret,
        lettre_sans=lettre_sans,
        annulable=etats.permis_annuler(hist),
    )


def gestes_avec_etat(conn: sqlite3.Connection, offer_id: int) -> list[etats.GesteEtat]:
    """Chaque geste de la table, permis ou non, avec son libellé et sa raison
    (critère 14 — EXE-200 ; libellé dynamique de l'annulation — EXE-194,
    critère 15)."""
    etat = etat_stocke(conn, offer_id)
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes(conn, offer_id)
    hist = historique(conn, offer_id)
    return etats.gestes_avec_etat(
        etat,
        cv_pret=cv_pret,
        lettre_pret=lettre_pret,
        lettre_sans=lettre_sans,
        dernier_annulable=etats.dernier_geste_non_annule(hist),
    )


def etapes_acquises(conn: sqlite3.Connection, offer_id: int) -> list[str]:
    """Sous-ensemble de la frise réellement acquis (EXE-194, critère 22)."""
    etat = etat_stocke(conn, offer_id)
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes(conn, offer_id)
    hist = historique(conn, offer_id)
    return etats.etapes_acquises(
        etat, hist, cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    )


def dernier_ecart(
    conn: sqlite3.Connection, offer_id: int
) -> etats.EvenementHistorique | None:
    """Dernier geste `ecarter` non annulé (EXE-194, critères 9 et 11)."""
    return etats.dernier_ecart(historique(conn, offer_id))


def appliquer_geste(
    conn: sqlite3.Connection,
    offer_id: int,
    geste: str,
    *,
    effet_at: str | None = None,
    motif: str | None = None,
) -> str:
    """Nouvel état stocké, ou lève `etats.GesteRefuse` (transition impossible)
    / `etats.DateEffetFuture` (EXE-197 : `effet_at` de `marquer_envoyee`
    postérieur au jour de Bruxelles) sans rien écrire (critère 2)."""
    etat_avant = etat_stocke(conn, offer_id)
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes(conn, offer_id)
    nouvel_etat = etats.appliquer(
        etat_avant,
        geste,
        cv_pret=cv_pret,
        lettre_pret=lettre_pret,
        lettre_sans=lettre_sans,
    )
    now = _now()
    if geste == etats.MARQUER_ENVOYEE:
        # EXE-197, H3 : seul `marquer_envoyee` porte la règle de date — les
        # autres gestes gardent leur `effet_at` tel qu'il est reçu.
        effet = etats.normaliser_effet_marquer_envoyee(effet_at)
    else:
        effet = effet_at if effet_at is not None else now
    conn.execute(
        "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?) "
        "ON CONFLICT(offer_id) DO UPDATE SET etat = excluded.etat",
        (offer_id, nouvel_etat),
    )
    conn.execute(
        "INSERT INTO historique_gestes (offer_id, geste, etat_depart, etat_arrivee, "
        "motif, effet_at, enregistre_at, annule_at) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
        (offer_id, geste, etat_avant, nouvel_etat, motif, effet, now),
    )
    conn.commit()
    return nouvel_etat


def annuler_dernier_geste(conn: sqlite3.Connection, offer_id: int) -> str:
    hist = historique(conn, offer_id)
    dernier = etats.dernier_geste_non_annule(hist)
    if dernier is None:
        raise etats.GesteRefuse(etat_stocke(conn, offer_id), etats.ANNULER)
    now = _now()
    conn.execute(
        "UPDATE historique_gestes SET annule_at = ? WHERE id = ?",
        (now, dernier.id),
    )
    conn.execute(
        "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?) "
        "ON CONFLICT(offer_id) DO UPDATE SET etat = excluded.etat",
        (offer_id, dernier.etat_depart),
    )
    conn.commit()
    return dernier.etat_depart


def date_envoyee(conn: sqlite3.Connection, offer_id: int) -> str | None:
    """Date d'effet du dernier `marquer_envoyee` non annulé — équivalent de
    l'ancien `verdicts.envoyee_at` (EXE-139)."""
    row = conn.execute(
        "SELECT effet_at FROM historique_gestes WHERE offer_id = ? AND geste = ? "
        "AND annule_at IS NULL ORDER BY id DESC LIMIT 1",
        (offer_id, etats.MARQUER_ENVOYEE),
    ).fetchone()
    return row["effet_at"] if row else None


# ---------------------------------------------------------------------------
# Revue hors périmètre — axe à part, ne change jamais le tri (architecture.md)
# ---------------------------------------------------------------------------


def marquer_revue_hors_perimetre(
    conn: sqlite3.Connection, offer_id: int, valeur: str
) -> None:
    if valeur not in _VALEURS_REVUE:
        raise ValueError(f"valeur de revue hors périmètre inconnue : {valeur!r}")
    conn.execute(
        "INSERT INTO revues_hors_perimetre (offer_id, valeur, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(offer_id) DO UPDATE SET valeur = excluded.valeur, "
        "created_at = excluded.created_at",
        (offer_id, valeur, _now()),
    )
    conn.commit()


def effacer_revue_hors_perimetre(conn: sqlite3.Connection, offer_id: int) -> None:
    conn.execute("DELETE FROM revues_hors_perimetre WHERE offer_id = ?", (offer_id,))
    conn.commit()


def revue_hors_perimetre(conn: sqlite3.Connection, offer_id: int) -> str | None:
    row = conn.execute(
        "SELECT valeur FROM revues_hors_perimetre WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    return row["valeur"] if row is not None else None


def revue_hors_perimetre_map(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute("SELECT offer_id, valeur FROM revues_hors_perimetre").fetchall()
    return {r["offer_id"]: r["valeur"] for r in rows}


def verdict_label(conn: sqlite3.Connection, offer_id: int) -> str | None:
    """Reflet d'affichage, compatible de l'ancien `verdicts.status` (front
    inchangé hors critères 34-37) : la revue hors périmètre gagne sur le tri."""
    revue = revue_hors_perimetre(conn, offer_id)
    if revue is not None:
        return revue
    t = tri(conn, offer_id)
    if t == etats.RETENUE:
        return "retenu"
    if t == etats.ECARTEE:
        return "ecartee"
    return None
