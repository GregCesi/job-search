"""Endpoints offres + verdicts."""
import json
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from .db import get_conn
from .schemas import CriterionScore, OfferDetail, OfferRow, VerdictIn

log = logging.getLogger(__name__)
router = APIRouter()

_SORT_COLS = {"score", "fetched_at", "title", "company"}


# ---------------------------------------------------------------------------
# L2 — GET /offers
# ---------------------------------------------------------------------------

@router.get("/offers", response_model=list[OfferRow])
def list_offers(
    score_min: float | None = Query(None),
    score_max: float | None = Query(None),
    remote: bool | None = Query(None),
    source: str | None = Query(None),
    verdict: str | None = Query(None),
    seen: bool | None = Query(None),
    q: str | None = Query(None, description="Recherche texte sur title + company"),
    sort: str = Query("score", pattern="^(score|fetched_at|title|company)$"),
    order: Literal["asc", "desc"] = Query("desc"),
) -> list[OfferRow]:
    conditions: list[str] = []
    params: list = []

    if score_min is not None:
        conditions.append("o.score >= ?")
        params.append(score_min)
    if score_max is not None:
        conditions.append("o.score <= ?")
        params.append(score_max)
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
    sort_col = sort if sort in _SORT_COLS else "score"
    sql = f"""
        SELECT o.id, o.title, o.company, o.location, o.remote, o.contract_type,
               o.score, o.seen, o.fetched_at, v.status AS verdict
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
            score=r["score"],
            verdict=r["verdict"],
            seen=bool(r["seen"]),
            fetched_at=r["fetched_at"] or "",
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# L3 — GET /offers/{id}  (effet de bord : seen = 1)
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

        # Effet de bord : marquer comme vu
        conn.execute("UPDATE offers SET seen = 1 WHERE id = ?", (offer_id,))
        conn.commit()
    finally:
        conn.close()

    criteria = _parse_criteria(row["criteria_json"], offer_id)

    return OfferDetail(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        remote=bool(row["remote"]),
        contract_type=row["contract_type"],
        score=row["score"],
        verdict=row["verdict"],
        seen=True,
        fetched_at=row["fetched_at"] or "",
        description=row["description"],
        url=row["url"],
        source=row["source"],
        criteria=criteria,
    )


def _parse_criteria(raw: str | None, offer_id: int) -> list[CriterionScore]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return [CriterionScore(**item) for item in data]
    except Exception as exc:
        log.warning("criteria_json parse failed for offer %s: %s", offer_id, exc)
        return []


# ---------------------------------------------------------------------------
# L4 — PUT /offers/{id}/verdict  (UPSERT)
#       DELETE /offers/{id}/verdict
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
