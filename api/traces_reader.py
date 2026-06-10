"""Lecture défensive du fichier de traces LLM extract_facts.

Le fichier est lu, jamais muté.
Chemin résolu depuis __file__ (pattern api/db.py).
"""
import json
import logging
from pathlib import Path

from .db import get_conn
from .schemas import TraceParsedFacts, TraceOut

log = logging.getLogger(__name__)

_TRACES_PATH = (
    Path(__file__).parent.parent / "data" / "traces" / "extract_facts.jsonl"
)


def read_traces_raw() -> list[dict]:
    """Lit le .jsonl de traces ligne par ligne en mode défensif.

    - Fichier absent  → liste vide, aucune erreur.
    - Ligne corrompue → log.warning + saut (jamais de crash du run).
    - Renvoie les dicts bruts, sans transformation.
    """
    if not _TRACES_PATH.exists():
        log.warning(
            "traces file not found: %s — returning empty list", _TRACES_PATH
        )
        return []

    traces: list[dict] = []
    with _TRACES_PATH.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning(
                    "traces line %d: JSON parse error — skipping (%s)", lineno, exc
                )
                continue
            if not isinstance(obj, dict):
                log.warning(
                    "traces line %d: expected dict, got %s — skipping",
                    lineno,
                    type(obj).__name__,
                )
                continue
            traces.append(obj)

    return traces


def _fetch_offer_info(offer_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """Retourne {source_id: (title, company)} pour les ids demandés.

    Offre introuvable → absent du dict (pas d'erreur).
    """
    if not offer_ids:
        return {}
    placeholders = ",".join("?" * len(offer_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT source_id, title, company FROM offers WHERE source_id IN ({placeholders})",
            offer_ids,
        ).fetchall()
    return {row["source_id"]: (row["title"], row["company"]) for row in rows}


def _build_one(
    raw: dict,
    offer_title: str | None = None,
    offer_company: str | None = None,
    note: str | None = None,
) -> TraceOut:
    pf_raw = raw.get("parsed_facts") or {}
    parsed_facts = TraceParsedFacts(
        seniority_required=pf_raw.get("seniority_required"),
        techs_required=pf_raw.get("techs_required") or [],
        domain=pf_raw.get("domain"),
        role_level=pf_raw.get("role_level"),
        parse_failed=bool(pf_raw.get("parse_failed", False)),
    )
    return TraceOut(
        trace_key=f"{raw['offer_id']}::{raw['timestamp']}",
        offer_id=raw["offer_id"],
        offer_title=offer_title,
        offer_company=offer_company,
        model=raw["model"],
        temperature=float(raw["temperature"]),
        timestamp=raw["timestamp"],
        prompt_system=raw.get("prompt_system", ""),
        prompt_user=raw.get("prompt_user", ""),
        raw_response=raw.get("raw_response", ""),
        parsed_facts=parsed_facts,
        parse_failed=bool(raw.get("parse_failed", False)),
        note=note,
    )


def build_traces_out(raws: list[dict]) -> list[TraceOut]:
    """Construit la liste des TraceOut enrichis (batch SQL, single query).

    - Enrichit offer_title / offer_company depuis offers.source_id (L3).
    - note laissé à None (joint par la route en L4 depuis trace_notes).
    - Offre introuvable → champs None, pas d'erreur.
    - Triées par offer_id puis timestamp (variance d'une même offre groupée).
    """
    offer_ids = list({r["offer_id"] for r in raws})
    offer_info = _fetch_offer_info(offer_ids)

    traces = [
        _build_one(
            raw,
            offer_title=offer_info.get(raw["offer_id"], (None, None))[0],
            offer_company=offer_info.get(raw["offer_id"], (None, None))[1],
        )
        for raw in raws
    ]
    traces.sort(key=lambda t: (t.offer_id, t.timestamp))
    return traces
