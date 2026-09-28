"""Tests EXE-58 — service (génération) et route API (critères 1, 2, 22).

Aucun test n'appelle le modèle (contrainte du ticket) : `query` du SDK Claude Agent
est remplacé par un faux générateur async. Aucun test ne lit ni n'écrit sous data/ :
DB, CV de référence et profil sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException, Response

import api.cv as api_cv
import api.db as api_db
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db

REF_CV_HTML = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Ancien titre</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Strasbourg, France</b></div>
    </div>

    <h2>Compétences</h2>
  <div class="grp">
    <div class="grp-label">Langages</div>
    <div class="grp-list">Python · SQL</div>
  </div>

  <h2>Formation</h2>
    <div class="edu">Diplôme fictif</div>
  </div>
</body></html>
"""

PROFILE_YAML = """
profile_id: test
role_ceiling: ic
skills:
  python: {level: 6, desire: 8}
zones:
  strasbourg_area:
    insee: []
    dept: []
    keywords: ["strasbourg"]
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: [remote]
  contract_types: [cdi]
"""


def _fake_result(structured_output=None, is_error=False, result=None):
    return ResultMessage(
        subtype="success" if not is_error else "error_during_execution",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="fake-session",
        total_cost_usd=0.01,
        result=result,
        structured_output=structured_output,
    )


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire (ou lève une exception)."""

    async def _query(*, prompt, options):
        msgs = behavior(prompt, options)
        for m in msgs:
            yield m

    return _query


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
def cv_fixture_paths(tmp_path, monkeypatch):
    ref = tmp_path / "cv_reference.html"
    ref.write_text(REF_CV_HTML, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    return ref, profile


def _insert_offer(db_path, offer_id, techs=None, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json) VALUES (?, 'test', ?, 'fp', 'Titre H/F', 'Strasbourg', ?)",
            (offer_id, str(offer_id), json.dumps({"techs_required": techs or []})),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-28')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _cvs_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


class TestCritere1Idempotence:
    def test_premiere_generation_puis_redemande_sans_rappeler_le_modele(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id, techs=[])
        call_count = {"n": 0}

        def behavior(prompt, options):
            call_count["n"] += 1
            return [
                _fake_result(
                    structured_output={
                        "groupes": [{"label": "Langages", "items": ["Python", "SQL"]}]
                    }
                )
            ]

        monkeypatch.setattr(cv_service, "query", _make_query(behavior))

        asyncio.run(cv_service.run_cv(offer_id))
        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["html"] is not None
        assert call_count["n"] == 1

        # Route : un CV déjà généré est rendu tel quel, le modèle n'est jamais rappelé.
        def _never_called(_oid):
            raise AssertionError("le modèle a été rappelé pour un CV déjà généré")

        monkeypatch.setattr(api_cv, "run_cv", _never_called)
        response = Response()
        result = asyncio.run(api_cv.create_cv(offer_id, response))
        assert response.status_code == 200
        assert result["html"] == row["html"]
        assert call_count["n"] == 1  # toujours 1 : le vrai modèle n'a pas été rappelé


class TestCritere2RefusOffreNonRetenue:
    def test_refuse_et_ne_stocke_rien(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 2
        _insert_offer(db_path, offer_id, techs=[], verdict="candidaté")
        called = {"n": 0}

        def _spy(_oid):
            called["n"] += 1

        monkeypatch.setattr(api_cv, "run_cv", _spy)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_cv.create_cv(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert _cvs_row(db_path, offer_id) is None
        assert called["n"] == 0

    def test_refuse_quand_aucun_verdict(self, db_path, cv_fixture_paths):
        offer_id = 5
        _insert_offer(db_path, offer_id, techs=[], verdict=None)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_cv.create_cv(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert _cvs_row(db_path, offer_id) is None


class TestCritere22EchecOuTimeout:
    def test_echec_du_modele_rien_stocke_signale(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id, techs=[])

        def behavior(prompt, options):
            raise RuntimeError("SDK indisponible")

        monkeypatch.setattr(cv_service, "query", _make_query(behavior))
        asyncio.run(cv_service.run_cv(offer_id))

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["html"] is None
        assert row["error_message"]

    def test_timeout_rien_stocke_signale(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 4
        _insert_offer(db_path, offer_id, techs=[])
        monkeypatch.setattr(cv_service, "TIMEOUT_S", 0.01)

        async def _slow_query(*, prompt, options):
            await asyncio.sleep(1)
            yield _fake_result(structured_output={"groupes": []})

        monkeypatch.setattr(cv_service, "query", _slow_query)
        asyncio.run(cv_service.run_cv(offer_id))

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["html"] is None
        assert row["error_message"]
