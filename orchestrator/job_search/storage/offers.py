import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from job_search.scoring.scorer import ScoringResult, criteria_to_json
from job_search.sources.base import JobOffer


@dataclass
class StoredOffer:
    id: int
    source: str
    source_id: str
    title: str
    company: str | None
    location: str | None
    remote: bool
    contract_type: str | None
    url: str
    fetched_at: str
    score: float | None
    criteria_json: str | None
    description: str | None = None


def save_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    result: ScoringResult,
) -> None:
    """Upsert offer with score and criteria. Updates score if offer already exists."""
    conn.execute(
        """
        INSERT INTO offers
            (source, source_id, fingerprint, title, company, location,
             remote, contract_type, url, fetched_at, score, criteria_json, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            score         = excluded.score,
            criteria_json = excluded.criteria_json,
            description   = excluded.description
        """,
        (
            offer.source,
            offer.source_id,
            offer.fingerprint,
            offer.title,
            offer.company,
            offer.location,
            int(offer.remote),
            offer.contract_type,
            offer.url,
            offer.fetched_at.isoformat(),
            result.global_score,
            criteria_to_json(result),
            offer.description,
        ),
    )
    conn.commit()


def get_offers_since(
    conn: sqlite3.Connection,
    since: datetime,
    min_score: float = 0.0,
    limit: int = 50,
) -> list[StoredOffer]:
    """Return offers fetched after `since`, ordered by score desc."""
    rows = conn.execute(
        """
        SELECT id, source, source_id, title, company, location, remote,
               contract_type, url, fetched_at, score, criteria_json
        FROM offers
        WHERE fetched_at >= ? AND (score IS NULL OR score >= ?)
        ORDER BY score DESC
        LIMIT ?
        """,
        (since.isoformat(), min_score, limit),
    ).fetchall()
    return [
        StoredOffer(
            id=r["id"],
            source=r["source"],
            source_id=r["source_id"],
            title=r["title"],
            company=r["company"],
            location=r["location"],
            remote=bool(r["remote"]),
            contract_type=r["contract_type"],
            url=r["url"],
            fetched_at=r["fetched_at"],
            score=r["score"],
            criteria_json=r["criteria_json"],
        )
        for r in rows
    ]
