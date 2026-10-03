"""Compteur en mémoire des durées et échecs d'extraction, pour le suivi MLflow
d'un run (EXE-105). Canal distinct de la trace JSONL (scoring/tracing.py) :
aucune écriture sur disque, aucun texte d'offre — seulement un nom de modèle,
une durée et un booléen d'échec.

Inactif par défaut (`collect()` jamais ouvert) : `record()` est alors un
no-op, sans coût pour les appelants existants (ajout à la main, rejeu)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class ExtractionStats:
    _durations: dict[str, list[float]] = field(default_factory=dict)
    _failures: dict[str, int] = field(default_factory=dict)

    def record(self, model: str, duration_seconds: float, failed: bool) -> None:
        self._durations.setdefault(model, []).append(duration_seconds)
        if failed:
            self._failures[model] = self._failures.get(model, 0) + 1

    def median_duration(self, model: str) -> float:
        values = sorted(self._durations.get(model, []))
        if not values:
            return 0.0
        n = len(values)
        mid = n // 2
        if n % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) / 2

    def failure_count(self, model: str) -> int:
        return self._failures.get(model, 0)


_active: ExtractionStats | None = None


@contextmanager
def collect():
    """Active la collecte pour la durée du bloc `with`, imbrication comprise :
    restaure le collecteur englobant (ou son absence) en sortie."""
    global _active
    previous = _active
    stats = ExtractionStats()
    _active = stats
    try:
        yield stats
    finally:
        _active = previous


def record(model: str, duration_seconds: float, failed: bool) -> None:
    if _active is not None:
        _active.record(model, duration_seconds, failed)
