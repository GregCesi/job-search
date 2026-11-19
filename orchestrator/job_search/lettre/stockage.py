"""Partir d'une de mes lettres (EXE-206) : lecture et écriture en base.

« Mes lettres » sont les lettres marquées Prêtes sur une autre offre, au texte
non vide (H2). La copie reprend ce texte tel quel, mot pour mot, sur la lettre
de l'offre courante : aucun appel de modèle, aucun remplacement (ni entreprise,
ni intitulé, ni date). Elle vaut décision de faire la lettre (H3) : la lettre
copiée est `done`, sa décision `demandee`, sans marque Prête, et l'historique
gagne une version d'origine « moi ». La lettre d'origine n'est jamais touchée.
"""

import json
import sqlite3
from datetime import datetime, timezone

from orchestrator.job_search import paths
from orchestrator.job_search.lettre.redaction import (
    count_words,
    detect_tournures,
    exceeds_length,
    load_tournures_interdites,
)
from orchestrator.job_search.lettre.service import _append_version
from orchestrator.job_search.pdf.filename import resolve_entreprise
from orchestrator.job_search.pieces import DECISION_A_DECIDER, DECISION_DEMANDEE

RAISON_SOURCE_INDISPONIBLE = (
    "Cette lettre n'est pas une lettre marquée Prête sur une autre offre."
)
RAISON_DEJA_DECIDEE = (
    "La lettre de cette offre n'est plus à décider : rien à copier dessus."
)

_REQUETE_MES_LETTRES = """
    SELECT l.offer_id, l.marque_pret_at, l.texte, o.title, o.company,
           f.employeur_nom
    FROM lettres l
    JOIN offers o ON o.id = l.offer_id
    LEFT JOIN fiches_entreprise f ON f.offer_id = l.offer_id
    WHERE l.marque_pret_at IS NOT NULL
      AND l.offer_id != ?
      AND l.texte IS NOT NULL AND TRIM(l.texte) != ''
"""


class CopieRefuseeError(RuntimeError):
    pass


def _lignes_mes_lettres(conn: sqlite3.Connection, offer_id: int) -> list:
    return conn.execute(
        _REQUETE_MES_LETTRES + " ORDER BY l.marque_pret_at DESC, l.offer_id DESC",
        (offer_id,),
    ).fetchall()


def mes_lettres(conn: sqlite3.Connection, offer_id: int) -> list[dict]:
    """Une ligne par lettre marquée Prête sur une autre offre (critères 4 à 6) :
    entreprise, intitulé et date de la marque, de la plus récente à la plus
    ancienne."""
    return [
        {
            "offer_id": r["offer_id"],
            "entreprise": resolve_entreprise(r["company"], r["employeur_nom"]),
            "intitule": r["title"],
            "marque_pret_at": r["marque_pret_at"],
        }
        for r in _lignes_mes_lettres(conn, offer_id)
    ]


def a_des_lettres_a_reprendre(conn: sqlite3.Connection, offer_id: int) -> bool:
    """Vrai s'il existe au moins une lettre à reprendre (critère 2)."""
    return bool(_lignes_mes_lettres(conn, offer_id))


def copier_lettre(
    conn: sqlite3.Connection, offer_id: int, source_offer_id: int
) -> None:
    """Copie le texte de la lettre de `source_offer_id` sur celle de `offer_id`
    (critères 7 à 10, 12). Refuse si la source n'est pas une de mes lettres ou
    si la lettre courante n'est plus à décider."""
    source = next(
        (
            r
            for r in _lignes_mes_lettres(conn, offer_id)
            if r["offer_id"] == source_offer_id
        ),
        None,
    )
    if source is None:
        raise CopieRefuseeError(RAISON_SOURCE_INDISPONIBLE)
    courante = conn.execute(
        "SELECT decision FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if courante is not None and courante["decision"] not in (
        None,
        DECISION_A_DECIDER,
    ):
        raise CopieRefuseeError(RAISON_DEJA_DECIDEE)

    texte = source["texte"]
    signalees = detect_tournures(
        texte, load_tournures_interdites(paths.LETTRE_TOURNURES_PATH)
    )
    nb_mots = count_words(texte)
    depasse = exceeds_length(nb_mots)
    conn.execute(
        """
        INSERT INTO lettres (offer_id, statut, decision, texte,
            tournures_signalees_json, nb_mots, depasse_longueur, created_at)
        VALUES (?, 'done', ?, ?, ?, ?, ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='done', decision=excluded.decision, texte=excluded.texte,
            tournures_signalees_json=excluded.tournures_signalees_json,
            nb_mots=excluded.nb_mots, depasse_longueur=excluded.depasse_longueur,
            marque_pret_at=NULL, error_message=NULL
        """,
        (
            offer_id,
            DECISION_DEMANDEE,
            texte,
            json.dumps(signalees, ensure_ascii=False),
            nb_mots,
            int(depasse),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    _append_version(conn, offer_id, texte, signalees, nb_mots, depasse, "moi", None)
    conn.commit()
