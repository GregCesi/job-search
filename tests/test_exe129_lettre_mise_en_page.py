"""Tests EXE-129 — page HTML de la lettre d'une offre retenue, mise en page
comme son PDF (critères 1 à 4).

Mêmes conventions que test_exe102_pdf_pieces.py : DB et coordonnées sous
tmp_path, aucun appel modèle, aucune lecture/écriture sous data/.
"""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db


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


def _insert_offer(db_path, offer_id, verdict="retenu", title="Titre", company=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, 'Texte de l offre')",
            (offer_id, str(offer_id), title, company),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, verdict, _now()),
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


LETTRE_TEXTE = (
    "Je vous écris pour vous faire part de mon vif intérêt pour ce poste, qui "
    "correspond à mon projet professionnel et à mes compétences techniques."
)


# ---------------------------------------------------------------------------
# Critère 1 — même page que celle dont le PDF est tiré
# ---------------------------------------------------------------------------


class TestCritere1MemePageQueLePdf:
    def test_page_identique_a_celle_du_pdf(self, db_path, coordonnees_path):
        offer_id = 1
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)

        response = api_lettre.get_lettre_mise_en_page(offer_id)
        html = response.body.decode("utf-8")

        assert response.media_type == "text/html"
        assert "Grégoire Marchand" in html
        assert "gregoire@example.com" in html
        assert "+33 6 00 00 00 00" in html
        assert "Strasbourg" in html
        assert "Objet : candidature au poste de Ingénieur IA" in html
        assert LETTRE_TEXTE in html

    def test_identique_au_html_source_du_pdf(
        self, db_path, coordonnees_path, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)

        captured: dict[str, str] = {}
        original = api_lettre.html_to_pdf

        def _capture(html: str) -> bytes:
            captured["html"] = html
            return original(html)

        monkeypatch.setattr(api_lettre, "html_to_pdf", _capture)

        pdf_response = api_lettre.get_lettre_pdf(offer_id)
        assert pdf_response.body[:5] == b"%PDF-"
        apercu_response = api_lettre.get_lettre_mise_en_page(offer_id)

        assert apercu_response.body.decode("utf-8") == captured["html"]


# ---------------------------------------------------------------------------
# Critère 2 — lettre non générée
# ---------------------------------------------------------------------------


class TestCritere2LettreNonGeneree:
    def test_refuse_avec_la_phrase_du_pdf(self, db_path, coordonnees_path):
        offer_id = 3
        _insert_offer(db_path, offer_id, company="SFEIR")

        with pytest.raises(HTTPException) as exc_pdf:
            api_lettre.get_lettre_pdf(offer_id)
        with pytest.raises(HTTPException) as exc_apercu:
            api_lettre.get_lettre_mise_en_page(offer_id)

        assert exc_apercu.value.status_code == 409
        assert exc_apercu.value.detail == exc_pdf.value.detail


# ---------------------------------------------------------------------------
# Critère 3 — offre non retenue
# ---------------------------------------------------------------------------


class TestCritere3OffreNonRetenue:
    def test_refuse_avec_la_phrase_du_pdf(self, db_path, coordonnees_path):
        offer_id = 4
        _insert_offer(db_path, offer_id, verdict="rejete", company="SFEIR")

        with pytest.raises(HTTPException) as exc_pdf:
            api_lettre.get_lettre_pdf(offer_id)
        with pytest.raises(HTTPException) as exc_apercu:
            api_lettre.get_lettre_mise_en_page(offer_id)

        assert exc_apercu.value.status_code == 409
        assert exc_apercu.value.detail == exc_pdf.value.detail


# ---------------------------------------------------------------------------
# Critère 4 — coordonnées manquantes
# ---------------------------------------------------------------------------


class TestCritere4CoordonneesManquantes:
    def test_refuse_avec_la_phrase_du_pdf(self, db_path, tmp_path, monkeypatch):
        offer_id = 5
        missing = tmp_path / "absent" / "coordonnees.txt"
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", missing)
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)

        with pytest.raises(HTTPException) as exc_pdf:
            api_lettre.get_lettre_pdf(offer_id)
        with pytest.raises(HTTPException) as exc_apercu:
            api_lettre.get_lettre_mise_en_page(offer_id)

        assert exc_apercu.value.status_code == 409
        assert exc_apercu.value.detail == exc_pdf.value.detail
        assert str(missing) in exc_apercu.value.detail
