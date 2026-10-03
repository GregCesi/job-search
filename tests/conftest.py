"""Isolation MLflow commune à toute la suite (EXE-105).

Aucun test — ancien ou nouveau — n'écrit dans le `mlflow.db` du dépôt : chaque
test pointe son propre tracking SQLite temporaire, restauré après coup. Les
tests EXE-98/99/100 appellent `run.main()`, qui démarre désormais un run MLflow ;
sans cette fixture, ils écriraient dans le fichier réel.

`orchestrator.job_search.tracking.mlflow_tracking` pointe MLflow vers le
`mlflow.db` du dépôt dès son import (effet de bord qui n'a lieu qu'une fois,
Python mettant les modules en cache) — importé ici, avant qu'aucune fixture
ne tourne, pour que la redirection ci-dessous soit toujours la dernière à
s'appliquer, sur le premier test comme sur tous les suivants.
"""

import mlflow
import pytest

import orchestrator.job_search.tracking.mlflow_tracking  # noqa: F401


@pytest.fixture(autouse=True)
def _isolate_mlflow_tracking(tmp_path):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    yield
    mlflow.set_tracking_uri(None)
