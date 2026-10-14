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
    normaliser_angle,
    resolve_offer_text,
)
from orchestrator.job_search.paths import LETTRE_TOURNURES_PATH
from orchestrator.job_search.storage.db import get_connection, init_db
from orchestrator.job_search.tracking.lettre_tracing import tracer_generation

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


RAISON_PAS_MA_MAIN = (
    "La lettre affichée n'est pas une version que j'ai réécrite moi-même."
)


class LettrePasDeMaMainError(RuntimeError):
    """La lettre affichée n'est pas une version « moi » (EXE-173, critère 2) :
    repartir d'elle n'a pas de sens, refusé avant tout appel de modèle."""


class RienAEcarterError(RuntimeError):
    """Aucun fait retenu à écarter (EXE-162, critère 17) : lettre générique ou
    jamais générée."""


# EXE-171, critère 9 : au-delà, l'angle est refusé avant tout enregistrement —
# donc avant tout appel de modèle, puisqu'il n'est jamais stocké.
MAX_ANGLE_CHARS = 1500


def raison_angle_trop_long() -> str:
    return f"L'angle ne peut pas dépasser {MAX_ANGLE_CHARS} caractères."


class AngleTropLongError(ValueError):
    """Angle normalisé de plus de MAX_ANGLE_CHARS caractères (EXE-171, critère 9)."""


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
    angle_utilise: str | None  # EXE-171, critère 10 : None si générée sans angle
    # EXE-173, critère 9 : le jugement du tout premier appel du juge sur ma
    # lettre — None hors reprise depuis ma lettre.
    jugement_ma_lettre: dict | None = None
    # EXE-175, critère 7 : le tour de la lettre retenue (0 = ma lettre elle-même,
    # jamais réécrite) — distinct de `nb_tours`, le nombre de tours exécutés.
    tour_retenu: int = 0


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
    angle_utilise: str | None = None,
    repartie_de_ma_lettre: bool = False,
    appels: list[dict] | None = None,
    trace_id: str | None = None,
) -> None:
    """Ajoute une version à l'historique — jamais de réécriture ni de suppression
    d'une version existante (invariant du ticket EXE-66). Porte le fait retenu
    (EXE-162, critère 7) et le modèle qui l'a écrite, absent pour une reprise à
    la main (EXE-166, critère 6). Pour une version écrite par la boucle (EXE-169,
    critères 4, 6, 8) : le modèle du juge à part du modèle choisi, et le verdict
    du juge sur cette lettre (ses quatre rubriques, le nombre de tours, la raison
    de fin) — tous absents pour une reprise à la main, pour qu'une régénération
    ultérieure ne touche jamais le jugement déjà écrit dans l'historique.
    `angle_utilise` (EXE-171, critère 10) : l'angle qui a produit cette version,
    absent (None) si elle vient du tamis ou d'une reprise à la main.
    `repartie_de_ma_lettre` (EXE-173, critère 10) : vraie seulement pour la
    version finale d'une boucle repartie d'une version « moi ».
    `appels`/`trace_id` (EXE-174, critères 1, 2, 8) : les appels de modèle de la
    génération qui a produit cette version et l'identifiant de sa trace MLflow —
    absents (None) pour une reprise à la main."""
    conn.execute(
        """
        INSERT INTO lettre_versions
            (offer_id, texte, tournures_signalees_json, nb_mots, depasse_longueur,
             origine, fait_retenu_json, created_at, modele, modele_juge,
             jugement_json, nb_tours, raison_fin, angle_utilise,
             repartie_de_ma_lettre, appels_json, trace_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            angle_utilise,
            int(repartie_de_ma_lettre),
            json.dumps(appels, ensure_ascii=False) if appels else None,
            trace_id,
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


def save_angle(
    conn: sqlite3.Connection, offer_id: int, angle: str | None
) -> str | None:
    """Enregistre mon angle d'accroche (EXE-171, critères 5, 7, 9) : refuse avant
    tout enregistrement (donc avant tout appel de modèle) si l'angle normalisé
    dépasse MAX_ANGLE_CHARS, sinon enregistre l'angle normalisé (None si vide ou
    seulement des espaces). Crée la ligne `lettres` si elle n'existe pas encore —
    l'angle peut être écrit avant que la fiche entreprise ait terminé (critère 8)."""
    normalise = normaliser_angle(angle)
    if normalise is not None and len(normalise) > MAX_ANGLE_CHARS:
        raise AngleTropLongError(raison_angle_trop_long())
    conn.execute(
        """
        INSERT INTO lettres (offer_id, statut, angle, created_at) VALUES (?, 'aucune', ?, ?)
        ON CONFLICT(offer_id) DO UPDATE SET angle=excluded.angle
        """,
        (offer_id, normalise, _now()),
    )
    conn.commit()
    return normalise


def _fetch_angle(conn: sqlite3.Connection, offer_id: int) -> str | None:
    row = conn.execute(
        "SELECT angle FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    return row["angle"] if row else None


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
    ma_lettre: str | None = None,
) -> _GenerationBoucle:
    """Lance la boucle tamis → rédaction → vérificateur → juge (critère 1), sur
    les points de la fiche terminée moins les faits écartés (critères 4, 14) —
    jamais sur les points cochés ni la désignation de la fiche. Tourne dans un
    thread (critère 2) : `generer_lettre_depuis_donnees` appelle `asyncio.run` en
    interne, incompatible avec la boucle d'événements de l'API.

    `on_etape` (EXE-167) : transmis tel quel à la boucle, appelé depuis le
    thread — optionnel, sans effet quand personne ne l'écoute (critère 6).

    `ma_lettre` (EXE-173, critères 3, 5) : absent par défaut. Rempli, la boucle
    repart de ce texte — le juge la lit avant toute reprise."""
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
    # EXE-171, critère 8 : relu à chaque génération/régénération — tant que mon
    # angle est rempli, toute génération de cette offre part de lui.
    angle = _fetch_angle(conn, offer_id)

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
        angle=angle,
        ma_lettre=ma_lettre,
        **kwargs_etape,
    )

    if (
        resultat.raison_fin != RAISON_RIEN_A_REDIRE
        and not resultat.raison_fin.startswith(RAISON_PLAFOND)
    ):
        raise RuntimeError(resultat.raison_fin)

    derniere = resultat.lettre_retenue
    texte = derniere["texte"]
    nb_mots = derniere["nb_mots"]
    signalees = derniere.get("tournures_signalees") or []
    jugement = derniere["jugement"]
    releve = dernier_releve(derniere)
    fait_retenu = None if resultat.fait_retenu == GENERIQUE_ID else resultat.fait_retenu
    jugement_ma_lettre = (
        asdict(resultat.jugement_ma_lettre)
        if resultat.jugement_ma_lettre is not None
        else None
    )

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
        angle_utilise=angle,
        jugement_ma_lettre=jugement_ma_lettre,
        tour_retenu=derniere.get("tour", 0),
    )


def _mode_generation(gen: _GenerationBoucle, *, repartie_de_ma_lettre: bool) -> str:
    """Mode de génération porté par la trace MLflow (EXE-174, critère 7) : les
    trois valeurs possibles sont mutuellement exclusives — une reprise depuis
    ma lettre ne part jamais du tamis ni de mon angle (EXE-173, critère 3)."""
    if repartie_de_ma_lettre:
        return "depuis_ma_lettre"
    return "angle" if gen.angle_utilise else "tamis"


def _tracer(
    gen: _GenerationBoucle, offer_id: int, modele: str, mode: str
) -> str | None:
    return tracer_generation(
        gen.appels,
        offer_id=offer_id,
        mode=mode,
        modele_redaction=modele,
        modele_juge=gen.modele_juge,
        raison_fin=gen.raison_fin,
    )


def _update_lettre_courante(
    conn: sqlite3.Connection,
    offer_id: int,
    gen: _GenerationBoucle,
    modele: str,
    *,
    repartie_de_ma_lettre: bool = False,
) -> None:
    """Remplace la lettre courante par une génération réussie — régénération
    ordinaire ou reprise depuis ma lettre qui l'a réécrite (EXE-173, critères
    5-10) : même mise à jour, plus la marque de reprise sur la nouvelle version
    dans ce second cas. Trace MLflow de la génération (EXE-174, critères 6-9) :
    calculée ici, jamais dans la boucle — le banc n'appelle jamais ce chemin."""
    mode = _mode_generation(gen, repartie_de_ma_lettre=repartie_de_ma_lettre)
    trace_id = _tracer(gen, offer_id, modele, mode)
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
        angle_utilise=gen.angle_utilise,
        repartie_de_ma_lettre=repartie_de_ma_lettre,
        appels=gen.appels,
        trace_id=trace_id,
    )


def valider_repart_de_ma_lettre(conn: sqlite3.Connection, offer_id: int) -> str:
    """Refuse avant tout appel de modèle (EXE-173, critère 2) si la lettre
    affichée n'est pas une version que j'ai réécrite moi-même — rend son texte
    sinon, pour amorcer la boucle dessus (critère 3)."""
    row = conn.execute(
        "SELECT statut, texte FROM lettres WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None or row["statut"] != "done":
        raise LettrePasDeMaMainError(RAISON_PAS_MA_MAIN)
    derniere = conn.execute(
        "SELECT origine FROM lettre_versions WHERE offer_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (offer_id,),
    ).fetchone()
    if derniere is None or derniere["origine"] != "moi":
        raise LettrePasDeMaMainError(RAISON_PAS_MA_MAIN)
    return row["texte"]


def enregistrer_jugement_sur_ma_version(
    conn: sqlite3.Connection,
    offer_id: int,
    jugement: dict | None,
    modele_juge: str,
    appels: list[dict] | None = None,
    trace_id: str | None = None,
) -> None:
    """EXE-173, critère 9 : pose le jugement du juge sur ma version la plus
    récente écrite à la main (origine='moi') — remplace, pour ce seul cas,
    l'absence de jugement sur une reprise à la main (EXE-169, critère 8). Ne
    touche ni le texte ni rien d'autre de cette version — jamais réécrite,
    jamais effacée. `appels`/`trace_id` (EXE-174, critère 3) : l'appel du juge
    sur ma lettre, posé ici quand la régénération depuis ma lettre ne produit
    aucune nouvelle version."""
    row = conn.execute(
        "SELECT id FROM lettre_versions WHERE offer_id = ? AND origine = 'moi' "
        "ORDER BY id DESC LIMIT 1",
        (offer_id,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "UPDATE lettre_versions SET jugement_json=?, modele_juge=?, "
        "appels_json=?, trace_id=? WHERE id=?",
        (
            json.dumps(jugement, ensure_ascii=False) if jugement else None,
            modele_juge,
            json.dumps(appels, ensure_ascii=False) if appels else None,
            trace_id,
            row["id"],
        ),
    )


def _store_generation(
    conn: sqlite3.Connection, offer_id: int, gen: _GenerationBoucle, modele: str
) -> None:
    mode = _mode_generation(gen, repartie_de_ma_lettre=False)
    trace_id = _tracer(gen, offer_id, modele, mode)
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
        angle_utilise=gen.angle_utilise,
        appels=gen.appels,
        trace_id=trace_id,
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
            _update_lettre_courante(conn, offer_id, gen, modele)
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


async def run_lettre_regenerate_depuis_ma_lettre(
    offer_id: int,
    ma_lettre: str,
    modele: str = MODELE_PAR_DEFAUT,
    on_etape: Callable[[dict], None] | None = None,
) -> None:
    """Repart de ma lettre (EXE-173) : le juge la lit d'abord (critère 3), sur
    le modèle choisi pour la rédaction si une reprise s'ensuit — le juge reste
    toujours sur `MODELE_JUGE` (EXE-169). Son jugement est posé sur ma version
    (critère 9) quoi qu'il arrive. S'il n'a rien à redire, ma lettre reste la
    lettre courante, sans nouvelle version (critère 4). Sinon, la rédaction la
    reprend depuis ce ressenti (critères 5-8), et la version finale porte la
    marque « repartie de ma lettre » (critère 10). Même traitement d'échec que
    `run_lettre_regenerate` : la version d'avant reste en place intacte."""
    conn = get_connection()
    try:
        init_db(conn)
        try:
            gen = await _generate_via_boucle(
                conn, offer_id, modele, on_etape, ma_lettre=ma_lettre
            )
            # EXE-175, critère 7 : la lettre retenue peut être ma propre lettre
            # (tour 0) même après des reprises au plafond — même traitement
            # que « rien à redire », aucune version n'est créée.
            if gen.tour_retenu > 0:
                # Critère 3 : une nouvelle version naît — ses appels et sa
                # trace vont sur elle, pas sur ma version ; seul le jugement
                # (déjà posé par le juge sur ma lettre) y est répété.
                enregistrer_jugement_sur_ma_version(
                    conn, offer_id, gen.jugement_ma_lettre, MODELE_JUGE
                )
                _update_lettre_courante(
                    conn, offer_id, gen, modele, repartie_de_ma_lettre=True
                )
            else:
                # Critère 3/4/7 : rien à redire sur ma lettre, ou la lettre
                # retenue au plafond est ma lettre elle-même — elle reste la
                # lettre courante, aucune version n'est créée. L'appel unique
                # du juge et sa trace sont gardés sur ma version.
                trace_id = _tracer(gen, offer_id, modele, "depuis_ma_lettre")
                enregistrer_jugement_sur_ma_version(
                    conn,
                    offer_id,
                    gen.jugement_ma_lettre,
                    MODELE_JUGE,
                    appels=gen.appels,
                    trace_id=trace_id,
                )
                conn.execute(
                    """
                    UPDATE lettres SET
                        jugement_json=?, nb_tours=0, raison_fin=?, modele_juge=?,
                        regeneration_en_cours=0, regeneration_error=NULL
                    WHERE offer_id=?
                    """,
                    (
                        json.dumps(gen.jugement_ma_lettre, ensure_ascii=False)
                        if gen.jugement_ma_lettre
                        else None,
                        gen.raison_fin,
                        MODELE_JUGE,
                        offer_id,
                    ),
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
