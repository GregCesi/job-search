"""Endpoints offres + verdicts."""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from orchestrator.job_search.pieces import (
    DECISION_SANS_LETTRE,
    cv_statut,
    lettre_statut,
    libelle_tout_telecharger,
    pieces_a_envoyer,
)
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

from . import cascade
from .db import get_conn
from .schemas import (
    CategoryReviewIn,
    ExpirationCheckSchema,
    ExtractedFactsSchema,
    OfferDetail,
    OfferRow,
    ReviewOut,
    VerdictIn,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Score breakdown — dérivé à la volée, jamais persisté (IMPLEMENTATION.md L1)
# ---------------------------------------------------------------------------

_scoring_ctx: dict | None = None


def _load_scoring_context() -> dict:
    """Charge profil + alias table une seule fois (cachés module-level)."""
    global _scoring_ctx
    if _scoring_ctx is not None:
        return _scoring_ctx
    try:
        from orchestrator.job_search.matching.profile import load_profile
        from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH
        from orchestrator.job_search.scoring.aliases import load_alias_table

        profile, _ = load_profile(PROFILE_PATH)
        table = load_alias_table(ALIAS_PATH)
        _scoring_ctx = {"profile": profile, "table": table}
    except Exception as exc:
        log.warning("scoring context unavailable: %s", exc)
        _scoring_ctx = {"profile": None, "table": None}
    return _scoring_ctx


def _derive_score_breakdown(row) -> str | None:
    """Ligne unique expliquant pourquoi l'offre est dans sa catégorie."""
    raw = row["extracted_facts_json"]
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if data.get("parse_failed"):
        return None

    category = row["category"]
    if not category or category not in ("parfait", "reve", "atteignable", "hors"):
        return None

    ctx = _load_scoring_context()
    profile = ctx["profile"]
    table = ctx["table"]
    if profile is None or table is None:
        return None

    try:
        from orchestrator.job_search.scoring.attainability import compute_attainability
        from orchestrator.job_search.scoring.desirability import compute_desirability
        from orchestrator.job_search.sources.base import ExtractedFacts

        facts = ExtractedFacts.model_validate(data)
        desir = compute_desirability(facts, profile.search_criteria, profile, table)
        attain = compute_attainability(facts, profile, table)
    except Exception as exc:
        log.warning("score_breakdown failed for offer %s: %s", row["id"], exc)
        return None

    if category == "parfait":
        return "Parfait — rien ne bloque."

    # Blockers atteignabilité
    attain_parts: list[str] = []
    if attain.blocked_by == "role" or (
        attain.blocked_by is None and attain.attain_role < attain.attain_tech
    ):
        attain_parts.append(
            f"poste {facts.role_level.value}, ta cible est {profile.role_ceiling.value}"
        )
    if attain.seniority_malus > 0:
        ceiling_label = (
            profile.seniority_ceiling.value if profile.seniority_ceiling else "?"
        )
        attain_parts.append(
            f"séniorité {facts.seniority_required.value}, cible {ceiling_label} (−{attain.seniority_malus:.0f})"
        )
    if attain.techs_missing:
        # Top 3 missing, importance core/required seulement
        top_missing: list[str] = []
        for t in facts.techs_required:
            if t.name in attain.techs_missing and t.importance in ("core", "required"):
                top_missing.append(f"{t.name} ({t.importance})")
                if len(top_missing) >= 3:
                    break
        if top_missing:
            attain_parts.append(f"manque {', '.join(top_missing)}")

    # Blocker désirabilité
    desir_parts: list[str] = []
    domain_info = desir.detail.get("domain", {})
    domain_val = domain_info.get("value", "")
    domain_preferred = domain_info.get("preferred", [])
    domain_gradient = domain_info.get("gradient", 0.0)
    if domain_gradient < 0.5:
        cible = ", ".join(domain_preferred) if domain_preferred else "?"
        desir_parts.append(f"{domain_val}, hors cible {cible}")

    if category == "reve":
        # Désirable, PAS atteignable → blocker(s) atteignabilité
        if attain_parts:
            return f"Rêve — atteignabilité bloque : {' ; '.join(attain_parts)}"
        return "Rêve — atteignabilité limite."

    if category == "atteignable":
        # Atteignable, PEU désirable → blocker désirabilité (domaine)
        if desir_parts:
            return f"Atteignable — désirabilité bloque : {' ; '.join(desir_parts)}"
        return "Atteignable — désirabilité limite."

    # hors — combiner les deux
    parts = desir_parts + attain_parts
    if parts:
        return f"Hors — {' ; '.join(parts)}"
    return "Hors — scoring insuffisant."


router = APIRouter()

_SORT_COLS = {
    "fetched_at",
    "title",
    "company",
    "category",
    "seen_candidat",
    "hors_perimetre_reason",
}

# Rang du verdict combiné (tri ou revue hors périmètre, la revue gagnant —
# cf. `_verdict_label`) pour le tri composite (critère 20).
_VERDICT_ORDER = {
    "retenu": 1,
    "hors_perimetre_faux_pos": 2,
    "hors_perimetre_ok": 3,
    "ecartee": 4,
}

# Séquence fixe affichée en tête d'une offre retenue (critère 15) — seules les
# étapes du chemin « heureux » ; une offre qui a bifurqué (refusée, sans
# suite, abandonnée) n'y figure pas mais `etape` dit où elle est réellement.
ETAPES_AFFICHEES = [
    suivi_etats.RETENUE,
    suivi_etats.PRETE_A_L_ENVOI,
    suivi_etats.CANDIDATURE_ENVOYEE,
    suivi_etats.ENTRETIEN,
]


def _derive_review_fields(row) -> dict:
    """Dérive categorie_finale + etat_review + staleness à la volée (jamais persistés)."""
    suggeree = row["categorie_suggeree"]
    corrigee = row["categorie_corrigee"]
    reviewed_at = row["reviewed_at"]

    # suggestion_actuelle = ce que l'IA pense MAINTENANT
    if row["hors_perimetre_reason"] is not None:
        suggestion_actuelle = "hors_perimetre"
    elif row["category"]:
        suggestion_actuelle = row["category"]
    else:
        suggestion_actuelle = None

    # review_stale = un rescore a eu lieu après la dernière review
    rescored_at = row["rescored_at"]
    review_stale = (
        reviewed_at is not None
        and rescored_at is not None
        and rescored_at > reviewed_at
    )

    if reviewed_at is None:
        etat = "non_relue"
    elif review_stale:
        etat = "a_revoir"
    elif corrigee is not None:
        etat = "corrigee"
    else:
        etat = "validee"

    return {
        "categorie_suggeree": suggeree,
        "categorie_corrigee": corrigee,
        "categorie_finale": corrigee if corrigee is not None else suggeree,
        "etat_review": etat,
        "remarque": row["remarque"],
        "reviewed_at": reviewed_at,
        "review_stale": review_stale,
        "suggestion_actuelle": suggestion_actuelle,
    }


def _pieces_pretes_depuis_row(row) -> tuple[bool, bool, bool]:
    cv_row = (
        {"marque_pret_at": row["cv_marque_pret_at"]}
        if row["cv_id"] is not None
        else None
    )
    lettre_row = (
        {
            "statut": row["lettre_statut_raw"],
            "marque_pret_at": row["lettre_marque_pret_at"],
        }
        if row["lettre_id"] is not None
        else None
    )
    lettre_sans = row["lettre_decision_raw"] == DECISION_SANS_LETTRE
    return (
        cv_statut(cv_row) == "prete",
        lettre_statut(lettre_row) == "prete",
        lettre_sans,
    )


def _derive_etape(row, etat: str) -> str | None:
    """Étape de candidature d'une offre retenue — dérivée à la lecture,
    jamais persistée. Passe par le module d'états (TCK-311, EXE-193) pour la
    table, par `orchestrator.job_search.pieces` pour le statut des pièces."""
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes_depuis_row(row)
    return suivi_etats.etape_affichee(
        etat, cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    )


def _verdict_label(etat: str, revue: str | None) -> str | None:
    if revue is not None:
        return revue
    t = suivi_etats.tri(etat)
    if t == suivi_etats.RETENUE:
        return "retenu"
    if t == suivi_etats.ECARTEE:
        return "ecartee"
    return None


def _correspond_au_filtre_verdict(
    tri_val: str, revue_val: str | None, filtre: str | None
) -> bool:
    """Critère 12 : le filtre `verdict=retenu`/`ecartee` se décide sur le tri
    seul — jamais masqué par la revue hors périmètre, qui a son propre axe et
    son propre filtre (`hors_perimetre_ok`/`hors_perimetre_faux_pos`)."""
    if filtre is None:
        return True
    if filtre == "retenu":
        return tri_val == suivi_etats.RETENUE
    if filtre == "ecartee":
        return tri_val == suivi_etats.ECARTEE
    if filtre == "a_trier":
        return tri_val == suivi_etats.A_TRIER
    if filtre in ("hors_perimetre_ok", "hors_perimetre_faux_pos"):
        return revue_val == filtre
    return False


def _message_ecarter_refuse(etat: str) -> str:
    """Critère 18 : dit ce qui est possible depuis cette étape (ses gestes
    permis), jamais un conseil figé — libellés, jamais de code interne
    (critère 17)."""
    permis = suivi_etats.gestes_permis(etat)
    libelle_etat = suivi_etats.LIBELLES_ETATS.get(etat, etat)
    if not permis:
        return f"Une offre « {libelle_etat} » ne s'écarte pas directement : aucun geste n'est possible depuis cette étape."
    libelles = ", ".join(f"« {suivi_etats.LIBELLES_GESTES.get(g, g)} »" for g in permis)
    return (
        f"Une offre « {libelle_etat} » ne s'écarte pas directement : "
        f"depuis cette étape, c'est possible par {libelles}."
    )


def _gestes_permis_depuis_row(row, etat: str, hist: list) -> list[str]:
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes_depuis_row(row)
    return suivi_etats.gestes_permis_effectifs(
        etat,
        cv_pret=cv_pret,
        lettre_pret=lettre_pret,
        lettre_sans=lettre_sans,
        annulable=suivi_etats.permis_annuler(hist),
    )


def _gestes_avec_etat_depuis_row(row, etat: str, hist: list) -> list[dict]:
    """Chaque geste de la table, permis ou non avec son libellé et sa raison
    (critère 14 ; libellé dynamique de l'annulation — EXE-194, critère 15)."""
    cv_pret, lettre_pret, lettre_sans = _pieces_pretes_depuis_row(row)
    return [
        {"geste": g.geste, "permis": g.permis, "libelle": g.libelle, "raison": g.raison}
        for g in suivi_etats.gestes_avec_etat(
            etat,
            cv_pret=cv_pret,
            lettre_pret=lettre_pret,
            lettre_sans=lettre_sans,
            dernier_annulable=suivi_etats.dernier_geste_non_annule(hist),
        )
    ]


def _ecart_depuis_hist(hist: list) -> tuple[str | None, str | None]:
    """(ecartee_le, motif_ecart) dérivés du dernier geste `ecarter` non annulé
    (EXE-194, critères 9, 11)."""
    ev = suivi_etats.dernier_ecart(hist)
    if ev is None:
        return None, None
    return ev.effet_at, ev.motif


def _tout_telecharger(
    cv_pret: bool, lettre_pret: bool, lettre_sans: bool
) -> tuple[bool, str | None]:
    """Si « Tout télécharger » est possible, et sinon pourquoi, en clair
    (critère 16 — EXE-200 ; `lettre_sans` compte comme la lettre prête,
    EXE-196 critères 1-5)."""
    if suivi_etats.pieces_pretes_pour_envoi(
        cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    ):
        return True, None
    if not cv_pret and not (lettre_pret or lettre_sans):
        return False, "Le CV et la lettre ne sont pas encore prêts."
    if not cv_pret:
        return False, "Le CV n'est pas encore prêt."
    return False, "La lettre n'est pas encore prête."


# ---------------------------------------------------------------------------
# GET /offers
# ---------------------------------------------------------------------------


@router.get("/offers", response_model=list[OfferRow])
def list_offers(
    remote: bool | None = Query(None),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
    seen_candidat: bool | None = Query(None),
    filtered_out: bool | None = Query(
        None,
        description="None=exclut les filtrées, True=seulement les filtrées, False=non filtrées",
    ),
    category: str | None = Query(
        None, description="parfait | reve | atteignable | hors"
    ),
    exclude_category: str | None = Query(
        None, description="Exclut les offres de cette catégorie (ex: hors)"
    ),
    hors_perimetre: bool | None = Query(
        None,
        description="True=seulement hors-périmètre, False=exclut hors-périmètre, None=tout",
    ),
    hp_cause: str | None = Query(
        None, description="Filtre par cause HP : no_tech | mgmt_role | contrat"
    ),
    extraction_status: str | None = Query(
        None,
        description="pending (inclut à refaire) | unreadable | "
        "second_pass_pending — EXE-98/EXE-99 | missing_text — EXE-115",
    ),
    exclude_ad_language: str | None = Query(
        None,
        description="Exclut les offres dont ad_language est dans cette liste (comma-separated, ex: nl)",
    ),
    etat_review: str | None = Query(None, description="non_relue | validee | corrigee"),
    q: str | None = Query(None, description="Recherche texte sur title + company"),
    view_profile: bool | None = Query(None),
    include_remote: bool | None = Query(None),
    sort: str = Query("category"),
    order: str = Query("desc"),
) -> list[OfferRow]:
    conditions: list[str] = []
    params: list = []

    # Par défaut on exclut les offres filtrées (stage, hors-zone, etc.)
    if filtered_out is None:
        conditions.append("o.filtered_out = 0")
    elif filtered_out:
        conditions.append("o.filtered_out = 1")
    else:
        conditions.append("o.filtered_out = 0")

    if remote is not None:
        conditions.append("o.remote = ?")
        params.append(1 if remote else 0)
    if source is not None:
        conditions.append("o.source = ?")
        params.append(source)
    if seen_candidat is not None:
        conditions.append("o.seen_candidat = ?")
        params.append(1 if seen_candidat else 0)
    if category is not None:
        conditions.append("o.category = ?")
        params.append(category)
    if exclude_category is not None:
        conditions.append("o.category != ?")
        params.append(exclude_category)
    if hors_perimetre is True:
        conditions.append("o.hors_perimetre_reason IS NOT NULL")
    elif hors_perimetre is False:
        conditions.append("o.hors_perimetre_reason IS NULL")
    if hp_cause is not None:
        conditions.append("o.perimetre_causes LIKE ?")
        params.append(f'%"{hp_cause}"%')
    if extraction_status == "pending":
        conditions.append("o.extraction_status IN ('pending', 'retry')")
    elif extraction_status == "unreadable":
        conditions.append("o.extraction_status = 'unreadable'")
    elif extraction_status == "second_pass_pending":
        conditions.append("o.extraction_status = 'second_pass_pending'")
    elif extraction_status == "missing_text":
        conditions.append("o.extraction_status = 'missing_text'")
    if exclude_ad_language is not None:
        langs = [
            lang.strip() for lang in exclude_ad_language.split(",") if lang.strip()
        ]
        if langs:
            placeholders = ",".join("?" * len(langs))
            conditions.append(
                f"(o.ad_language IS NULL OR o.ad_language NOT IN ({placeholders}))"
            )
            params.extend(langs)
    if etat_review is not None:
        etats = [e.strip() for e in etat_review.split(",") if e.strip()]
        if etats:
            clauses = []
            for e in etats:
                if e == "non_relue":
                    clauses.append("o.reviewed_at IS NULL")
                elif e == "validee":
                    clauses.append(
                        "(o.reviewed_at IS NOT NULL AND o.categorie_corrigee IS NULL AND (o.rescored_at IS NULL OR o.rescored_at <= o.reviewed_at))"
                    )
                elif e == "corrigee":
                    clauses.append(
                        "(o.categorie_corrigee IS NOT NULL AND (o.rescored_at IS NULL OR o.rescored_at <= o.reviewed_at))"
                    )
                elif e == "a_revoir":
                    clauses.append(
                        "(o.reviewed_at IS NOT NULL AND o.rescored_at IS NOT NULL AND o.rescored_at > o.reviewed_at)"
                    )
            if clauses:
                conditions.append(f"({' OR '.join(clauses)})")
    if q is not None:
        conditions.append("(LOWER(o.title) LIKE ? OR LOWER(o.company) LIKE ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like])
    if view_profile is True:
        from api.view_profile import build_view_clauses

        zone_conds, zone_params = build_view_clauses()
        zone_conds = list(zone_conds)
        if include_remote is True:
            zone_conds.append("o.remote = 1")
        if zone_conds:
            conditions.append(f"({' OR '.join(zone_conds)})")
            params.extend(zone_params)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Tri composite : sort=col1,col2 + order=dir1,dir2
    sort_parts = [s.strip() for s in sort.split(",")]
    order_parts = [o.strip() for o in order.split(",")]
    # Étendre order_parts si moins d'entrées que sort_parts
    while len(order_parts) < len(sort_parts):
        order_parts.append(order_parts[-1] if order_parts else "desc")

    conn = get_conn()
    try:
        etat_par_offre = suivi_storage.etat_map(conn)
        revue_par_offre = suivi_storage.revue_hors_perimetre_map(conn)
        hist_par_offre = suivi_storage.historique_map(conn)

        # Le verdict n'est pas une colonne SQL : un CASE sur o.id, construit à
        # partir des rangs calculés ci-dessus, lui donne sa vraie place dans un
        # tri composite (critère 20) — jamais un tri Python après coup, qui
        # écrasait l'ordre des colonnes demandé.
        verdict_case_sql = "5"
        verdict_case_params: list = []
        if "verdict" in sort_parts:
            cases = []
            for oid, etat in etat_par_offre.items():
                label = _verdict_label(etat, revue_par_offre.get(oid))
                rank = _VERDICT_ORDER.get(label)
                if rank is not None:
                    cases.append("WHEN ? THEN ?")
                    verdict_case_params.extend([oid, rank])
            if cases:
                verdict_case_sql = f"CASE o.id {' '.join(cases)} ELSE 5 END"

        # Date du dernier écart, pour trier Écartées « la plus récente d'abord »
        # (EXE-194, critère 9) — même technique que le verdict ci-dessus : un
        # CASE précalculé en Python, jamais un tri Python après coup.
        ecartee_case_sql = "NULL"
        ecartee_case_params: list = []
        if "ecartee_le" in sort_parts:
            cases = []
            for oid, hist in hist_par_offre.items():
                ev = suivi_etats.dernier_ecart(hist)
                if ev is not None:
                    cases.append("WHEN ? THEN ?")
                    ecartee_case_params.extend([oid, ev.effet_at])
            if cases:
                ecartee_case_sql = f"CASE o.id {' '.join(cases)} ELSE NULL END"

        order_clauses: list[str] = []
        order_params: list = []
        for s, o in zip(sort_parts, order_parts):
            d = o.upper() if o.upper() in ("ASC", "DESC") else "DESC"
            if s == "category":
                order_clauses.append(f"""
                    CASE o.category
                        WHEN 'parfait'     THEN 1
                        WHEN 'reve'        THEN 2
                        WHEN 'atteignable' THEN 3
                        WHEN 'hors'        THEN 4
                        ELSE 5
                    END {d}""")
            elif s == "location":
                order_clauses.append(f"""
                    CASE WHEN o.remote = 1 THEN 1 ELSE 0 END {d},
                    o.location {d} NULLS LAST""")
            elif s == "contract_type":
                order_clauses.append(f"""
                    CASE o.contract_type
                        WHEN 'CDI'       THEN 1
                        WHEN 'Permanent' THEN 2
                        WHEN 'Full-time' THEN 3
                        WHEN 'Freelance' THEN 4
                        WHEN 'LIB'       THEN 5
                        WHEN 'CDD'       THEN 6
                        WHEN 'MIS'       THEN 7
                        WHEN 'Part-time' THEN 8
                        ELSE 9
                    END {d}""")
            elif s == "verdict":
                order_clauses.append(f"{verdict_case_sql} {d}")
                order_params.extend(verdict_case_params)
            elif s == "ecartee_le":
                order_clauses.append(f"{ecartee_case_sql} {d} NULLS LAST")
                order_params.extend(ecartee_case_params)
            elif s in _SORT_COLS:
                order_clauses.append(f"o.{s} {d} NULLS LAST")
            else:
                order_clauses.append("o.category DESC")
        order_clause = ", ".join(order_clauses) if order_clauses else "o.category DESC"
        sql = f"""
            SELECT o.id, o.title, o.company, o.location, o.remote, o.contract_type,
                   o.category, o.seen_candidat, o.fetched_at, o.filtered_out, o.filter_reason,
                   o.hors_perimetre_reason, o.perimetre_causes,
                   o.categorie_suggeree, o.categorie_corrigee, o.remarque, o.reviewed_at,
                   o.rescored_at, o.extraction_status, o.extraction_attempts,
                   c.id AS cv_id, c.marque_pret_at AS cv_marque_pret_at,
                   l.id AS lettre_id, l.statut AS lettre_statut_raw,
                   l.marque_pret_at AS lettre_marque_pret_at,
                   l.decision AS lettre_decision_raw,
                   ex.expired AS expiration_expired
            FROM offers o
            LEFT JOIN cvs c ON c.offer_id = o.id
            LEFT JOIN lettres l ON l.offer_id = o.id
            LEFT JOIN expirations ex ON ex.offer_id = o.id
            {where}
            ORDER BY {order_clause}
        """
        rows = conn.execute(sql, params + order_params).fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        etat = etat_par_offre.get(r["id"], suivi_etats.A_TRIER)
        revue = revue_par_offre.get(r["id"])
        verdict_label = _verdict_label(etat, revue)
        tri_val = suivi_etats.tri(etat)
        if not _correspond_au_filtre_verdict(tri_val, revue, verdict):
            continue
        hist = hist_par_offre.get(r["id"], [])
        ecartee_le, motif_ecart = _ecart_depuis_hist(hist)
        result.append(
            OfferRow(
                id=r["id"],
                title=r["title"],
                company=r["company"],
                location=r["location"],
                remote=bool(r["remote"]),
                contract_type=r["contract_type"],
                category=r["category"],
                verdict=verdict_label,
                tri=tri_val,
                revue_hors_perimetre=revue,
                etape=_derive_etape(r, etat),
                gestes_permis=_gestes_permis_depuis_row(r, etat, hist),
                gestes=_gestes_avec_etat_depuis_row(r, etat, hist),
                hors_perimetre_reason=r["hors_perimetre_reason"],
                perimetre_causes=json.loads(r["perimetre_causes"])
                if r["perimetre_causes"]
                else [],
                ecartee_le=ecartee_le,
                motif_ecart=motif_ecart,
                seen_candidat=bool(r["seen_candidat"]),
                fetched_at=r["fetched_at"] or "",
                **_derive_review_fields(r),
                filtered_out=bool(r["filtered_out"]),
                filter_reason=r["filter_reason"],
                expired=bool(r["expiration_expired"])
                if r["expiration_expired"] is not None
                else False,
                extraction_status=r["extraction_status"],
                extraction_attempts=r["extraction_attempts"] or 0,
            )
        )

    return result


# ---------------------------------------------------------------------------
# POST /offers/check-known  (dédup amont — read-only)
# ---------------------------------------------------------------------------


class _CheckKnownItem(BaseModel):
    title: str
    company: str
    location: str


@router.post("/offers/check-known")
def check_known(items: list[_CheckKnownItem]) -> dict:
    from orchestrator.job_search.sources.fingerprint import fingerprint

    fps = [fingerprint(it.title, it.company, it.location) for it in items]

    conn = get_conn()
    try:
        placeholders = ",".join("?" for _ in fps)
        rows = conn.execute(
            f"SELECT fingerprint FROM offers WHERE fingerprint IN ({placeholders})",
            fps,
        ).fetchall()
    finally:
        conn.close()

    known = {r["fingerprint"] for r in rows}
    new_indices = [i for i, fp in enumerate(fps) if fp not in known]
    return {
        "new_indices": new_indices,
        "known_count": len(fps) - len(new_indices),
        "new_count": len(new_indices),
    }


# ---------------------------------------------------------------------------
# GET /offers/{id}  (effet de bord : seen_candidat = 1)
# ---------------------------------------------------------------------------


@router.get("/offers/{offer_id}", response_model=OfferDetail)
def get_offer(offer_id: int) -> OfferDetail:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT o.*,
                   ex.employer_url AS expiration_employer_url,
                   ex.expired AS expiration_expired,
                   ex.last_checked_at AS expiration_last_checked_at,
                   ex.checks_json AS expiration_checks_json
            FROM offers o
            LEFT JOIN expirations ex ON ex.offer_id = o.id
            WHERE o.id = ?
            """,
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="offer not found")

        conn.execute("UPDATE offers SET seen_candidat = 1 WHERE id = ?", (offer_id,))
        conn.commit()

        etat = suivi_storage.etat_stocke(conn, offer_id)
        tri_val = suivi_etats.tri(etat)
        revue_val = suivi_storage.revue_hors_perimetre(conn, offer_id)
        verdict_label = suivi_storage.verdict_label(conn, offer_id)
        etape = suivi_storage.etape(conn, offer_id)
        gestes_permis = suivi_storage.gestes_permis(conn, offer_id)
        gestes = suivi_storage.gestes_avec_etat(conn, offer_id)
        etapes_acquises = suivi_storage.etapes_acquises(conn, offer_id)
        dernier_ecart_evt = suivi_storage.dernier_ecart(conn, offer_id)
        ecartee_le = dernier_ecart_evt.effet_at if dernier_ecart_evt else None
        motif_ecart = dernier_ecart_evt.motif if dernier_ecart_evt else None
        cv_pret, lettre_pret, lettre_sans = suivi_storage.pieces_pretes(conn, offer_id)
    finally:
        conn.close()

    tout_telecharger_possible, tout_telecharger_raison = _tout_telecharger(
        cv_pret, lettre_pret, lettre_sans
    )

    return OfferDetail(
        id=row["id"],
        source_id=row["source_id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        remote=bool(row["remote"]),
        contract_type=row["contract_type"],
        category=row["category"],
        verdict=verdict_label,
        tri=tri_val,
        revue_hors_perimetre=revue_val,
        etape=etape,
        gestes_permis=gestes_permis,
        gestes=[
            {
                "geste": g.geste,
                "permis": g.permis,
                "libelle": g.libelle,
                "raison": g.raison,
            }
            for g in gestes
        ],
        etapes_affichees=ETAPES_AFFICHEES if tri_val == suivi_etats.RETENUE else [],
        etapes_acquises=etapes_acquises,
        tout_telecharger_possible=tout_telecharger_possible,
        tout_telecharger_raison=tout_telecharger_raison,
        tout_telecharger_pieces=pieces_a_envoyer(lettre_sans),
        tout_telecharger_libelle=libelle_tout_telecharger(lettre_sans),
        ecartee_le=ecartee_le,
        motif_ecart=motif_ecart,
        hors_perimetre_reason=row["hors_perimetre_reason"],
        perimetre_causes=json.loads(row["perimetre_causes"])
        if row["perimetre_causes"]
        else [],
        seen_candidat=True,
        fetched_at=row["fetched_at"] or "",
        filtered_out=bool(row["filtered_out"]),
        filter_reason=row["filter_reason"],
        **_derive_review_fields(row),
        description=row["description"],
        url=row["url"],
        source=row["source"],
        extracted_facts=_parse_facts(row["extracted_facts_json"], offer_id),
        techs_matched=json.loads(row["techs_matched_json"])
        if row["techs_matched_json"]
        else [],
        techs_missing=json.loads(row["techs_missing_json"])
        if row["techs_missing_json"]
        else [],
        score_breakdown=_derive_score_breakdown(row),
        employer_url=row["expiration_employer_url"],
        last_checked_at=row["expiration_last_checked_at"],
        expiration_checks=_parse_expiration_checks(row["expiration_checks_json"]),
        expired=bool(row["expiration_expired"])
        if row["expiration_expired"] is not None
        else False,
        extraction_status=row["extraction_status"],
        extraction_attempts=row["extraction_attempts"] or 0,
        ad_language=row["ad_language"],
    )


def _parse_expiration_checks(raw: str | None) -> list[ExpirationCheckSchema]:
    if not raw:
        return []
    return [ExpirationCheckSchema(**c) for c in json.loads(raw)]


def _parse_facts(raw: str | None, offer_id: int) -> ExtractedFactsSchema | None:
    if not raw:
        return None
    try:
        from .schemas import TechSchema

        data = json.loads(raw)
        techs_raw = data.get("techs_required", [])
        techs = [
            TechSchema(name=t["name"], importance=t.get("importance"))
            if isinstance(t, dict)
            else TechSchema(name=t)
            for t in techs_raw
        ]
        return ExtractedFactsSchema(
            seniority_required=data.get("seniority_required", ""),
            techs_required=techs,
            domain=data.get("domain", ""),
            role_level=data.get("role_level"),
            langues_requises=data.get("langues_requises", []),
            parse_failed=data.get("parse_failed", False),
        )
    except Exception as exc:
        log.warning("extracted_facts_json parse failed for offer %s: %s", offer_id, exc)
        return None


# ---------------------------------------------------------------------------
# POST /offers/{id}/geste — tout geste de la table du module d'états
# (TCK-311, EXE-193, critère 13). Seuls Retenir, Écarter et Marquer envoyée
# sont câblés à un bouton candidat ce tour (via /verdict et /envoyee) ; les
# étapes suivantes (relancer, entretien, refuser…) arrivent au jet suivant,
# mais chaque geste de la table s'applique déjà par cette route.
# ---------------------------------------------------------------------------


class GesteIn(BaseModel):
    geste: str
    motif: str | None = None
    effet_at: str | None = None

    @field_validator("effet_at")
    @classmethod
    def _effet_at_doit_etre_une_date(cls, v: str | None) -> str | None:
        """Critère 21 : refusé en 422 avant toute écriture si `effet_at` n'est
        pas une date — la validation Pydantic tourne avant le corps de la
        route."""
        if v is not None:
            try:
                datetime.fromisoformat(v)
            except ValueError as exc:
                raise ValueError(f"effet_at n'est pas une date valide : {v!r}") from exc
        return v


@router.post("/offers/{offer_id}/geste")
async def appliquer_geste_route(offer_id: int, body: GesteIn) -> dict:
    conn = get_conn()
    launch = False
    try:
        offer = conn.execute(
            "SELECT id FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")
        try:
            if body.geste == suivi_etats.ANNULER:
                nouvel_etat = suivi_storage.annuler_dernier_geste(conn, offer_id)
            else:
                nouvel_etat = suivi_storage.appliquer_geste(
                    conn,
                    offer_id,
                    body.geste,
                    motif=body.motif,
                    effet_at=body.effet_at,
                )
                launch = body.geste == suivi_etats.RETENIR
        except (suivi_etats.GesteRefuse, suivi_etats.PiecesNonPretes) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()

    if launch:
        # Geste de retenir = action explicite de lancement (TCK-281) : la fiche
        # et le CV partent sans autre appel de ma part.
        await cascade.launch_pieces(offer_id)
    return {"etat": nouvel_etat}


# ---------------------------------------------------------------------------
# PUT /offers/{id}/verdict  (UPSERT)
# DELETE /offers/{id}/verdict
# ---------------------------------------------------------------------------


@router.put("/offers/{offer_id}/verdict", status_code=204)
async def upsert_verdict(offer_id: int, body: VerdictIn) -> None:
    conn = get_conn()
    launch = False
    try:
        offer = conn.execute(
            "SELECT id FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")

        if body.status in ("hors_perimetre_ok", "hors_perimetre_faux_pos"):
            suivi_storage.marquer_revue_hors_perimetre(conn, offer_id, body.status)
        elif body.status == "retenu":
            etat = suivi_storage.etat_stocke(conn, offer_id)
            if etat == suivi_etats.ECARTEE:
                suivi_storage.appliquer_geste(
                    conn, offer_id, suivi_etats.REMETTRE_A_TRIER
                )
                etat = suivi_etats.A_TRIER
            if etat == suivi_etats.A_TRIER:
                suivi_storage.appliquer_geste(conn, offer_id, suivi_etats.RETENIR)
                launch = True
        elif body.status == "ecartee":
            etat = suivi_storage.etat_stocke(conn, offer_id)
            if etat == suivi_etats.A_TRIER:
                suivi_storage.appliquer_geste(
                    conn, offer_id, suivi_etats.ECARTER, motif=body.motif
                )
            elif etat != suivi_etats.ECARTEE:
                raise HTTPException(
                    status_code=409, detail=_message_ecarter_refuse(etat)
                )
    finally:
        conn.close()

    if launch:
        # Geste de retenir = action explicite de lancement (TCK-281) : la fiche
        # et le CV partent sans autre appel de ma part.
        await cascade.launch_pieces(offer_id)


# ---------------------------------------------------------------------------
# PUT /offers/{id}/category-review  — review de catégorie (chantier review humaine L3)
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {"parfait", "reve", "atteignable", "hors", "hors_perimetre"}


@router.put("/offers/{offer_id}/category-review", status_code=204)
def upsert_category_review(offer_id: int, body: CategoryReviewIn) -> None:
    if (
        body.categorie_corrigee is not None
        and body.categorie_corrigee not in _VALID_CATEGORIES
    ):
        raise HTTPException(
            status_code=422,
            detail=f"categorie_corrigee must be one of {_VALID_CATEGORIES}",
        )

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, category, hors_perimetre_reason FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="offer not found")

        # Snapshot de la suggestion : category si présent, sinon hors_perimetre
        if row["hors_perimetre_reason"] is not None:
            suggeree = "hors_perimetre"
        else:
            suggeree = row["category"]

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE offers
            SET categorie_suggeree = ?,
                categorie_corrigee = ?,
                remarque           = ?,
                reviewed_at        = ?
            WHERE id = ?
            """,
            (suggeree, body.categorie_corrigee, body.remarque, now, offer_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# GET /offers/{id}/review   — lecture review calibration (legacy, lecture seule)
# ---------------------------------------------------------------------------


@router.get("/offers/{offer_id}/review", response_model=ReviewOut)
def get_review(offer_id: int) -> ReviewOut:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM human_reviews WHERE offer_id = ?",
            (str(offer_id),),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no review for this offer")
        return ReviewOut(
            offer_id=row["offer_id"],
            ratings_json=json.loads(row["ratings_json"]),
            ai_snapshot_json=json.loads(row["ai_snapshot_json"]),
            global_audit_text=row["global_audit_text"],
            global_score=row["global_score"],
            seen_at_review=bool(row["seen_at_review"]),
            created_at=row["created_at"],
        )
    finally:
        conn.close()


@router.delete("/offers/{offer_id}/verdict", status_code=204)
def delete_verdict(offer_id: int) -> None:
    """Annule le dernier geste du tri/de la candidature — ne touche JAMAIS la
    revue hors périmètre, axe à part (EXE-194, critère 16) : voir
    `retirer_revue` ci-dessous pour ça."""
    conn = get_conn()
    try:
        offer = conn.execute(
            "SELECT id FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")
        try:
            suivi_storage.annuler_dernier_geste(conn, offer_id)
        except suivi_etats.GesteRefuse:
            pass  # rien à annuler : déjà à trier
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DELETE /offers/{id}/revue — retire la revue hors périmètre, distinct de
# l'annulation (EXE-194, critère 17) : ne change jamais le tri ni l'historique.
# ---------------------------------------------------------------------------


@router.delete("/offers/{offer_id}/revue", status_code=204)
def retirer_revue(offer_id: int) -> None:
    conn = get_conn()
    try:
        offer = conn.execute(
            "SELECT id FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")
        if suivi_storage.revue_hors_perimetre(conn, offer_id) is None:
            raise HTTPException(
                status_code=409, detail="Aucune revue hors périmètre à retirer."
            )
        suivi_storage.effacer_revue_hors_perimetre(conn, offer_id)
    finally:
        conn.close()
