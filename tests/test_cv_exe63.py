"""Tests EXE-63 — titre nettoyé du nom d'employeur (critères 1-2), CV généré sans
appel modèle quand il n'y a rien à ajouter (critères 3-6), tables créées par l'API
au démarrage (critères 7-8).

Aucun test n'appelle le modèle : `query` du SDK Claude Agent est soit remplacé par
un faux générateur async, soit monkeypatché pour lever si on l'appelle par erreur.
Aucun test ne lit ni n'écrit sous data/ : DB, CV de référence et profil sont des
fichiers tmp_path.
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
from orchestrator.job_search.cv.skills import clean_title, parse_reference_block
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

# Aucune des 9 technos H1 dans les skills du profil : canonical_levels reste vide,
# donc `compute_permitted_additions` ne retient jamais rien (critères 3-5).
PROFILE_SANS_LES_TECHS_H1 = """
profile_id: test
role_ceiling: ic
skills: {}
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

# kubernetes au niveau 6, absent du CV de référence : un ajout est permis (critère 6).
PROFILE_AVEC_KUBERNETES = """
profile_id: test
role_ceiling: ic
skills:
  kubernetes: {level: 6, desire: 5}
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

TECHS_H1 = [
    {"name": n, "importance": "required"}
    for n in [
        "python",
        "rag",
        "langchain",
        "langgraph",
        "azure",
        "git",
        "mlops",
        "mlflow",
        "cicd",
    ]
]


def _fake_result(structured_output=None):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="fake-session",
        total_cost_usd=1.0,
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
    profile.write_text(PROFILE_SANS_LES_TECHS_H1, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    return ref, profile


def _insert_offer(db_path, offer_id, title, techs, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json) VALUES (?, 'test', ?, 'fp', ?, 'Strasbourg', ?)",
            (offer_id, str(offer_id), title, json.dumps({"techs_required": techs})),
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


class TestCritere1TitreAvantPipe:
    def test_titre_avec_nom_employeur_apres_pipe(self):
        assert (
            clean_title("Generative AI Engineer | Proximus Ada")
            == "Generative AI Engineer"
        )


class TestCritere2TitreSansPipeInchange:
    def test_titre_sans_pipe_inchange(self):
        assert clean_title("AI Engineer") == "AI Engineer"


class TestCritere3AucunAppelModeleQuandRienAAjouter:
    def test_generation_sans_appel_modele(self, db_path, cv_fixture_paths):
        offer_id = 10
        _insert_offer(
            db_path, offer_id, "Generative AI Engineer | Proximus Ada", TECHS_H1
        )

        def _forbidden_query(*, prompt, options):
            raise AssertionError(
                "le modèle a été appelé alors qu'il n'y avait rien à ajouter"
            )

        # Volontairement pas de monkeypatch via _make_query : un vrai appel doit
        # échouer bruyamment, pas être toléré par un faux générateur async.
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(cv_service, "query", _forbidden_query)
        try:
            asyncio.run(cv_service.run_cv(offer_id))
        finally:
            monkeypatch.undo()

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["titre"] == "Generative AI Engineer"


class TestCritere4CoutEnregistreZero:
    def test_cout_zero_quand_rien_a_ajouter(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _insert_offer(db_path, offer_id, "AI Engineer", TECHS_H1)

        def _forbidden_query(*, prompt, options):
            raise AssertionError("le modèle ne doit pas être appelé")

        monkeypatch.setattr(cv_service, "query", _forbidden_query)
        asyncio.run(cv_service.run_cv(offer_id))

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["cost_usd"] == 0


class TestCritere5BlocCompetencesIdentiqueAuCvDeReference:
    def test_bloc_competences_identique_a_la_reference(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id, "AI Engineer", TECHS_H1)

        def _forbidden_query(*, prompt, options):
            raise AssertionError("le modèle ne doit pas être appelé")

        monkeypatch.setattr(cv_service, "query", _forbidden_query)
        asyncio.run(cv_service.run_cv(offer_id))

        row = _cvs_row(db_path, offer_id)
        ref = parse_reference_block(REF_CV_HTML)
        groupes = json.loads(row["groupes_json"])
        assert groupes == [{"label": g.label, "items": g.items} for g in ref.groupes]


class TestCritere6ModeleAppeleQuandAjoutPermis:
    def test_modele_appele_si_au_moins_un_ajout(self, db_path, tmp_path, monkeypatch):
        ref = tmp_path / "cv_reference.html"
        ref.write_text(REF_CV_HTML, encoding="utf-8")
        profile = tmp_path / "profile.yaml"
        profile.write_text(PROFILE_AVEC_KUBERNETES, encoding="utf-8")
        monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
        monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)

        offer_id = 13
        _insert_offer(
            db_path,
            offer_id,
            "AI Engineer",
            [{"name": "kubernetes", "importance": "required"}],
        )

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
        assert call_count["n"] == 1
        assert row["cost_usd"] == 1.0


class TestCritere7ApiCreeLesTablesAuDemarrage:
    def test_demande_de_cv_sans_erreur_serveur_apres_demarrage(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "job_search.sqlite"
        monkeypatch.setattr(api_db, "DB_PATH", path)

        # Base « ancienne » : seules `offers` et `verdicts` existent, comme avant
        # qu'un run orchestrator n'ait jamais tourné (H3 du ticket).
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE offers (id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, "
            "fingerprint TEXT, title TEXT, location TEXT, extracted_facts_json TEXT)"
        )
        conn.execute(
            "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, offer_id INTEGER, "
            "status TEXT, created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location) "
            "VALUES (1, 'test', '1', 'fp', 'Titre', 'Strasbourg')"
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (1, 'retenu', '2026-09-28')"
        )
        conn.commit()
        conn.close()

        # Import local : le module api.main connecte trace_notes à l'import (api/traces.py) ;
        # il ne doit s'exécuter qu'une fois DB_PATH monkeypatché vers le fichier tmp_path.
        import api.main as api_main

        api_main._migrate_db()  # simule le démarrage de l'API

        with pytest.raises(HTTPException) as exc_info:
            api_cv.get_cv(1)
        assert exc_info.value.status_code == 404  # pas une sqlite3.OperationalError


class TestCritere8ApiConserveLesCvExistantsAuDemarrage:
    def test_cv_existant_toujours_present_apres_demarrage(self, db_path):
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location) "
            "VALUES (1, 'test', '1', 'fp', 'Titre', 'Strasbourg')"
        )
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, titre, created_at) "
            "VALUES (1, 'done', '<html>déjà généré</html>', 'Titre', '2026-09-28')"
        )
        conn.commit()
        conn.close()

        import api.main as api_main

        api_main._migrate_db()  # simule un redémarrage de l'API

        row = _cvs_row(db_path, 1)
        assert row["statut"] == "done"
        assert row["html"] == "<html>déjà généré</html>"
