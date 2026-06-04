import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from orchestrator.job_search.scoring.attainability import Attainability
from orchestrator.job_search.scoring.categorize import ScoredOffer
from orchestrator.job_search.scoring.desirability import Desirability
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
    desirability: float | None
    desirability_detail: str | None   # JSON
    attainability: float | None       # score 0-100 (chantier 2 — était ReachLevel string)
    attainability_detail: str | None  # JSON {attain_tech, attain_role, blocked_by, techs_matched, techs_missing}
    category: str | None = None
    score_in_category: float | None = None
    attain_tech: float | None = None
    attain_role: float | None = None
    blocked_by: str | None = None
    description: str | None = None
    filtered_out: bool = False
    filter_reason: str | None = None


def save_offer(
    conn: sqlite3.Connection,
    offer: JobOffer,
    desirability: Desirability | None,
    attainability: Attainability | None,
    scored: ScoredOffer | None = None,
    filtered_out: bool = False,
    filter_reason: str | None = None,
) -> None:
    """Upsert offer with scores. Filtered offers are saved without scores."""
    facts_json = (
        offer.extracted_facts.model_dump_json()
        if offer.extracted_facts is not None
        else None
    )
    attainability_detail = (
        json.dumps({
            "attain_tech":    attainability.attain_tech,
            "attain_role":    attainability.attain_role,
            "blocked_by":     attainability.blocked_by,
            "techs_matched":  attainability.techs_matched,
            "techs_missing":  attainability.techs_missing,
        })
        if attainability is not None
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
             extracted_facts_json, desirability, desirability_detail,
             attainability, attainability_detail,
             category, score_in_category, attain_tech, attain_role, blocked_by,
             filtered_out, filter_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            extracted_facts_json = excluded.extracted_facts_json,
            desirability         = excluded.desirability,
            desirability_detail  = excluded.desirability_detail,
            attainability        = excluded.attainability,
            attainability_detail = excluded.attainability_detail,
            category             = excluded.category,
            score_in_category    = excluded.score_in_category,
            attain_tech          = excluded.attain_tech,
            attain_role          = excluded.attain_role,
            blocked_by           = excluded.blocked_by,
            description          = excluded.description,
            filtered_out         = excluded.filtered_out,
            filter_reason        = excluded.filter_reason
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
            desirability.score if desirability is not None else None,
            json.dumps(desirability.detail) if desirability is not None else None,
            attainability.score if attainability is not None else None,
            attainability_detail,
            scored.category.value if scored is not None else None,
            scored.score_in_category if scored is not None else None,
            attainability.attain_tech if attainability is not None else None,
            attainability.attain_role if attainability is not None else None,
            attainability.blocked_by if attainability is not None else None,
            int(filtered_out),
            filter_reason,
        ),
    )
    conn.commit()


def get_offers_since(
    conn: sqlite3.Connection,
    since: datetime,
    min_desirability: float = 0.0,
    limit: int = 50,
) -> list[StoredOffer]:
    """Return scored (non-filtered) offers fetched after `since`, ordered by score_in_category desc."""
    rows = conn.execute(
        """
        SELECT id, source, source_id, title, company, location, remote,
               contract_type, url, fetched_at, description,
               desirability, desirability_detail, attainability, attainability_detail,
               category, score_in_category, attain_tech, attain_role, blocked_by,
               filtered_out, filter_reason
        FROM offers
        WHERE fetched_at >= ?
          AND filtered_out = 0
          AND (desirability IS NULL OR desirability >= ?)
        ORDER BY score_in_category DESC NULLS LAST
        LIMIT ?
        """,
        (since.isoformat(), min_desirability, limit),
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
            desirability=r["desirability"],
            desirability_detail=r["desirability_detail"],
            attainability=r["attainability"],
            attainability_detail=r["attainability_detail"],
            category=r["category"],
            score_in_category=r["score_in_category"],
            attain_tech=r["attain_tech"],
            attain_role=r["attain_role"],
            blocked_by=r["blocked_by"],
            description=r["description"],
            filtered_out=bool(r["filtered_out"]),
            filter_reason=r["filter_reason"],
        )
        for r in rows
    ]
