"""Suivi MLflow d'un run de la pipeline (EXE-105), local et sans serveur distant.

Calque le pattern de rag-eval-scifact (.claude/rules/stack.md) : tracking SQLite
(`mlflow.db` à la racine du dépôt), pas le backend fichier `mlruns/` (en mode
maintenance depuis MLflow 3.x), aucune variable d'environnement à poser.

Le suivi est un à-côté du run (architecture.md, invariants de persistance) :
si MLflow ne peut pas écrire (stockage absent, verrouillé ou illisible), le
run de la pipeline va au bout sans lui — jamais l'inverse. Chaque méthode de
`RunTracker` avale ses propres exceptions et bascule `active` à faux ; les
appels suivants deviennent des no-op silencieux (hors l'impression qui
signale l'échec, une seule fois).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")

import mlflow
from mlflow.tracking import MlflowClient

from orchestrator.job_search.paths import REPO_ROOT

EXPERIMENT_NAME = "run-pipeline"
DEFAULT_TRACKING_URI = f"sqlite:///{REPO_ROOT / 'mlflow.db'}"

mlflow.set_tracking_uri(DEFAULT_TRACKING_URI)


def _artifact_root_for(tracking_uri: str) -> str:
    """Dossier `mlruns` à côté du `mlflow.db` actif, jamais le défaut MLflow
    relatif au répertoire courant — sinon un test (ou un lancement depuis un
    autre dossier) écrirait son `mlruns/` ailleurs que la base qu'il vise."""
    db_path = Path(tracking_uri.removeprefix("sqlite:///")).resolve()
    return str(db_path.parent / "mlruns")


class RunTracker:
    """Poignée sur un run MLflow d'une expérience donnée — `run-pipeline` par
    défaut ; `reference` (TCK-221, EXE-107) pour le rejeu du jeu de référence."""

    def __init__(self, experiment_name: str = EXPERIMENT_NAME) -> None:
        self.active = False
        self._started = False
        self._experiment_name = experiment_name

    def start(self, params: dict[str, Any]) -> None:
        try:
            client = MlflowClient()
            experiment = client.get_experiment_by_name(self._experiment_name)
            if experiment is None:
                experiment_id = client.create_experiment(
                    self._experiment_name,
                    artifact_location=_artifact_root_for(mlflow.get_tracking_uri()),
                )
            else:
                experiment_id = experiment.experiment_id
            mlflow.set_experiment(experiment_id=experiment_id)
            mlflow.start_run()
            self._started = True
            mlflow.log_params(params)
            self.active = True
        except Exception as exc:
            print(f"[run] suivi MLflow a échoué au démarrage : {exc}")
            self.active = False

    def log_param(self, key: str, value: Any) -> None:
        if not self.active:
            return
        try:
            mlflow.log_param(key, value)
        except Exception as exc:
            print(f"[run] suivi MLflow a échoué (paramètre) : {exc}")
            self.active = False

    def log_metrics(self, metrics: dict[str, float]) -> None:
        if not self.active:
            return
        try:
            mlflow.log_metrics(metrics)
        except Exception as exc:
            print(f"[run] suivi MLflow a échoué (métriques) : {exc}")
            self.active = False

    def log_artifact(self, path: Path) -> None:
        if not self.active:
            return
        try:
            mlflow.log_artifact(str(path))
        except Exception as exc:
            print(f"[run] suivi MLflow a échoué (artefact) : {exc}")
            self.active = False

    def end(self) -> None:
        if not self._started:
            return
        try:
            mlflow.end_run()
        except Exception as exc:
            print(f"[run] suivi MLflow a échoué (clôture) : {exc}")
        finally:
            self._started = False
            self.active = False
