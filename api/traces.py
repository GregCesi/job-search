"""Endpoints traces viewer."""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .db import get_conn
from .schemas import CAUSE_VALUES, SEVERITE_VALUES, TraceNoteIn, TraceOut
from .traces_reader import build_traces_out, read_traces_raw

log = logging.getLogger(__name__)
router = APIRouter()

# ── Migration ─────────────────────────────────────────────────────────────────

def _ensure_trace_notes_table() -> None:
    """Crée trace_notes si absente + ajoute colonnes manquantes (idempotent)."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trace_notes (
                trace_key   TEXT PRIMARY KEY,
                offer_id    TEXT NOT NULL,
                note        TEXT NOT NULL DEFAULT '',
                updated_at  TEXT NOT NULL
            )
        """)
        # Migration idempotente : ajout cause + severite
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trace_notes)").fetchall()
        }
        if "cause" not in existing:
            conn.execute("ALTER TABLE trace_notes ADD COLUMN cause TEXT")
        if "severite" not in existing:
            conn.execute("ALTER TABLE trace_notes ADD COLUMN severite TEXT")
        conn.commit()


_ensure_trace_notes_table()

# ── Helpers DB ────────────────────────────────────────────────────────────────

def _upsert_note(
    trace_key: str,
    offer_id: str,
    note: str,
    cause: str | None = None,
    severite: str | None = None,
) -> None:
    updated_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO trace_notes (trace_key, offer_id, note, cause, severite, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trace_key) DO UPDATE SET
                note       = excluded.note,
                cause      = excluded.cause,
                severite   = excluded.severite,
                updated_at = excluded.updated_at
            """,
            (trace_key, offer_id, note, cause, severite, updated_at),
        )
        conn.commit()


def _fetch_annotations(trace_keys: list[str]) -> dict[str, dict]:
    """Retourne {trace_key: {note, cause, severite}} depuis trace_notes."""
    if not trace_keys:
        return {}
    placeholders = ",".join("?" * len(trace_keys))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT trace_key, note, cause, severite FROM trace_notes WHERE trace_key IN ({placeholders})",
            trace_keys,
        ).fetchall()
    return {
        row["trace_key"]: {
            "note": row["note"],
            "cause": row["cause"],
            "severite": row["severite"],
        }
        for row in rows
    }


@router.get("/traces", response_model=list[TraceOut])
def list_traces() -> list[TraceOut]:
    """Renvoie toutes les traces (sans dédup), triées par offer_id puis timestamp.

    Enrichit offer_title/offer_company depuis offers.source_id.
    Joint la note depuis trace_notes (None si absente ou table inexistante).
    0 appel LLM. Lecture seule.
    """
    traces = build_traces_out(read_traces_raw())

    annots = _fetch_annotations([t.trace_key for t in traces])
    if annots:
        traces = [
            t.model_copy(update=annots[t.trace_key]) if t.trace_key in annots else t
            for t in traces
        ]

    return traces


# ── PUT /traces/{trace_key}/note ──────────────────────────────────────────────

@router.put("/traces/{trace_key}/note", response_model=dict)
def upsert_trace_note(trace_key: str, body: TraceNoteIn) -> dict:
    """Persiste (ou efface) la note d'error analysis pour une trace.

    Écrit UNIQUEMENT dans trace_notes. Le .jsonl et offers/verdicts/human_reviews
    sont strictement intacts.
    Note vide ('') = effacement logique (ligne conservée, note vide).
    """
    if body.cause is not None and body.cause not in CAUSE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"cause invalide: {body.cause!r} (valeurs: {sorted(CAUSE_VALUES)})",
        )
    if body.severite is not None and body.severite not in SEVERITE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=f"severite invalide: {body.severite!r} (valeurs: {sorted(SEVERITE_VALUES)})",
        )

    # Récupère offer_id depuis les traces lues (nécessaire pour la FK)
    raws = read_traces_raw()
    raw = next((r for r in raws if f"{r['offer_id']}::{r['timestamp']}" == trace_key), None)
    if raw is None:
        raise HTTPException(status_code=404, detail="trace_key introuvable")

    _upsert_note(trace_key, raw["offer_id"], body.note, body.cause, body.severite)
    return {
        "trace_key": trace_key,
        "note": body.note,
        "cause": body.cause,
        "severite": body.severite,
    }


# ── GET /traces/export ───────────────────────────────────────────────────────

@router.get("/traces/export")
def export_traces_jsonl():
    """Export JSONL : toutes les traces enrichies (trace + annotations).

    JOIN extract_facts.jsonl × trace_notes par trace_key.
    Traces sans note → note/cause/severite à null, ligne incluse.
    """
    raws = read_traces_raw()
    annots = _fetch_annotations([f"{r['offer_id']}::{r['timestamp']}" for r in raws])

    def generate():
        for raw in raws:
            tk = f"{raw['offer_id']}::{raw['timestamp']}"
            ann = annots.get(tk, {})
            line = {
                "offer_id": raw.get("offer_id"),
                "model": raw.get("model"),
                "temperature": raw.get("temperature"),
                "prompt_system": raw.get("prompt_system", ""),
                "prompt_user": raw.get("prompt_user", ""),
                "raw_response": raw.get("raw_response", ""),
                "parsed_facts": raw.get("parsed_facts"),
                "parse_failed": raw.get("parse_failed", False),
                "timestamp": raw.get("timestamp"),
                "trace_key": tk,
                "note": ann.get("note"),
                "cause": ann.get("cause"),
                "severite": ann.get("severite"),
            }
            yield json.dumps(line, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="traces_annotated.jsonl"'
        },
    )
