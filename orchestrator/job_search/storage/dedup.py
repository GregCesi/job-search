import sqlite3

from orchestrator.job_search.sources.base import JobOffer


def filter_new(conn: sqlite3.Connection, offers: list[JobOffer]) -> list[JobOffer]:
    """Return offers not already in the DB (by source+source_id OR fingerprint)."""
    if not offers:
        return []

    rows = conn.execute("SELECT source, source_id, fingerprint FROM offers").fetchall()
    seen_ids = {(r["source"], r["source_id"]) for r in rows}
    seen_fps = {r["fingerprint"] for r in rows}

    new: list[JobOffer] = []
    for offer in offers:
        if (offer.source, offer.source_id) in seen_ids:
            continue
        if offer.fingerprint in seen_fps:
            continue
        new.append(offer)
        # Guard against duplicates within the same batch
        seen_ids.add((offer.source, offer.source_id))
        seen_fps.add(offer.fingerprint)

    return new
