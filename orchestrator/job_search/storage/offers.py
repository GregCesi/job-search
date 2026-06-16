import sqlite3
from dataclasses import dataclass
from datetime import datetime

from orchestrator.job_search.scoring.categorize import Category
from orchestrator.job_search.sources.base import JobOffer


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
    category: str | None = None
    description: str | None = None
    filtered_out: bool = False
    filter_reason: str | None = None


def save_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    *,
    category: Category | None = None,
    filtered_out: bool = False,
    filter_reason: str | None = None,
    hors_perimetre_reason: str | None = None,
) -> None:
    """Upsert offer. Filtered/hors-périmètre offers saved without category."""
    facts_json = (
        offer.extracted_facts.model_dump_json()
        if offer.extracted_facts is not None
        else None
    )
    full_time_int = None if offer.full_time is None else int(offer.full_time)

    conn.execute(
        """
        INSERT INTO offers
            (source, source_id, fingerprint, title, company, location,
             remote, contract_type, nature_contract, alternance, full_time,
             company_size, experience_required, rome_code, rome_label,
             url, fetched_at, description, seen,
             extracted_facts_json, category,
             filtered_out, filter_reason, hors_perimetre_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            extracted_facts_json  = excluded.extracted_facts_json,
            category              = excluded.category,
            description           = excluded.description,
            filtered_out          = excluded.filtered_out,
            filter_reason         = excluded.filter_reason,
            hors_perimetre_reason = excluded.hors_perimetre_reason
        """,
        (
            offer.source, offer.source_id, offer.fingerprint,
            offer.title, offer.company, offer.location,
            int(offer.remote), offer.contract_type, offer.nature_contract,
            int(offer.alternance), full_time_int,
            offer.company_size, offer.experience_required,
            offer.rome_code, offer.rome_label,
            offer.url, offer.fetched_at.isoformat(), offer.description,
            facts_json,
            category.value if category is not None else None,
            int(filtered_out),
            filter_reason,
            hors_perimetre_reason,
        ),
    )
    conn.commit()


def get_offers_since(
    conn: sqlite3.Connection,
    since: datetime,
    limit: int = 50,
) -> list[StoredOffer]:
    """Return non-filtered offers fetched after `since`, ordered by category."""
    rows = conn.execute(
        """
        SELECT id, source, source_id, title, company, location, remote,
               contract_type, url, fetched_at, description,
               category, filtered_out, filter_reason
        FROM offers
        WHERE fetched_at >= ?
          AND filtered_out = 0
        ORDER BY
            CASE category
                WHEN 'parfait'     THEN 1
                WHEN 'reve'        THEN 2
                WHEN 'atteignable' THEN 3
                WHEN 'hors'        THEN 4
                ELSE 5
            END ASC
        LIMIT ?
        """,
        (since.isoformat(), limit),
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
            category=r["category"],
            description=r["description"],
            filtered_out=bool(r["filtered_out"]),
            filter_reason=r["filter_reason"],
        )
        for r in rows
    ]
