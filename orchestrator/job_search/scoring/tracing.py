"""
Instrumentation des appels LLM — traces JSONL pour extract_facts.

Canal séparé (architecture.md §Persistance) : n'écrit que dans data/traces/*.jsonl,
jamais dans offers/verdicts/human_reviews.
Effet de bord non bloquant : _write_trace ne propage aucune exception.
"""
import warnings
from pathlib import Path

from pydantic import BaseModel

from orchestrator.job_search.paths import TRACES_PATH

TRACE_PATH = TRACES_PATH


class LLMTrace(BaseModel):
    offer_id: str        # offer.source_id
    model: str           # $OLLAMA_MODEL effectif
    temperature: float   # 0.1 attendu
    prompt_system: str   # system prompt exact
    prompt_user: str     # user prompt exact (titre + description[:1500] + hints)
    raw_response: str    # réponse brute AVANT tout parsing
    parsed_facts: dict   # ExtractedFacts.model_dump()
    parse_failed: bool   # True si fallback activé
    timestamp: str       # ISO8601


def _write_trace(trace: LLMTrace, path: Path = TRACE_PATH) -> None:
    """Append one JSONL line. Never raises — write failure emits a warning only."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(trace.model_dump_json() + "\n")
    except Exception as exc:
        warnings.warn(f"[tracing] failed to write trace: {exc}")
