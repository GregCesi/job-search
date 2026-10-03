"""Tests EXE-108 — l'API autorise l'origine du front à lire le nom de fichier
du PDF (CV, lettre) dans la réponse cross-origin.

Exercés via `TestClient(app)` pour traverser réellement le middleware CORS —
contrairement à `test_exe102_pdf_pieces.py`, qui appelle les fonctions de
route nues et ne voit donc jamais `CORSMiddleware`. Aucun test ne lit ni
n'écrit sous data/ : DB et coordonnées sont sous `tmp_path`. Aucun appel
modèle : CV et lettre sont simulés par insertion SQL directe (statut='done'),
même convention que `test_exe102_pdf_pieces.py`.
"""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
from orchestrator.job_search.pdf import coordonnees as coordonnees_module
from orchestrator.job_search.storage import db as storage_db
from orchestrator.job_search.storage.db import init_db

ORIGIN = "http://localhost:3000"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def coordonnees_path(tmp_path, monkeypatch):
    path = tmp_path / "coordonnees.txt"
    path.write_text(
        "nom: Grégoire Marchand\n"
        "mail: gregoire@example.com\n"
        "telephone: +33 6 00 00 00 00\n"
        "ville: Strasbourg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", path)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(db_path, offer_id, company="SFEIR"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', ?, "
            "'Texte de l offre')",
            (offer_id, str(offer_id), company),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', ?)",
            (offer_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_cv_done(db_path, offer_id, html):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, titre, created_at) "
            "VALUES (?, 'done', ?, 'Titre', ?)",
            (offer_id, html, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre_done(db_path, offer_id, texte):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, texte, created_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, texte, _now()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Critère 1 — PDF du CV : l'origine du front lit le nom du fichier
# ---------------------------------------------------------------------------


class TestCritere1CorsExposeHeaderCv:
    def test_origine_front_autorisee_a_lire_le_nom_du_fichier_cv(
        self, db_path, coordonnees_path
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_cv_done(db_path, offer_id, html="<html><body>CV</body></html>")
        # Import local : api.main connecte trace_notes à l'import (api/traces.py) ;
        # il ne doit s'exécuter qu'une fois DB_PATH monkeypatché vers tmp_path
        # (même convention que test_cv_exe63.py).
        from api.main import app

        with TestClient(app) as client:
            response = client.get(
                f"/offers/{offer_id}/cv/pdf", headers={"Origin": ORIGIN}
            )
        assert response.status_code == 200
        expose = response.headers.get("access-control-expose-headers", "")
        assert "content-disposition" in expose.lower()


# ---------------------------------------------------------------------------
# Critère 2 — PDF de la lettre : l'origine du front lit le nom du fichier
# ---------------------------------------------------------------------------


class TestCritere2CorsExposeHeaderLettre:
    def test_origine_front_autorisee_a_lire_le_nom_du_fichier_lettre(
        self, db_path, coordonnees_path
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_lettre_done(db_path, offer_id, "Texte de la lettre.")
        from api.main import app

        with TestClient(app) as client:
            response = client.get(
                f"/offers/{offer_id}/lettre/pdf", headers={"Origin": ORIGIN}
            )
        assert response.status_code == 200
        expose = response.headers.get("access-control-expose-headers", "")
        assert "content-disposition" in expose.lower()
