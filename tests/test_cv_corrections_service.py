"""Tests EXE-59 — service et route API des corrections (critères 2, 7 à 13).

Étend le stockage posé par EXE-58 (H3) sans modifier son comportement : les
tests de la fiche « Depuis une offre retenue… » (test_cv_service.py,
test_cv_skills.py) ne sont pas touchés et restent verts. Aucun test n'appelle
le modèle : `query` du SDK Claude Agent est remplacé par un faux générateur
async. Aucun test ne lit ni n'écrit sous data/ : DB, CV de référence et profil
sont des fichiers tmp_path (même isolation que test_cv_service.py).
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.cv as api_cv
import api.db as api_db
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.cv.service import CvNotReadyError
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
  <div class="grp">
    <div class="grp-label">Outils &amp; méthodes</div>
    <div class="grp-list">Git · Docker</div>
  </div>
  <div class="grp-notions">Notions en : GraphQL</div>

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


def _fake_result(structured_output=None):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="fake-session",
        total_cost_usd=0.01,
        result=None,
        structured_output=structured_output,
    )


def _make_query(behavior):
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


def _run_cv(monkeypatch, offer_id, model_groups=None):
    def behavior(prompt, options):
        return [_fake_result(structured_output={"groupes": model_groups or []})]

    monkeypatch.setattr(cv_service, "query", _make_query(behavior))
    asyncio.run(cv_service.run_cv(offer_id))


def _cvs_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def _corrections_rows(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM cv_corrections WHERE offer_id = ? ORDER BY id ASC",
            (offer_id,),
        ).fetchall()
    finally:
        conn.close()


def _correct(offer_id, action, competence, maitrisee=None, groupe=None):
    body = api_cv.SkillCorrectionIn(
        action=action, competence=competence, maitrisee=maitrisee, groupe=groupe
    )
    return api_cv.correct_cv_skill(offer_id, body)


class TestCritere2ApiDisparaitDeDemandeSansYEtre:
    def test_ajout_maitrise_retire_de_la_liste(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 20
        _insert_offer(
            db_path, offer_id, techs=[{"name": "Kubernetes", "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)

        before = _cvs_row(db_path, offer_id)
        assert "Kubernetes" in json.loads(before["demande_sans_y_etre_json"])

        result = _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        assert "Kubernetes" not in result["demande_sans_y_etre"]
        assert "Kubernetes" not in json.loads(
            _cvs_row(db_path, offer_id)["demande_sans_y_etre_json"]
        )


class TestCritere7RefusApi:
    def test_ajout_d_une_competence_deja_presente_refuse_sans_rien_changer(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 21
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        before = _cvs_row(db_path, offer_id)["au_cv_json"]

        with pytest.raises(HTTPException) as exc_info:
            _correct(offer_id, "ajout", "python", True, "Langages")
        assert exc_info.value.status_code == 409
        assert _cvs_row(db_path, offer_id)["au_cv_json"] == before


class TestCritere8Historique:
    def test_trois_corrections_dans_l_ordre_avec_champs(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 22
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        _correct(offer_id, "ajout", "Terraform", False, None)
        _correct(offer_id, "retrait", "Kubernetes")

        rows = _corrections_rows(db_path, offer_id)
        assert [r["competence"] for r in rows] == [
            "Kubernetes",
            "Terraform",
            "Kubernetes",
        ]
        assert [r["action"] for r in rows] == ["ajout", "ajout", "retrait"]
        assert [bool(r["maitrisee"]) for r in rows] == [True, False, True]
        assert rows[0]["groupe"] == "Outils & méthodes"
        assert rows[1]["groupe"] is None
        assert rows[2]["groupe"] == "Outils & méthodes"
        assert all(r["created_at"] for r in rows)


class TestCritere9PersistanceApresRedemarrage:
    def test_trois_corrections_relues_apres_nouvelle_connexion(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 23
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        _correct(offer_id, "ajout", "Terraform", False, None)
        _correct(offer_id, "retrait", "Git")

        # Nouvelle connexion, comme le ferait une requête après redémarrage de l'API.
        row = _cvs_row(db_path, offer_id)
        au_cv = json.loads(row["au_cv_json"])
        assert "Kubernetes" in au_cv
        assert "Terraform" in au_cv
        assert "Git" not in au_cv


class TestCritere10Et11RenduHtml:
    def test_html_courant_inclut_les_corrections_et_reste_identique_ailleurs(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 24
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        html = result["html"]
        assert "Kubernetes" in html

        head_ref = REF_CV_HTML.split('<div class="role">', 1)[0]
        head_out = html.split('<div class="role">', 1)[0]
        assert head_ref == head_out

        tail_ref = REF_CV_HTML.split("<h2>Formation</h2>", 1)[1]
        tail_out = html.split("<h2>Formation</h2>", 1)[1]
        assert tail_ref == tail_out

        assert '<div class="row"><b>email@example.com</b></div>' in html


class TestCritere12RegenerationApresCorrections:
    def test_regeneration_ecrase_les_corrections_mais_garde_l_historique(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 25
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        assert "Kubernetes" in json.loads(_cvs_row(db_path, offer_id)["au_cv_json"])

        _run_cv(monkeypatch, offer_id)  # relance de la génération

        after = _cvs_row(db_path, offer_id)
        assert "Kubernetes" not in json.loads(after["au_cv_json"])
        assert len(_corrections_rows(db_path, offer_id)) == 1


class TestCritere13AucunAppelModele:
    def test_correction_n_appelle_jamais_le_sdk(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 26
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        def _boom(*, prompt, options):
            raise AssertionError("le modèle a été appelé pour une correction")

        monkeypatch.setattr(cv_service, "query", _boom)

        result = _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        assert "Kubernetes" in result["au_cv"]


class TestCorrectionSansCvGenere:
    def test_correction_avant_generation_refusee(self, db_path, cv_fixture_paths):
        offer_id = 27
        _insert_offer(db_path, offer_id, techs=[])
        with pytest.raises(HTTPException) as exc_info:
            _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        assert exc_info.value.status_code == 409

    def test_apply_correction_leve_cv_not_ready_directement(
        self, db_path, cv_fixture_paths
    ):
        offer_id = 28
        _insert_offer(db_path, offer_id, techs=[])
        with api_db.get_conn() as conn, pytest.raises(CvNotReadyError):
            cv_service.apply_correction(
                conn, offer_id, "ajout", "Kubernetes", True, "Langages"
            )
