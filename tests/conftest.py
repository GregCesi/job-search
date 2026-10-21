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

import api.db as api_db
import orchestrator.job_search.paths as paths
import orchestrator.job_search.storage.db as storage_db
import orchestrator.job_search.tracking.mlflow_tracking  # noqa: F401


@pytest.fixture(autouse=True)
def _isolate_mlflow_tracking(tmp_path):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path / 'mlflow.db'}")
    yield
    mlflow.set_tracking_uri(None)


@pytest.fixture(autouse=True)
def _isolate_db_path(tmp_path, monkeypatch):
    """EXE-200, critère 5 : `DB_PATH` pointe hors de `data/` du dépôt pour
    CHAQUE test, y compris celui qui ne prépare aucun chemin lui-même — un
    test qui veut son propre fichier le repose ensuite via son propre
    monkeypatch (dernier appel gagnant), sans rien changer ici (H1 : 113
    appels à `init_db` dans 15 fichiers écrasaient la vraie base sans cette
    fixture)."""
    isole = tmp_path / "isole.sqlite"
    monkeypatch.setattr(paths, "DB_PATH", isole)
    monkeypatch.setattr(storage_db, "DB_PATH", isole)
    monkeypatch.setattr(api_db, "DB_PATH", isole)
