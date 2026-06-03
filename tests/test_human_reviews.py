"""Round-trip tests for human_reviews — L2 validation."""
import json
import sqlite3

import pytest

from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.reviews import HumanReview, get_review, upsert_review


@pytest.fixture
def conn():
    """In-memory DB with full schema."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


def test_get_missing_returns_none(conn):
    assert get_review(conn, "offer-999") is None


def test_upsert_then_get_round_trip(conn):
    ratings = json.dumps({"tech_fit": {"note": 8, "justif": "bon match"}})
    snapshot = json.dumps([{"nom": "tech_fit", "note": 7, "justif": "IA note", "axe": "desirability"}])

    upsert_review(conn, "offer-1", ratings, snapshot, global_audit_text="ok", global_score=7, seen_at_review=True)

    review = get_review(conn, "offer-1")
    assert review is not None
    assert review.offer_id == "offer-1"
    assert json.loads(review.ratings_json) == json.loads(ratings)
    assert json.loads(review.ai_snapshot_json) == json.loads(snapshot)
    assert review.global_audit_text == "ok"
    assert review.global_score == 7
    assert review.seen_at_review is True
    assert review.created_at  # non-empty ISO8601


def test_upsert_is_idempotent(conn):
    ratings_v1 = json.dumps({"tech_fit": {"note": 5, "justif": "v1"}})
    ratings_v2 = json.dumps({"tech_fit": {"note": 9, "justif": "v2"}})
    snapshot = json.dumps([])

    upsert_review(conn, "offer-2", ratings_v1, snapshot)
    upsert_review(conn, "offer-2", ratings_v2, snapshot, global_score=9)

    review = get_review(conn, "offer-2")
    assert json.loads(review.ratings_json)["tech_fit"]["note"] == 9
    assert review.global_score == 9
    # Only one row
    count = conn.execute("SELECT COUNT(*) FROM human_reviews WHERE offer_id = 'offer-2'").fetchone()[0]
    assert count == 1


def test_migration_idempotent(conn):
    """Running init_db twice on the same connection must not raise."""
    init_db(conn)  # second call
    assert get_review(conn, "x") is None


def test_offers_verdicts_untouched(conn):
    """offers and verdicts tables must exist and be empty after migration."""
    offers_count = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    verdicts_count = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    assert offers_count == 0
    assert verdicts_count == 0
