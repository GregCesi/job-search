"""Endpoints offres + verdicts."""
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db import get_conn
from .schemas import (
    CategoryReviewIn,
    ExtractedFactsSchema,
    OfferDetail,
    OfferRow,
    ReviewOut,
    VerdictIn,
)

log = logging.getLogger(__name__)
router = APIRouter()

_SORT_COLS = {"fetched_at", "title", "company", "category"}


def _derive_review_fields(row) -> dict:
    """Dérive categorie_finale + etat_review à la volée (jamais persistés)."""
    suggeree = row["categorie_suggeree"]
    corrigee = row["categorie_corrigee"]
    reviewed_at = row["reviewed_at"]
    if reviewed_at is None:
        etat = "non_relue"
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
    }


# ---------------------------------------------------------------------------
# GET /offers
# ---------------------------------------------------------------------------

@router.get("/offers", response_model=list[OfferRow])
def list_offers(
    remote: bool | None = Query(None),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
    seen: bool | None = Query(None),
    filtered_out: bool | None = Query(None, description="None=exclut les filtrées, True=seulement les filtrées, False=non filtrées"),
    category: str | None = Query(None, description="parfait | reve | atteignable | hors"),
    hors_perimetre: bool | None = Query(None, description="True=seulement hors-périmètre, False=exclut hors-périmètre, None=tout"),
    etat_review: str | None = Query(None, description="non_relue | validee | corrigee"),
    q: str | None = Query(None, description="Recherche texte sur title + company"),
    sort: str = Query("category", pattern="^(fetched_at|title|company|category)$"),
    order: Literal["asc", "desc"] = Query("desc"),
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
    if verdict is not None:
        conditions.append("v.status = ?")
        params.append(verdict)
    if seen is not None:
        conditions.append("o.seen = ?")
        params.append(1 if seen else 0)
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
        sort_col = sort if sort in _SORT_COLS else "category"
        order_clause = f"o.{sort_col} {order.upper()} NULLS LAST"
    sql = f"""
        SELECT o.id, o.title, o.company, o.location, o.remote, o.contract_type,
               o.category, o.seen, o.fetched_at, o.filtered_out, o.filter_reason,
               o.hors_perimetre_reason,
               o.categorie_suggeree, o.categorie_corrigee, o.remarque, o.reviewed_at,
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

    return [
        OfferRow(
            id=r["id"],
            title=r["title"],
            company=r["company"],
            location=r["location"],
            remote=bool(r["remote"]),
            contract_type=r["contract_type"],
            category=r["category"],
            verdict=r["verdict"],
            hors_perimetre_reason=r["hors_perimetre_reason"],
            seen=bool(r["seen"]),
            fetched_at=r["fetched_at"] or "",
            **_derive_review_fields(r),
            filtered_out=bool(r["filtered_out"]),
            filter_reason=r["filter_reason"],
        )
        for r in rows
    ]


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
# GET /offers/{id}  (effet de bord : seen = 1)
# ---------------------------------------------------------------------------

@router.get("/offers/{offer_id}", response_model=OfferDetail)
def get_offer(offer_id: int) -> OfferDetail:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT o.*, v.status AS verdict
            FROM offers o
            LEFT JOIN verdicts v ON v.offer_id = o.id
            WHERE o.id = ?
            """,
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="offer not found")

        conn.execute("UPDATE offers SET seen = 1 WHERE id = ?", (offer_id,))
        conn.commit()
    finally:
        conn.close()

    return OfferDetail(
        id=row["id"],
        source_id=row["source_id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        remote=bool(row["remote"]),
        contract_type=row["contract_type"],
        category=row["category"],
        verdict=row["verdict"],
        hors_perimetre_reason=row["hors_perimetre_reason"],
        seen=True,
        fetched_at=row["fetched_at"] or "",
        filtered_out=bool(row["filtered_out"]),
        filter_reason=row["filter_reason"],
        **_derive_review_fields(row),
        description=row["description"],
        url=row["url"],
        source=row["source"],
        extracted_facts=_parse_facts(row["extracted_facts_json"], offer_id),
        techs_matched=json.loads(row["techs_matched_json"]) if row["techs_matched_json"] else [],
        techs_missing=json.loads(row["techs_missing_json"]) if row["techs_missing_json"] else [],
    )


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
            parse_failed=data.get("parse_failed", False),
        )
    except Exception as exc:
        log.warning("extracted_facts_json parse failed for offer %s: %s", offer_id, exc)
        return None


# ---------------------------------------------------------------------------
# PUT /offers/{id}/verdict  (UPSERT)
# DELETE /offers/{id}/verdict
# ---------------------------------------------------------------------------

@router.put("/offers/{offer_id}/verdict", status_code=204)
def upsert_verdict(offer_id: int, body: VerdictIn) -> None:
    conn = get_conn()
    try:
        offer = conn.execute("SELECT id FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")

        existing = conn.execute(
            "SELECT id FROM verdicts WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            conn.execute(
                "UPDATE verdicts SET status = ?, created_at = ? WHERE offer_id = ?",
                (body.status, now, offer_id),
            )
        else:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, body.status, now),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# PUT /offers/{id}/category-review  — review de catégorie (chantier review humaine L3)
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {"parfait", "reve", "atteignable", "hors", "hors_perimetre"}


@router.put("/offers/{offer_id}/category-review", status_code=204)
def upsert_category_review(offer_id: int, body: CategoryReviewIn) -> None:
    if body.categorie_corrigee is not None and body.categorie_corrigee not in _VALID_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"categorie_corrigee must be one of {_VALID_CATEGORIES}")

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
    conn = get_conn()
    try:
        offer = conn.execute("SELECT id FROM offers WHERE id = ?", (offer_id,)).fetchone()
        if offer is None:
            raise HTTPException(status_code=404, detail="offer not found")
        conn.execute("DELETE FROM verdicts WHERE offer_id = ?", (offer_id,))
        conn.commit()
    finally:
        conn.close()
