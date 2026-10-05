"""Tests EXE-130 — titre du CV personnalisable par offre, et titre par défaut
pour les prochains CV générés (critères 1 à 13).

Aucun test n'appelle le modèle : `query` du SDK Claude Agent est remplacé par
un faux générateur async (même convention que test_cv_corrections_service.py).
Aucun test ne lit ni n'écrit sous data/ : DB, CV de référence, profil et
coordonnées sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.cv as api_cv
import api.db as api_db
import api.pieces as api_pieces
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from tests.pdf_inspect import extract_text

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
        for m in behavior(prompt, options):
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


def _insert_offer(db_path, offer_id, title="Titre H/F", verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json) VALUES (?, 'test', ?, 'fp', ?, 'Strasbourg', ?)",
            (offer_id, str(offer_id), title, json.dumps({"techs_required": []})),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-05')",
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


def _offers_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    finally:
        conn.close()


class TestCritere1ApiRendLeTitre:
    def test_enregistrer_un_titre_rend_le_cv_avec(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)

        result = api_cv.put_cv_titre(
            offer_id, api_cv.CvTitreIn(titre="Mon titre perso")
        )
        assert result["titre"] == "Mon titre perso"
        assert _cvs_row(db_path, offer_id)["titre"] == "Mon titre perso"


class TestCritere2TitreRemplaceDansLeHtml:
    def test_ancien_titre_absent_nouveau_present(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id, title="Ancien intitulé")
        _run_cv(monkeypatch, offer_id)
        before = _cvs_row(db_path, offer_id)["titre"]

        result = api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Nouveau titre"))
        assert "Nouveau titre" in result["html"]
        assert before not in result["html"]


class TestCritere3PdfPorteLeTitre:
    def test_pdf_contient_le_titre_enregistre(
        self, db_path, cv_fixture_paths, coordonnees_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id, title="Ancien intitulé")
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Titre du PDF"))

        response = api_cv.get_cv_pdf(offer_id)
        text = extract_text(response.body)
        assert "Titre du PDF" in text


class TestCritere4LocalisationEtCompetencesInchangees:
    def test_localisation_et_groupes_identiques(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        before = _cvs_row(db_path, offer_id)

        api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Nouveau titre"))

        after = _cvs_row(db_path, offer_id)
        assert after["localisation"] == before["localisation"]
        assert after["groupes_json"] == before["groupes_json"]
        assert after["notions_json"] == before["notions_json"]
        assert after["au_cv_json"] == before["au_cv_json"]


class TestCritere5TitreVideRefuse:
    @pytest.mark.parametrize("titre", ["", "   "])
    def test_titre_vide_ou_espaces_refuse(
        self, db_path, cv_fixture_paths, monkeypatch, titre
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        before = _cvs_row(db_path, offer_id)["titre"]

        with pytest.raises(HTTPException) as exc_info:
            api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre=titre))
        assert exc_info.value.status_code == 422
        assert _cvs_row(db_path, offer_id)["titre"] == before


class TestCritere6CvNonTermineRefuse:
    def test_refuse_avant_generation(self, db_path, cv_fixture_paths):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Un titre"))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail


class TestCritere7MarquePreteRedevientEnCours:
    def test_changer_le_titre_efface_la_marque(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "prete"

        api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Nouveau titre"))
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"


class TestCritere8CorrectionGardeLeTitre:
    def test_titre_reste_apres_une_correction(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Mon titre"))

        result = api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(action="retrait", competence="Python"),
        )
        assert result["titre"] == "Mon titre"
        assert _cvs_row(db_path, offer_id)["titre"] == "Mon titre"


class TestCritere9TitreDefautAuProchainCv:
    def test_le_prochain_cv_porte_le_titre_par_defaut(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 9
        with api_db.get_conn() as conn:
            cv_service.set_titre_defaut(conn, "Titre par défaut")
        _insert_offer(db_path, offer_id, title="Intitulé de l'offre")
        _run_cv(monkeypatch, offer_id)
        assert _cvs_row(db_path, offer_id)["titre"] == "Titre par défaut"


class TestCritere10DefautNeChangePasLesCvExistants:
    def test_cv_deja_genere_ne_change_pas(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 10
        _insert_offer(db_path, offer_id, title="Intitulé de l'offre H/F")
        _run_cv(monkeypatch, offer_id)
        titre_avant = _cvs_row(db_path, offer_id)["titre"]

        with api_db.get_conn() as conn:
            cv_service.set_titre_defaut(conn, "Titre par défaut")

        assert _cvs_row(db_path, offer_id)["titre"] == titre_avant


class TestCritere11LectureDuTitreDefaut:
    def test_rend_celui_enregistre_ou_rien(self, db_path):
        assert api_cv.get_cv_titre_defaut() == {"titre_defaut": None}
        api_cv.put_cv_titre_defaut(api_cv.TitreDefautIn(titre_defaut="Mon défaut"))
        assert api_cv.get_cv_titre_defaut() == {"titre_defaut": "Mon défaut"}


class TestCritere12EffacerLeTitreDefaut:
    def test_prochain_cv_reprend_l_intitule_de_l_offre(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 12
        api_cv.put_cv_titre_defaut(
            api_cv.TitreDefautIn(titre_defaut="Titre par défaut")
        )
        api_cv.delete_cv_titre_defaut()
        assert api_cv.get_cv_titre_defaut() == {"titre_defaut": None}

        _insert_offer(db_path, offer_id, title="Intitulé H/F")
        _run_cv(monkeypatch, offer_id)
        assert _cvs_row(db_path, offer_id)["titre"] == "Intitulé"


class TestCritere13TitreOffreIndependantDuDefaut:
    def test_titre_de_l_offre_change_les_autres_non(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_a, offer_b = 131, 132
        api_cv.put_cv_titre_defaut(
            api_cv.TitreDefautIn(titre_defaut="Titre par défaut")
        )
        _insert_offer(db_path, offer_a)
        _insert_offer(db_path, offer_b)
        _run_cv(monkeypatch, offer_a)
        _run_cv(monkeypatch, offer_b)
        assert _cvs_row(db_path, offer_a)["titre"] == "Titre par défaut"
        assert _cvs_row(db_path, offer_b)["titre"] == "Titre par défaut"

        api_cv.put_cv_titre(offer_a, api_cv.CvTitreIn(titre="Titre spécifique à A"))

        assert _cvs_row(db_path, offer_a)["titre"] == "Titre spécifique à A"
        assert _cvs_row(db_path, offer_b)["titre"] == "Titre par défaut"
        assert api_cv.get_cv_titre_defaut() == {"titre_defaut": "Titre par défaut"}


# ---------------------------------------------------------------------------
# « Ce qui ne doit pas arriver »
# ---------------------------------------------------------------------------


class TestAucunAppelModelePourChangerUnTitre:
    def test_set_titre_n_appelle_pas_le_sdk(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 14
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)

        def _boom(*, prompt, options):
            raise AssertionError("le modèle a été appelé pour changer un titre")

        monkeypatch.setattr(cv_service, "query", _boom)
        result = api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Un titre"))
        assert result["titre"] == "Un titre"


class TestTitreNonNettoye:
    def test_seuls_les_espaces_de_bord_sont_retires(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        result = api_cv.put_cv_titre(
            offer_id, api_cv.CvTitreIn(titre="  Lead Dev (H/F) | Acme  ")
        )
        assert result["titre"] == "Lead Dev (H/F) | Acme"


class TestTitreDeLOffreInchange:
    def test_offres_title_n_est_pas_modifie(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 16
        _insert_offer(db_path, offer_id, title="Intitulé original H/F")
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Titre modifié"))
        assert _offers_row(db_path, offer_id)["title"] == "Intitulé original H/F"


class TestParDefautLorsDeLEnregistrementDuTitre:
    def test_cocher_par_defaut_met_aussi_a_jour_le_defaut(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 17
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_titre(
            offer_id, api_cv.CvTitreIn(titre="Titre et défaut", par_defaut=True)
        )
        assert api_cv.get_cv_titre_defaut() == {"titre_defaut": "Titre et défaut"}
