"""Export endpoints — calibration + export à la carte.

GET /export/calibration
    → texte markdown, offres notées triées par désaccord décroissant, lots de 15.
GET /export/offers
    → texte markdown, offres filtrées avec champs à la carte.
"""
import json
import math
from datetime import timezone
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from .db import get_conn
from orchestrator.job_search.storage.reviews import HumanReview
from orchestrator.job_search.calibration.disagreement import disagreement, DisagreementScore

router = APIRouter()

_VALID_INCLUDE = {"description", "techs", "role", "domain", "category", "location", "contract", "url", "company"}
_DEFAULT_INCLUDE = {"company", "category", "techs"}


# ---------------------------------------------------------------------------
# GET /export/offers
# ---------------------------------------------------------------------------

@router.get("/export/offers", response_class=PlainTextResponse)
def export_offers(
    remote: bool | None = Query(None),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
    category: str | None = Query(None),
    hors_perimetre: bool | None = Query(None),
    etat_review: str | None = Query(None),
    q: str | None = Query(None),
    sort: str = Query("category", pattern="^(fetched_at|title|company|category)$"),
    order: Literal["asc", "desc"] = Query("desc"),
    include: str | None = Query(None, description="Champs à inclure (comma-separated). Défaut: company,category,techs"),
) -> str:
    # --- parse include ---
    if include:
        fields = {f.strip() for f in include.split(",") if f.strip() in _VALID_INCLUDE}
    else:
        fields = set(_DEFAULT_INCLUDE)

    # --- build WHERE (même logique que list_offers) ---
    conditions: list[str] = ["o.filtered_out = 0"]
    params: list = []

    if remote is not None:
        conditions.append("o.remote = ?")
        params.append(1 if remote else 0)
    if source is not None:
        conditions.append("o.source = ?")
        params.append(source)
    if verdict is not None:
        conditions.append("v.status = ?")
        params.append(verdict)
    if category is not None:
        conditions.append("o.category = ?")
        params.append(category)
    if hors_perimetre is True:
        conditions.append("o.hors_perimetre_reason IS NOT NULL")
    elif hors_perimetre is False:
        conditions.append("o.hors_perimetre_reason IS NULL")
    if etat_review == "non_relue":
        conditions.append("o.reviewed_at IS NULL")
    elif etat_review == "validee":
        conditions.append("o.reviewed_at IS NOT NULL AND o.categorie_corrigee IS NULL")
    elif etat_review == "corrigee":
        conditions.append("o.categorie_corrigee IS NOT NULL")
    if q is not None:
        conditions.append("(LOWER(o.title) LIKE ? OR LOWER(o.company) LIKE ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    if sort == "category":
        order_clause = """
            CASE o.category
                WHEN 'parfait'     THEN 1
                WHEN 'reve'        THEN 2
                WHEN 'atteignable' THEN 3
                WHEN 'hors'        THEN 4
                ELSE 5
            END ASC"""
    else:
        _sort_cols = {"fetched_at", "title", "company", "category"}
        sort_col = sort if sort in _sort_cols else "category"
        order_clause = f"o.{sort_col} {order.upper()} NULLS LAST"

    sql = f"""
        SELECT o.id, o.title, o.company, o.location, o.remote, o.contract_type,
               o.category, o.url, o.description, o.source,
               o.extracted_facts_json, o.techs_matched_json, o.techs_missing_json,
               o.categorie_suggeree, o.categorie_corrigee, o.hors_perimetre_reason,
               v.status AS verdict
        FROM offers o
        LEFT JOIN verdicts v ON v.offer_id = o.id
        {where}
        ORDER BY {order_clause}
    """
    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return _format_export_md(rows, fields)


def _format_export_md(rows: list, fields: set[str]) -> str:
    lines: list[str] = [f"# Export — {len(rows)} offre(s)\n"]

    for r in rows:
        # Heading: title toujours, company si demandée
        title = r["title"] or "(sans titre)"
        if "company" in fields and r["company"]:
            lines.append(f"## {title} — {r['company']}")
        else:
            lines.append(f"## {title}")

        # Catégorie finale (corrigee > suggeree > category)
        if "category" in fields:
            cat = r["categorie_corrigee"] or r["categorie_suggeree"] or r["category"] or "?"
            lines.append(f"- Catégorie : {cat}")

        # Techs (depuis extracted_facts_json)
        if "techs" in fields:
            techs_str = _format_techs(r["extracted_facts_json"])
            if techs_str:
                lines.append(f"- Techs : {techs_str}")

        # Domain / role (depuis extracted_facts_json)
        facts = _parse_facts_raw(r["extracted_facts_json"])
        if "domain" in fields and facts.get("domain"):
            lines.append(f"- Domaine : {facts['domain']}")
        if "role" in fields and facts.get("role_level"):
            lines.append(f"- Role : {facts['role_level']}")

        if "location" in fields and r["location"]:
            lines.append(f"- Localisation : {r['location']}")
        if "contract" in fields and r["contract_type"]:
            lines.append(f"- Contrat : {r['contract_type']}")
        if "url" in fields and r["url"]:
            lines.append(f"- URL : {r['url']}")

        # Description en bloc
        if "description" in fields and r["description"]:
            lines.append(f"\n{r['description']}")

        lines.append("")

    return "\n".join(lines)


def _parse_facts_raw(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _format_techs(facts_json: str | None) -> str:
    facts = _parse_facts_raw(facts_json)
    techs = facts.get("techs_required", [])
    if not techs:
        return ""
    parts = []
    for t in techs:
        if isinstance(t, dict):
            name = t.get("name", "?")
            imp = t.get("importance")
            parts.append(f"{name} ({imp})" if imp else name)
        else:
            parts.append(str(t))
    return ", ".join(parts)

_PAGE_SIZE = 15


@router.get("/export/calibration", response_class=PlainTextResponse)
def export_calibration() -> str:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT hr.offer_id, hr.ratings_json, hr.ai_snapshot_json,
                   hr.global_audit_text, hr.global_score, hr.seen_at_review, hr.created_at,
                   o.title, o.company
            FROM human_reviews hr
            LEFT JOIN offers o ON CAST(hr.offer_id AS INTEGER) = o.id
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return "# Calibration\n\nAucune review enregistrée.\n"

    scored: list[tuple[DisagreementScore, dict]] = []
    for row in rows:
        review = HumanReview(
            offer_id=row["offer_id"],
            ratings_json=row["ratings_json"],
            ai_snapshot_json=row["ai_snapshot_json"],
            global_audit_text=row["global_audit_text"],
            global_score=row["global_score"],
            seen_at_review=bool(row["seen_at_review"]),
            created_at=row["created_at"],
        )
        score = disagreement(review)
        scored.append((score, {
            "title": row["title"] or f"offre #{row['offer_id']}",
            "company": row["company"] or "?",
            "review": review,
        }))

    scored.sort(key=lambda x: x[0].distance_total, reverse=True)

    n_pages = max(1, math.ceil(len(scored) / _PAGE_SIZE))
    lines: list[str] = [
        f"# Calibration — {len(scored)} offre(s) notée(s)",
        f"Triées par désaccord décroissant · lots de {_PAGE_SIZE}\n",
    ]

    for page in range(n_pages):
        batch = scored[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]
        if n_pages > 1:
            lines.append(f"---\n## Lot {page + 1}/{n_pages}\n")

        for ds, meta in batch:
            review: HumanReview = meta["review"]
            ratings: dict = json.loads(review.ratings_json)
            snapshot: list[dict] = json.loads(review.ai_snapshot_json)
            ai_by_nom = {c["nom"]: c for c in snapshot}

            lines.append(f"### {meta['title']} — {meta['company']}")
            lines.append(
                f"distance_total={ds.distance_total:.2f}"
                + (f"  désir={ds.distance_desirability:.2f}" if ds.distance_desirability is not None else "")
                + (f"  attein={ds.distance_attainability:.2f}" if ds.distance_attainability is not None else "")
                + f"  couverture={ds.n_criteria_rated} critère(s)"
                + f"  date={review.created_at[:10]}"
            )

            # Détail par critère co-noté
            for nom, human_val in ratings.items():
                h_note = human_val.get("note") if isinstance(human_val, dict) else None
                if h_note is None:
                    continue
                ai_c = ai_by_nom.get(nom)
                if ai_c is None:
                    continue
                ai_note = ai_c.get("note")
                diff = abs(float(h_note) - float(ai_note)) if ai_note is not None else None
                diff_str = f"Δ={diff:.1f}" if diff is not None else "Δ=?"
                h_justif = (human_val.get("justif") or "").strip()
                lines.append(
                    f"- **{nom}** : IA={ai_note}/10 → humain={h_note}/10 ({diff_str})"
                    + (f" — {h_justif}" if h_justif else "")
                )

            if review.global_score is not None:
                lines.append(f"- Note globale humaine : {review.global_score}/10")
            if review.global_audit_text:
                lines.append(f"> {review.global_audit_text}")

            lines.append("")

    return "\n".join(lines)
