"""Endpoints offres + verdicts."""
import json
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .db import get_conn
from .schemas import (
    AttainabilityDetailSchema,
    CriterionSchema,
    ExtractedFactsSchema,
    OfferDetail,
    OfferRow,
    ReviewIn,
    ReviewOut,
    VerdictIn,
)

log = logging.getLogger(__name__)
router = APIRouter()

_SORT_COLS = {"desirability", "fetched_at", "title", "company"}


# ---------------------------------------------------------------------------
# GET /offers
# ---------------------------------------------------------------------------

@router.get("/offers", response_model=list[OfferRow])
def list_offers(
    desirability_min: float | None = Query(None),
    desirability_max: float | None = Query(None),
    attainability: str | None = Query(None, pattern="^(at_level|one_step_up|out_of_reach)$"),
    remote: bool | None = Query(None),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
    seen: bool | None = Query(None),
    filtered_out: bool | None = Query(None, description="None=exclut les filtrées, True=seulement les filtrées, False=non filtrées"),
    q: str | None = Query(None, description="Recherche texte sur title + company"),
    sort: str = Query("desirability", pattern="^(desirability|fetched_at|title|company)$"),
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

    if desirability_min is not None:
        conditions.append("o.desirability >= ?")
        params.append(desirability_min)
    if desirability_max is not None:
        conditions.append("o.desirability <= ?")
        params.append(desirability_max)
    if attainability is not None:
        conditions.append("o.attainability = ?")
        params.append(attainability)
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
    if q is not None:
        conditions.append("(LOWER(o.title) LIKE ? OR LOWER(o.company) LIKE ?)")
        like = f"%{q.lower()}%"
        params.extend([like, like])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sort_col = sort if sort in _SORT_COLS else "desirability"
    sql = f"""
        SELECT o.id, o.title, o.company, o.location, o.remote, o.contract_type,
               o.desirability, o.attainability, o.seen, o.fetched_at,
               o.filtered_out, o.filter_reason,
               v.status AS verdict
        FROM offers o
        LEFT JOIN verdicts v ON v.offer_id = o.id
        {where}
        ORDER BY o.{sort_col} {order.upper()} NULLS LAST
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
            desirability=r["desirability"],
            attainability=r["attainability"],
            verdict=r["verdict"],
            seen=bool(r["seen"]),
            fetched_at=r["fetched_at"] or "",
            filtered_out=bool(r["filtered_out"]),
            filter_reason=r["filter_reason"],
        )
        for r in rows
    ]


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

    desirability_detail = _parse_json(row["desirability_detail"], offer_id, "desirability_detail")
    attainability_detail = _parse_attainability(row["attainability_detail"], offer_id)

    return OfferDetail(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        remote=bool(row["remote"]),
        contract_type=row["contract_type"],
        desirability=row["desirability"],
        attainability=row["attainability"],
        verdict=row["verdict"],
        seen=True,
        fetched_at=row["fetched_at"] or "",
        filtered_out=bool(row["filtered_out"]),
        filter_reason=row["filter_reason"],
        description=row["description"],
        url=row["url"],
        source=row["source"],
        extracted_facts=_parse_facts(row["extracted_facts_json"], offer_id),
        desirability_detail=desirability_detail,
        attainability_detail=attainability_detail,
        criteria=_build_criteria(desirability_detail, attainability_detail),
    )


def _parse_facts(raw: str | None, offer_id: int) -> ExtractedFactsSchema | None:
    if not raw:
        return None
    try:
        return ExtractedFactsSchema(**json.loads(raw))
    except Exception as exc:
        log.warning("extracted_facts_json parse failed for offer %s: %s", offer_id, exc)
        return None


def _parse_json(raw: str | None, offer_id: int, field: str) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as exc:
        log.warning("%s parse failed for offer %s: %s", field, offer_id, exc)
        return None


def _parse_attainability(raw: str | None, offer_id: int) -> AttainabilityDetailSchema | None:
    if not raw:
        return None
    try:
        return AttainabilityDetailSchema(**json.loads(raw))
    except Exception as exc:
        log.warning("attainability_detail parse failed for offer %s: %s", offer_id, exc)
        return None


def _build_criteria(
    desirability_detail: dict | None,
    attainability_detail: AttainabilityDetailSchema | None,
) -> list[CriterionSchema]:
    """Normalise les champs de scoring existants vers une liste {nom, note 0-10, justif, axe}.

    Hypothèse de stabilité vérifiée au point de validation C-2 (IMPLEMENTATION-calibration.md).
    """
    criteria: list[CriterionSchema] = []

    if desirability_detail:
        domain = desirability_detail.get("domain")
        if domain:
            gradient = float(domain.get("gradient", domain.get("score", 0)))
            value = domain.get("value", "?")
            criteria.append(CriterionSchema(
                nom="domain",
                note=round(gradient * 10, 1),
                justif=f"{value} (gradient {gradient:.2f})",
                axe="desirability",
            ))

    if attainability_detail:
        gap = attainability_detail.seniority_gap
        seniority_note = 10.0 if gap <= 0 else (7.0 if gap == 1 else 0.0)
        gap_str = f"{'+' if gap > 0 else ''}{gap}"
        criteria.append(CriterionSchema(
            nom="seniority",
            note=seniority_note,
            justif=f"Écart séniorité : {gap_str}",
            axe="attainability",
        ))

        matched = attainability_detail.techs_matched
        missing = attainability_detail.techs_missing
        total = len(matched) + len(missing)
        if total > 0:
            coverage = len(matched) / total
            tech_note = round(coverage * 10, 1)
            justif_parts: list[str] = []
            if matched:
                justif_parts.append(f"✓ {', '.join(matched)}")
            if missing:
                justif_parts.append(f"✗ {', '.join(missing)}")
            criteria.append(CriterionSchema(
                nom="tech_coverage",
                note=tech_note,
                justif=" — ".join(justif_parts) or "aucune techno requise",
                axe="attainability",
            ))

    return criteria


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
# PUT /offers/{id}/review   — upsert human review + snapshot IA (L7/L9)
# GET /offers/{id}/review   — hydratation (L8)
# ---------------------------------------------------------------------------

@router.put("/offers/{offer_id}/review", status_code=204)
def upsert_review(offer_id: int, body: ReviewIn) -> None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT seen, desirability_detail, attainability_detail FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="offer not found")

        desr_detail = _parse_json(row["desirability_detail"], offer_id, "desirability_detail")
        att_detail = _parse_attainability(row["attainability_detail"], offer_id)
        criteria = _build_criteria(desr_detail, att_detail)
        ai_snapshot = [c.model_dump() for c in criteria]
        seen_at_review = bool(row["seen"])
        now = datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO human_reviews
                (offer_id, ratings_json, ai_snapshot_json,
                 global_audit_text, global_score, seen_at_review, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(offer_id) DO UPDATE SET
                ratings_json      = excluded.ratings_json,
                ai_snapshot_json  = excluded.ai_snapshot_json,
                global_audit_text = excluded.global_audit_text,
                global_score      = excluded.global_score,
                seen_at_review    = excluded.seen_at_review,
                created_at        = excluded.created_at
            """,
            (
                str(offer_id),
                json.dumps(body.ratings_json),
                json.dumps(ai_snapshot),
                body.global_audit_text,
                body.global_score,
                int(seen_at_review),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


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
