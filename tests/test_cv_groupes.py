"""Tests EXE-61 — la réponse CV expose les groupes nommés et les notions à part
(critères 1 à 8).

Étend le stockage posé par EXE-58/EXE-59 sans y toucher : les tests de
test_cv_service.py et test_cv_corrections_service.py ne sont pas modifiés et
restent verts (H3, « ce qui ne doit pas arriver »). Aucun test n'appelle le
modèle : `query` du SDK Claude Agent est remplacé par un faux générateur async.
Aucun test ne lit ni n'écrit sous data/ : DB, CV de référence et profil sont
des fichiers tmp_path (même isolation que test_cv_service.py).
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
from orchestrator.job_search.storage.db import init_db

# H2 : noms de groupes du CV de référence réel. Notion « environnement cloud
# (AWS, Azure) » : un seul item malgré la virgule entre parenthèses (critère 2).
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
    <div class="grp-label">IA &amp; LLM</div>
    <div class="grp-list">LangChain · RAG</div>
  </div>
  <div class="grp">
    <div class="grp-label">Développement</div>
    <div class="grp-list">Python · TypeScript</div>
  </div>
  <div class="grp">
    <div class="grp-label">Outils &amp; méthodes</div>
    <div class="grp-list">Git · Docker</div>
  </div>
  <div class="grp-notions">Notions en : GraphQL, environnement cloud (AWS, Azure)</div>

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


def _correct(offer_id, action, competence, maitrisee=None, groupe=None):
    body = api_cv.SkillCorrectionIn(
        action=action, competence=competence, maitrisee=maitrisee, groupe=groupe
    )
    return api_cv.correct_cv_skill(offer_id, body)


def _get(offer_id):
    return api_cv.get_cv(offer_id)


class TestCritere1GroupesNommesDansLOrdre:
    def test_reponse_donne_3_groupes_nommes_avec_competences_dans_l_ordre(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 100
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _get(offer_id)
        assert result["groupes"] == [
            {"label": "IA & LLM", "items": ["LangChain", "RAG"]},
            {"label": "Développement", "items": ["Python", "TypeScript"]},
            {"label": "Outils & méthodes", "items": ["Git", "Docker"]},
        ]


class TestCritere2NotionsAPartDesGroupes:
    def test_notions_separees_avec_item_compose_intact(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 101
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _get(offer_id)
        assert result["notions"] == ["GraphQL", "environnement cloud (AWS, Azure)"]
        for grp in result["groupes"]:
            assert "environnement cloud (AWS, Azure)" not in grp["items"]
            assert "GraphQL" not in grp["items"]


class TestCritere3AjoutMaitriseEnDernierDansSonGroupe:
    def test_ajout_maitrise_apparait_en_dernier_dans_le_groupe_cible(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 102
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")
        outils = next(g for g in result["groupes"] if g["label"] == "Outils & méthodes")
        assert outils["items"] == ["Git", "Docker", "Kubernetes"]


class TestCritere4RelectureApresAjout:
    def test_nouvelle_lecture_montre_l_ajout_au_meme_endroit(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 103
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        _correct(offer_id, "ajout", "Kubernetes", True, "Outils & méthodes")

        result = _get(offer_id)
        outils = next(g for g in result["groupes"] if g["label"] == "Outils & méthodes")
        assert outils["items"] == ["Git", "Docker", "Kubernetes"]


class TestCritere5AjoutNonMaitriseEnDernierDansLesNotions:
    def test_ajout_non_maitrise_apparait_en_dernier_dans_les_notions_et_aucun_groupe(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 104
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _correct(offer_id, "ajout", "Terraform", False, None)
        assert result["notions"][-1] == "Terraform"
        for grp in result["groupes"]:
            assert "Terraform" not in grp["items"]


class TestCritere6RetraitDisparaitDeSonGroupe:
    def test_retrait_disparait_de_son_groupe_dans_la_reponse(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 105
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        result = _correct(offer_id, "retrait", "Git")
        outils = next(g for g in result["groupes"] if g["label"] == "Outils & méthodes")
        assert "Git" not in outils["items"]
        assert outils["items"] == ["Docker"]


class TestCritere7ChampsExistantsInchanges:
    def test_les_champs_anterieurs_gardent_leur_nom_et_leur_contenu(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 106
        _insert_offer(
            db_path, offer_id, techs=[{"name": "Kubernetes", "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)

        result = _get(offer_id)
        assert result["statut"] == "done"
        assert isinstance(result["html"], str) and "Kubernetes" not in result["au_cv"]
        assert result["titre"] == "Titre"
        assert result["localisation"] == "Strasbourg, France"
        assert result["au_cv"] == [
            "LangChain",
            "RAG",
            "Python",
            "TypeScript",
            "Git",
            "Docker",
            "GraphQL",
            "environnement cloud (AWS, Azure)",
        ]
        assert result["demande_sans_y_etre"] == ["Kubernetes"]
        assert result["ajouts_permis"] == []
        assert "seuil_utilise" in result
        assert "cost_usd" in result
        assert "error_message" in result
        assert "created_at" in result

        # Refus d'une compétence déjà présente (comportement EXE-59 inchangé, H3).
        with pytest.raises(HTTPException) as exc_info:
            _correct(offer_id, "ajout", "python", True, "Développement")
        assert exc_info.value.status_code == 409
