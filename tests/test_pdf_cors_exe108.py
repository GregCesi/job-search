"""Tests EXE-108 — l'API autorise l'origine de la page à lire le nom du fichier
PDF (critères 1-2) : la configuration CORS expose l'en-tête `Content-Disposition`,
où l'API écrit le nom calculé du CV et de la lettre.

Aucun test ne lit ni n'écrit sous data/ : DB_PATH est monkeypatché vers un fichier
tmp_path, avec le schéma complet mais aucune offre — les deux routes rendent 409
(offre non retenue) avant de produire un PDF, ce qui suffit : les en-têtes CORS
sont ajoutés par le middleware quelle que soit la réponse. Aucun appel modèle.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db

ORIGIN = "http://localhost:3000"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(db_path)
    storage_db.init_db(conn)
    conn.close()
    monkeypatch.setattr(api_db, "DB_PATH", db_path)

    import api.main as api_main

    return TestClient(api_main.app)


class TestCritere1CvPdfExposeContentDisposition:
    def test_origine_page_autorisee_a_lire_le_nom_du_fichier(self, client):
        res = client.get("/offers/1/cv/pdf", headers={"Origin": ORIGIN})

        exposed = res.headers.get("access-control-expose-headers", "")
        assert "content-disposition" in exposed.lower()


class TestCritere2LettrePdfExposeContentDisposition:
    def test_origine_page_autorisee_a_lire_le_nom_du_fichier(self, client):
        res = client.get("/offers/1/lettre/pdf", headers={"Origin": ORIGIN})

        exposed = res.headers.get("access-control-expose-headers", "")
        assert "content-disposition" in exposed.lower()
