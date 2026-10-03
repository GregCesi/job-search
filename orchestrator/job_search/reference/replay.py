"""Rejoue le jeu de référence sur un modèle nommé (TCK-221, EXE-107,
architecture.md exception « rejeu du jeu de référence »).

Appelle le modèle hors ingestion, sur des offres déjà extraites, pour mesurer
une extraction contre un attendu écrit à la main. N'écrit rien dans les
offres en base (pas de connexion passée ici) ni dans le fichier de traces du
run (`TRACE_PATH` est détourné le temps de l'appel) : les résultats vivent
dans le rapport et dans MLflow, sous l'expérience « reference ».
"""

from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import orchestrator.job_search.scoring.extractor as extractor_module
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.paths import REPO_ROOT
from orchestrator.job_search.reference.dataset import ReferenceEntry, jeu_fingerprint
from orchestrator.job_search.reference.metrics import (
    AggregateMetrics,
    OfferComparison,
    aggregate,
    compare_offer,
)
from orchestrator.job_search.reference.report import render_report
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.scoring.extractor import (
    NoResponseFromModel,
    ensure_models_available,
    extract_facts,
    extraction_version,
    unload_model,
)
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.tracking.mlflow_tracking import RunTracker

REPORTS_DIR = REPO_ROOT / "data" / "reference" / "reports"
EXPERIMENT_NAME = "reference"
_DEFAULT_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


@contextmanager
def _suppressed_trace():
    """Un rejeu n'écrit jamais dans `data/traces/extract_facts.jsonl` (le
    fichier de traces du run) : `TRACE_PATH` est détourné vers un fichier
    éphémère le temps de l'appel, puis restauré (« ce qui ne doit pas
    arriver » du ticket)."""
    original = extractor_module.TRACE_PATH
    with tempfile.TemporaryDirectory() as tmp_dir:
        extractor_module.TRACE_PATH = Path(tmp_dir) / "rejeu.jsonl"
        try:
            yield
        finally:
            extractor_module.TRACE_PATH = original


def _synthetic_offer(offer_id: str, entry: ReferenceEntry) -> JobOffer:
    """Reconstruit juste assez d'offre pour appeler `extract_facts` — seuls
    le titre et le texte du jeu alimentent le prompt (H du ticket : le jeu ne
    porte que l'intitulé et le texte, pas les champs source)."""
    return JobOffer(
        source="reference",
        source_id=offer_id,
        fingerprint="",
        title=entry.title,
        description=entry.text,
        company=None,
        location=None,
        remote=False,
        contract_type=None,
        url=None,
        fetched_at=datetime.now(timezone.utc),
    )


def _extract_one(offer: JobOffer, model: str, host: str) -> object | None:
    with _suppressed_trace():
        try:
            return extract_facts(offer, model=model, host=host)
        except NoResponseFromModel:
            return None


@dataclass
class ReplayResult:
    model: str
    extraction_version: str
    jeu_fingerprint: str
    n_skipped_non_relu: int
    comparisons: list[OfferComparison] = field(default_factory=list)
    aggregates: AggregateMetrics | None = None
    report_text: str = ""
    report_path: Path | None = None


def _write_report(reports_dir: Path, model: str, text: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_model = model.replace(":", "-").replace("/", "-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = reports_dir / f"rejeu_{safe_model}_{stamp}.md"
    path.write_text(text, encoding="utf-8")
    return path


def replay_jeu(
    entries: dict[str, ReferenceEntry],
    model: str,
    *,
    profile: Profile,
    alias_table: AliasTable,
    host: str = _DEFAULT_HOST,
    reports_dir: Path = REPORTS_DIR,
    tracker_factory=RunTracker,
) -> ReplayResult:
    """Rejoue les entrées marquées « relu » de `entries` sur `model` (critère
    3). Refuse de démarrer si Ollama est injoignable ou si `model` n'y est
    pas installé (critère 15, `OllamaUnavailable` propagée, rien n'est
    tenté). Si `model` est le modèle de précision configuré (`OLLAMA_MODEL`),
    le rejeu suit les lots et les pauses de la pipeline (critère 14,
    `SECOND_PASS_*`, EXE-100) ; sinon il tourne séquentiellement, comme le
    tri en production."""
    ensure_models_available(host, [model])

    relues = {k: e for k, e in entries.items() if e.relu}
    n_skipped = len(entries) - len(relues)

    precision_model_env = os.getenv("OLLAMA_MODEL", "gemma4:12b")
    is_precision = model == precision_model_env

    comparisons: list[OfferComparison] = []

    def _run_one(offer_id: str, entry: ReferenceEntry) -> None:
        offer = _synthetic_offer(offer_id, entry)
        started = time.perf_counter()
        facts = _extract_one(offer, model, host)
        duration = time.perf_counter() - started
        comparisons.append(
            compare_offer(
                offer_id, facts, entry.attendu, profile, alias_table, duration
            )
        )

    items = list(relues.items())
    if is_precision:
        batch_size = int(os.getenv("SECOND_PASS_BATCH_SIZE", "10"))
        pause_seconds = float(os.getenv("SECOND_PASS_PAUSE_SECONDS", "300"))
        max_batches = int(os.getenv("SECOND_PASS_MAX_BATCHES", "5"))
        idx = 0
        batches_done = 0
        while idx < len(items):
            batch = items[idx : idx + batch_size]
            for offer_id, entry in batch:
                _run_one(offer_id, entry)
            idx += len(batch)
            batches_done += 1
            if batches_done >= max_batches or idx >= len(items):
                break
            unload_model(host, model)
            time.sleep(pause_seconds)
    else:
        for offer_id, entry in items:
            _run_one(offer_id, entry)

    aggregates = aggregate(comparisons)
    fp = jeu_fingerprint(entries)
    version = extraction_version(model)
    report_text = render_report(model, fp, aggregates, comparisons)
    report_path = _write_report(reports_dir, model, report_text)

    tracker = tracker_factory(experiment_name=EXPERIMENT_NAME)
    tracker.start(
        {
            "model": model,
            "extraction_version": version,
            "n_offres_rejouees": len(comparisons),
            "jeu_empreinte": fp,
        }
    )
    tracker.log_metrics(aggregates.as_dict())
    tracker.log_artifact(report_path)
    tracker.end()

    return ReplayResult(
        model=model,
        extraction_version=version,
        jeu_fingerprint=fp,
        n_skipped_non_relu=n_skipped,
        comparisons=comparisons,
        aggregates=aggregates,
        report_text=report_text,
        report_path=report_path,
    )
