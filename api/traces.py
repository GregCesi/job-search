"""Endpoints traces viewer."""
import logging
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .db import get_conn
from .schemas import TraceNoteIn, TraceOut
from .traces_reader import build_traces_out, read_traces_raw

log = logging.getLogger(__name__)
router = APIRouter()

# ── Migration ─────────────────────────────────────────────────────────────────

def _ensure_trace_notes_table() -> None:
    """Crée trace_notes si absente (idempotent). Appelé au démarrage."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trace_notes (
                trace_key   TEXT PRIMARY KEY,
                offer_id    TEXT NOT NULL,
                note        TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL
            )
        """)
        conn.commit()


_ensure_trace_notes_table()

# ── Helpers DB ────────────────────────────────────────────────────────────────

def _upsert_note(trace_key: str, offer_id: str, note: str) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO trace_notes (trace_key, offer_id, note, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(trace_key) DO UPDATE SET
                note       = excluded.note,
                updated_at = excluded.updated_at
            """,
            (trace_key, offer_id, note, updated_at),
        )
        conn.commit()


def _fetch_notes(trace_keys: list[str]) -> dict[str, str]:
    """Retourne {trace_key: note} depuis trace_notes."""
    if not trace_keys:
        return {}
    placeholders = ",".join("?" * len(trace_keys))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT trace_key, note FROM trace_notes WHERE trace_key IN ({placeholders})",
            trace_keys,
        ).fetchall()
    return {row["trace_key"]: row["note"] for row in rows}


@router.get("/traces", response_model=list[TraceOut])
def list_traces() -> list[TraceOut]:
    """Renvoie toutes les traces (sans dédup), triées par offer_id puis timestamp.

    Enrichit offer_title/offer_company depuis offers.source_id.
    Joint la note depuis trace_notes (None si absente ou table inexistante).
    0 appel LLM. Lecture seule.
    """
    traces = build_traces_out(read_traces_raw())

    notes = _fetch_notes([t.trace_key for t in traces])
    if notes:
        traces = [t.model_copy(update={"note": notes.get(t.trace_key)}) for t in traces]

    return traces


# ── PUT /traces/{trace_key}/note ──────────────────────────────────────────────

@router.put("/traces/{trace_key}/note", response_model=dict)
def upsert_trace_note(trace_key: str, body: TraceNoteIn) -> dict:
    """Persiste (ou efface) la note d'error analysis pour une trace.

    Écrit UNIQUEMENT dans trace_notes. Le .jsonl et offers/verdicts/human_reviews
    sont strictement intacts.
    Note vide ('') = effacement logique (ligne conservée, note vide).
    """
    # Récupère offer_id depuis les traces lues (nécessaire pour la FK)
    raws = read_traces_raw()
    raw = next((r for r in raws if f"{r['offer_id']}::{r['timestamp']}" == trace_key), None)
    if raw is None:
        raise HTTPException(status_code=404, detail="trace_key introuvable")

    _upsert_note(trace_key, raw["offer_id"], body.note)
    return {"trace_key": trace_key, "note": body.note}
