import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class HumanReview:
    offer_id: str
    ratings_json: str
    ai_snapshot_json: str
    global_audit_text: str | None
    global_score: int | None
    seen_at_review: bool
    created_at: str


def upsert_review(
    conn: sqlite3.Connection,
    offer_id: str,
    ratings_json: str,
    ai_snapshot_json: str,
    global_audit_text: str | None = None,
    global_score: int | None = None,
    seen_at_review: bool = False,
) -> None:
    """Insert or replace a human review. created_at is always overwritten."""
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
            offer_id,
            ratings_json,
            ai_snapshot_json,
            global_audit_text,
            global_score,
            int(seen_at_review),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def get_review(conn: sqlite3.Connection, offer_id: str) -> HumanReview | None:
    """Return the review for offer_id, or None if absent."""
    row = conn.execute(
        "SELECT * FROM human_reviews WHERE offer_id = ?", (offer_id,)
    ).fetchone()
    if row is None:
        return None
    return HumanReview(
        offer_id=row["offer_id"],
        ratings_json=row["ratings_json"],
        ai_snapshot_json=row["ai_snapshot_json"],
        global_audit_text=row["global_audit_text"],
        global_score=row["global_score"],
        seen_at_review=bool(row["seen_at_review"]),
        created_at=row["created_at"],
    )
