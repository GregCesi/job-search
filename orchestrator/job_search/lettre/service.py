"""Génération de la lettre de motivation (EXE-162) : fiche entreprise (faits, moins
ceux que j'ai écartés) → boucle tamis/rédaction/vérificateur/juge (`lettre/boucle.py`)
→ table `lettres`.

Frontière (architecture.md, exceptions encadrées) : l'appel de modèle ne part que
d'une action explicite (POST /offers/{id}/lettre, /offers/{id}/lettre/regenerer ou
/offers/{id}/lettre/ecarter), jamais d'un changement de profil ou de la fiche
entreprise.

Historique (EXE-66) : chaque texte qui devient la version courante — sortie du
modèle (génération, régénération ou écartement d'un fait) ou texte repris par
l'utilisateur — est journalisé dans `lettre_versions`, jamais réécrit ni effacé.
"""

import asyncio
import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    MODELES_CLAUDE,
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    ConfigBoucle,
    dernier_releve,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.lettre.redaction import (
    RAISON_RIEN_A_ECARTER,
    count_words,
    detect_tournures,
    exceeds_length,
    load_tournures_interdites,
    resolve_offer_text,
)
from orchestrator.job_search.paths import LETTRE_TOURNURES_PATH
from orchestrator.job_search.storage.db import get_connection, init_db

# EXE-166 : sonnet par défaut, choisi explicitement sinon (critères 1, 2, 4) —
# jamais un modèle local (Ollama), cf. MODELES_CLAUDE de la boucle.
MODELE_PAR_DEFAUT = "sonnet"

# EXE-169 : le juge tourne toujours sur opus, jamais sur le modèle choisi
# (critères 1, 2) — un juge sonnet avait laissé passer des lettres que je
# jugeais moi-même mauvaises.
MODELE_JUGE = "opus"


def raison_modele_invalide(modele: str) -> str:
    choix = " ou ".join(sorted(MODELES_CLAUDE))
    return f"Modèle inconnu : « {modele} ». Choix possibles : {choix}."


class ModeleInvalideError(ValueError):
    """Modèle demandé hors de sonnet/opus (EXE-166, critère 3)."""


def valider_modele(modele: str) -> None:
    """Refuse avant tout appel de modèle (critère 3) : seuls sonnet et opus,
    jamais un modèle local — MODELES_CLAUDE est la même liste que la boucle."""
    if modele not in MODELES_CLAUDE:
        raise ModeleInvalideError(raison_modele_invalide(modele))


class LettreNonPreteError(RuntimeError):
    """Aucune lettre `done` pour cette offre (EXE-66) : rien à reprendre ni à régénérer."""


class RienAEcarterError(RuntimeError):
    """Aucun fait retenu à écarter (EXE-162, critère 17) : lettre générique ou
    jamais générée."""


@dataclass
class _GenerationBoucle:
    texte: str
    signalees: list[str]
    nb_mots: int
    depasse: bool
    fait_retenu: dict | None  # None = lettre générique
    texte_type_id: str
    nb_tours: int
    raison_fin: str
    jugement: dict | None
    modele_juge: str  # EXE-169 : toujours MODELE_JUGE, à part du modèle choisi
    releve: dict | None
    appels: list[dict]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_version(
    conn: sqlite3.Connection,
    offer_id: int,
    texte: str,
    signalees: list[str],
    nb_mots: int,
    depasse: bool,
    origine: str,
    fait_retenu: dict | None,
    modele: str | None = None,
    modele_juge: str | None = None,
    jugement: dict | None = None,
    nb_tours: int | None = None,
    raison_fin: str | None = None,
) -> None:
    """Ajoute une version à l'historique — jamais de réécriture ni de suppression
    d'une version existante (invariant du ticket EXE-66). Porte le fait retenu
    (EXE-162, critère 7) et le modèle qui l'a écrite, absent pour une reprise à
    la main (EXE-166, critère 6). Pour une version écrite par la boucle (EXE-169,
    critères 4, 6, 8) : le modèle du juge à part du modèle choisi, et le verdict
    du juge sur cette lettre (ses quatre rubriques, le nombre de tours, la raison
    de fin) — tous absents pour une reprise à la main, pour qu'une régénération
    ultérieure ne touche jamais le jugement déjà écrit dans l'historique."""
    conn.execute(
        """
        INSERT INTO lettre_versions
            (offer_id, texte, tournures_signalees_json, nb_mots, depasse_longueur,
             origine, fait_retenu_json, created_at, modele, modele_juge,
             jugement_json, nb_tours, raison_fin)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            offer_id,
            texte,
            json.dumps(signalees, ensure_ascii=False),
            nb_mots,
            int(depasse),
            origine,
            json.dumps(fait_retenu, ensure_ascii=False) if fait_retenu else None,
            _now(),
            modele,
            modele_juge,
            json.dumps(jugement, ensure_ascii=False) if jugement else None,
            nb_tours,
            raison_fin,
        ),
    )


def reset_pending(conn: sqlite3.Connection, offer_id: int) -> None:
    """Insère ou remet à zéro la ligne lettre en `pending` (relance après erreur incluse).

    Ne touche jamais `points_choisis_json` ni `faits_ecartes_json` : le choix de
    points (hérité, non lu par la génération) et les faits écartés survivent à une
    régénération — ce reset ne concerne que la sortie de génération.
    """
    conn.execute(
        """
        INSERT INTO lettres (offer_id, statut, created_at) VALUES (?, 'pending', ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='pending', texte=NULL, tournures_signalees_json=NULL, nb_mots=NULL,
            depasse_longueur=NULL, modele=NULL, session_id=NULL, cost_usd=NULL,
            prompt_text=NULL, error_message=NULL, fait_retenu_json=NULL,
            texte_type_id=NULL, nb_tours=NULL, raison_fin=NULL, jugement_json=NULL,
            releve_json=NULL, appels_json=NULL
        """,
        (offer_id, _now()),
    )
    conn.commit()


def _cle_fait(point: dict) -> tuple:
    return (point.get("citation"), point.get("url"))


def _fetch_faits_ecartes(conn: sqlite3.Connection, offer_id: int) -> list[dict]:
    row = conn.execute(
        "SELECT faits_ecartes_json FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None or not row["faits_ecartes_json"]:
        return []
    return json.loads(row["faits_ecartes_json"])


def _filtrer_points_ecartes(points: list[dict], ecartes: list[dict]) -> list[dict]:
    cles_ecartees = {_cle_fait(e) for e in ecartes}
    return [p for p in points if _cle_fait(p) not in cles_ecartees]


def _config_boucle(modele: str) -> ConfigBoucle:
    """Le modèle choisi tourne sur le tamis et la rédaction (critères 1, 2) : le
    vérificateur, laissé à `None`, retombe sur celui de la rédaction
    (`ConfigBoucle.modele_verificateur_effectif`), jamais un troisième modèle.
    Le juge tourne toujours sur `MODELE_JUGE` (EXE-169), jamais sur le modèle
    choisi."""
    return ConfigBoucle(
        modele_tamis=modele, modele_redaction=modele, modele_juge=MODELE_JUGE
    )


async def _generate_via_boucle(
    conn: sqlite3.Connection,
    offer_id: int,
    modele: str,
    on_etape: Callable[[dict], None] | None = None,
) -> _GenerationBoucle:
    """Lance la boucle tamis → rédaction → vérificateur → juge (critère 1), sur
    les points de la fiche terminée moins les faits écartés (critères 4, 14) —
    jamais sur les points cochés ni la désignation de la fiche. Tourne dans un
    thread (critère 2) : `generer_lettre_depuis_donnees` appelle `asyncio.run` en
    interne, incompatible avec la boucle d'événements de l'API.

    `on_etape` (EXE-167) : transmis tel quel à la boucle, appelé depuis le
    thread — optionnel, sans effet quand personne ne l'écoute (critère 6)."""
    offer = conn.execute(
        "SELECT title, description_raw, description, company FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    if offer is None:
        raise ValueError(f"offre {offer_id} introuvable")

    offer_text = resolve_offer_text(offer["description_raw"], offer["description"])
    if not offer_text:
        raise ValueError(f"texte de l'offre manquant pour l'offre {offer_id}")

    fiche = conn.execute(
        "SELECT points_json, employeur_nom FROM fiches_entreprise "
        "WHERE offer_id = ? AND statut = 'done'",
        (offer_id,),
    ).fetchone()
    if fiche is None:
        raise ValueError(f"fiche entreprise manquante pour l'offre {offer_id}")

    points = json.loads(fiche["points_json"] or "[]")
    ecartes = _fetch_faits_ecartes(conn, offer_id)
    points_restants = _filtrer_points_ecartes(points, ecartes)
    entreprise = fiche["employeur_nom"] or offer["company"] or ""

    # Critère 6 : absent, l'appel garde exactement sa forme d'avant la fiche —
    # aucun argument supplémentaire à qui n'a pas demandé à être écouté.
    kwargs_etape = {"on_etape": on_etape} if on_etape is not None else {}
    config = _config_boucle(modele)
    resultat = await asyncio.to_thread(
        generer_lettre_depuis_donnees,
        offer["title"] or "",
        offer_text,
        entreprise,
        points_restants,
        config,
        **kwargs_etape,
    )

    if resultat.raison_fin not in (RAISON_RIEN_A_REDIRE, RAISON_PLAFOND):
        raise RuntimeError(resultat.raison_fin)

    derniere = resultat.lettres[-1]
    texte = derniere["texte"]
    nb_mots = derniere["nb_mots"]
    signalees = derniere.get("tournures_signalees") or []
    jugement = derniere["jugement"]
    releve = dernier_releve(derniere)
    fait_retenu = None if resultat.fait_retenu == GENERIQUE_ID else resultat.fait_retenu

    return _GenerationBoucle(
        texte=texte,
        signalees=signalees,
        nb_mots=nb_mots,
        depasse=exceeds_length(nb_mots),
        fait_retenu=fait_retenu,
        texte_type_id=resultat.texte_type_id,
        nb_tours=resultat.nb_tours,
        raison_fin=resultat.raison_fin,
        jugement=asdict(jugement) if jugement is not None else None,
        modele_juge=config.modele_juge,
        releve=releve,
        appels=[asdict(a) for a in resultat.appels],
    )


def _store_generation(
    conn: sqlite3.Connection, offer_id: int, gen: _GenerationBoucle, modele: str
) -> None:
    conn.execute(
        """
        UPDATE lettres SET
            statut='done', texte=?, tournures_signalees_json=?, nb_mots=?,
            depasse_longueur=?, modele=?, modele_juge=?, fait_retenu_json=?,
            texte_type_id=?, nb_tours=?, raison_fin=?, jugement_json=?,
            releve_json=?, appels_json=?, error_message=NULL
        WHERE offer_id=?
        """,
        (
            gen.texte,
            json.dumps(gen.signalees, ensure_ascii=False),
            gen.nb_mots,
            int(gen.depasse),
            modele,
            gen.modele_juge,
            json.dumps(gen.fait_retenu, ensure_ascii=False)
            if gen.fait_retenu
            else None,
            gen.texte_type_id,
            gen.nb_tours,
            gen.raison_fin,
            json.dumps(gen.jugement, ensure_ascii=False) if gen.jugement else None,
            json.dumps(gen.releve, ensure_ascii=False) if gen.releve else None,
            json.dumps(gen.appels, ensure_ascii=False),
            offer_id,
        ),
    )
    _append_version(
        conn,
        offer_id,
        gen.texte,
        gen.signalees,
        gen.nb_mots,
        gen.depasse,
        "modele",
        gen.fait_retenu,
        modele,
        gen.modele_juge,
        gen.jugement,
        gen.nb_tours,
        gen.raison_fin,
    )


async def run_lettre(
    offer_id: int,
    modele: str = MODELE_PAR_DEFAUT,
    on_etape: Callable[[dict], None] | None = None,
) -> None:
    """Produit la lettre de l'offre via la boucle, sur le modèle choisi (sonnet
    par défaut — EXE-166, critères 1, 2). Toute exception (dont le timeout,
    l'absence de fiche terminée, ou une raison de fin de boucle autre que
    « rien à redire »/« plafond ») finit en `statut='error'`, sans qu'aucun
    texte ne soit stocké (critère 9).

    `on_etape` (EXE-167, critère 2) : signal de progression optionnel, posé par
    l'appelant (l'API) — absent par défaut, sans effet sur ce module.
    """
    conn = get_connection()
    try:
        init_db(conn)
        reset_pending(conn, offer_id)
        try:
            gen = await _generate_via_boucle(conn, offer_id, modele, on_etape)
            _store_generation(conn, offer_id, gen, modele)
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — l'échec est une donnée (cf cv/service.py)
            conn.execute(
                "UPDATE lettres SET statut='error', error_message=? WHERE offer_id=?",
                (f"{type(exc).__name__}: {exc}"[:2000], offer_id),
            )
            conn.commit()
            if not isinstance(exc, Exception):
                raise
    finally:
        conn.close()


def mark_regenerating(conn: sqlite3.Connection, offer_id: int) -> None:
    """Marque une régénération en cours sans toucher à la version courante (critères
    11, 12 du ticket EXE-66) : `texte`, `tournures_signalees_json`, `nb_mots` et
    `depasse_longueur` restent ceux de la version d'avant tant que la régénération
    n'a pas abouti. Une marque « Prête » (EXE-101) est effacée dès le lancement :
    le contenu va changer, la validation humaine est à refaire."""
    conn.execute(
        "UPDATE lettres SET regeneration_en_cours=1, regeneration_error=NULL, "
        "marque_pret_at=NULL WHERE offer_id=?",
        (offer_id,),
    )
    conn.commit()


async def run_lettre_regenerate(
    offer_id: int,
    modele: str = MODELE_PAR_DEFAUT,
    on_etape: Callable[[dict], None] | None = None,
) -> None:
    """Régénère la lettre de l'offre via la boucle, sur le modèle choisi (sonnet
    par défaut) et les faits restants après exclusion (EXE-162). En cas d'échec
    ou de timeout, la version d'avant (texte, signalements) reste en place
    intacte — seul l'état `regeneration_en_cours`/`regeneration_error` change
    (critère 11 EXE-66). `on_etape` (EXE-167) : même contrat que `run_lettre`."""
    conn = get_connection()
    try:
        init_db(conn)
        try:
            gen = await _generate_via_boucle(conn, offer_id, modele, on_etape)
            conn.execute(
                """
                UPDATE lettres SET
                    texte=?, tournures_signalees_json=?, nb_mots=?, depasse_longueur=?,
                    modele=?, modele_juge=?, fait_retenu_json=?, texte_type_id=?,
                    nb_tours=?, raison_fin=?, jugement_json=?, releve_json=?,
                    appels_json=?, regeneration_en_cours=0, regeneration_error=NULL
                WHERE offer_id=?
                """,
                (
                    gen.texte,
                    json.dumps(gen.signalees, ensure_ascii=False),
                    gen.nb_mots,
                    int(gen.depasse),
                    modele,
                    gen.modele_juge,
                    json.dumps(gen.fait_retenu, ensure_ascii=False)
                    if gen.fait_retenu
                    else None,
                    gen.texte_type_id,
                    gen.nb_tours,
                    gen.raison_fin,
                    json.dumps(gen.jugement, ensure_ascii=False)
                    if gen.jugement
                    else None,
                    json.dumps(gen.releve, ensure_ascii=False) if gen.releve else None,
                    json.dumps(gen.appels, ensure_ascii=False),
                    offer_id,
                ),
            )
            _append_version(
                conn,
                offer_id,
                gen.texte,
                gen.signalees,
                gen.nb_mots,
                gen.depasse,
                "modele",
                gen.fait_retenu,
                modele,
                gen.modele_juge,
                gen.jugement,
                gen.nb_tours,
                gen.raison_fin,
            )
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — l'échec est une donnée (cf run_lettre)
            conn.execute(
                "UPDATE lettres SET regeneration_en_cours=0, regeneration_error=? "
                "WHERE offer_id=?",
                (f"{type(exc).__name__}: {exc}"[:2000], offer_id),
            )
            conn.commit()
            if not isinstance(exc, Exception):
                raise
    finally:
        conn.close()


def save_texte(conn: sqlite3.Connection, offer_id: int, texte: str) -> None:
    """Enregistre le texte repris par l'utilisateur comme version courante de la
    lettre (critère 1) : signale les tournures interdites et le dépassement de
    longueur sans jamais corriger `texte` (invariant du ticket — une tournure
    signalée reste dans le texte stocké), puis journalise une version (critère 4).
    Calcul 100% Python (critère 7) : aucun appel modèle. Une marque « Prête »
    (EXE-101) est effacée par cet enregistrement : le contenu change, la
    validation humaine est à refaire.
    """
    init_db(conn)
    row = conn.execute(
        "SELECT statut, fait_retenu_json FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None or row["statut"] != "done":
        raise LettreNonPreteError(f"aucune lettre prête pour l'offre {offer_id}")
    if not texte.strip():
        raise ValueError("le texte de la lettre ne peut pas être vide")

    tournures = load_tournures_interdites(LETTRE_TOURNURES_PATH)
    signalees = detect_tournures(texte, tournures)
    nb_mots = count_words(texte)
    depasse = exceeds_length(nb_mots)
    fait_retenu = (
        json.loads(row["fait_retenu_json"]) if row["fait_retenu_json"] else None
    )

    conn.execute(
        """
        UPDATE lettres SET
            texte=?, tournures_signalees_json=?, nb_mots=?, depasse_longueur=?,
            marque_pret_at=NULL
        WHERE offer_id=?
        """,
        (
            texte,
            json.dumps(signalees, ensure_ascii=False),
            nb_mots,
            int(depasse),
            offer_id,
        ),
    )
    _append_version(
        conn, offer_id, texte, signalees, nb_mots, depasse, "moi", fait_retenu
    )
    conn.commit()


def ajouter_fait_ecarte(conn: sqlite3.Connection, offer_id: int) -> None:
    """Écarte le fait retenu courant de la lettre (critère 13) : l'ajoute (si
    absent) à la liste persistée des faits écartés de l'offre, identifiés par leur
    citation et leur lien (H2 du ticket) — ne touche pas le texte courant, la
    régénération qui suit s'en charge."""
    row = conn.execute(
        "SELECT statut, fait_retenu_json, faits_ecartes_json FROM lettres WHERE offer_id = ?",
        (offer_id,),
    ).fetchone()
    if row is None or row["statut"] != "done" or not row["fait_retenu_json"]:
        raise RienAEcarterError(RAISON_RIEN_A_ECARTER)
    fait = json.loads(row["fait_retenu_json"])
    ecartes = json.loads(row["faits_ecartes_json"] or "[]")
    if not any(_cle_fait(e) == _cle_fait(fait) for e in ecartes):
        ecartes.append(fait)
    conn.execute(
        "UPDATE lettres SET faits_ecartes_json=? WHERE offer_id=?",
        (json.dumps(ecartes, ensure_ascii=False), offer_id),
    )
    conn.commit()


def retirer_fait_ecarte(
    conn: sqlite3.Connection, offer_id: int, citation: str | None, url: str | None
) -> None:
    """Remet un fait écarté (critère 15) : le retire de la liste persistée, sans
    déclencher de régénération."""
    row = conn.execute(
        "SELECT faits_ecartes_json FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    ecartes = (
        json.loads(row["faits_ecartes_json"])
        if row and row["faits_ecartes_json"]
        else []
    )
    restants = [
        e for e in ecartes if (e.get("citation"), e.get("url")) != (citation, url)
    ]
    conn.execute(
        "UPDATE lettres SET faits_ecartes_json=? WHERE offer_id=?",
        (json.dumps(restants, ensure_ascii=False), offer_id),
    )
    conn.commit()
