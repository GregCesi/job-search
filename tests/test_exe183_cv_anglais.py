"""Tests EXE-183 — CV anglais : production (auto ou à la demande), accord des
deux versions, et PDF (critères 1, 2, 3, 9, 10, 11, 19, 20, 21, 22, 23).

Aucun test n'appelle le modèle (contrainte du ticket) : `query` du SDK Claude
Agent est remplacé par un faux générateur async. Aucun test ne lit ni n'écrit
sous data/ : DB, CV de référence FR/EN et profil sont des fichiers tmp_path
(H1, H6 du ticket).
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
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db

REF_CV_HTML_FR = """<!doctype html>
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
    <div class="grp-list">Systèmes agentiques · Rust</div>
  </div>
  <div class="grp">
    <div class="grp-label">Outils &amp; méthodes</div>
    <div class="grp-list">Revues de code</div>
  </div>
  <div class="grp-notions">Notions en : environnement cloud (AWS, Azure, Google Cloud), GraphQL</div>

  <h2>Formation</h2>
    <div class="edu">Diplôme fictif</div>
  </div>
</body></html>
"""

REF_CV_HTML_EN = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Old title</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Brussels, Belgium</b></div>
    </div>

    <h2>Skills</h2>
  <div class="grp">
    <div class="grp-label">AI &amp; LLM</div>
    <div class="grp-list">RAG</div>
  </div>

  <h2>Education</h2>
    <div class="edu">Fake degree</div>
  </div>
</body></html>
"""

PROFILE_YAML = """
profile_id: test
role_ceiling: ic
skills:
  python: {level: 6, desire: 8}
  docker: {level: 7, desire: 8}
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
    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _run_cv(monkeypatch, offer_id, model_groups=None):
    def behavior(prompt, options):
        return [_fake_result(structured_output={"groupes": model_groups or []})]

    monkeypatch.setattr(cv_service, "query", _make_query(behavior))
    asyncio.run(cv_service.run_cv(offer_id))


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
    ref.write_text(REF_CV_HTML_FR, encoding="utf-8")
    ref_en = tmp_path / "cv_reference_en.html"
    ref_en.write_text(REF_CV_HTML_EN, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_EN_PATH", ref_en)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    return ref, ref_en, profile


def _insert_offer(
    db_path, offer_id, techs=None, verdict="retenu", ad_language=None, title="Titre H/F"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json, ad_language) VALUES (?, 'test', ?, 'fp', ?, "
            "'Strasbourg', ?, ?)",
            (
                offer_id,
                str(offer_id),
                title,
                json.dumps({"techs_required": techs or []}),
                ad_language,
            ),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-16')",
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


class TestCritere1AnnonceAnglaiseProduitDeuxVersions:
    def test_les_deux_versions_arrivent_sans_autre_geste(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["html"] is not None
        assert row["en_html"] is not None
        assert "Agentic systems" in row["en_html"]
        assert "Titre" in row["en_html"]  # critère 10 : même titre que le FR


class TestCritere2AutresLanguesSeulementFrancais:
    @pytest.mark.parametrize("ad_language", ["fr", "nl", "other", None])
    def test_aucune_version_anglaise(
        self, db_path, cv_fixture_paths, monkeypatch, ad_language
    ):
        offer_id = {"fr": 2, "nl": 3, "other": 4, None: 5}[ad_language]
        _insert_offer(db_path, offer_id, techs=[], ad_language=ad_language)
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["html"] is not None
        assert row["en_html"] is None


class TestCritere3BoutonGenereLaVersionAnglaise:
    def test_cv_francais_termine_sans_anglais_le_bouton_le_produit(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)
        assert _cvs_row(db_path, offer_id)["en_html"] is None

        result = api_cv.create_cv_en(offer_id)
        assert result["en_html"] is not None
        assert "Agentic systems" in result["en_html"]
        assert _cvs_row(db_path, offer_id)["en_html"] is not None

    def test_refuse_si_le_cv_francais_n_est_pas_termine(
        self, db_path, cv_fixture_paths
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id, techs=[])
        with pytest.raises(HTTPException) as exc_info:
            api_cv.create_cv_en(offer_id)
        assert exc_info.value.status_code == 409


class TestCritere9Localisation:
    def test_bruxelles_traduit_en_brussels(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 8
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json, ad_language) VALUES (?, 'test', ?, 'fp', 'Titre', "
            "'bruxelles', ?, 'en')",
            (offer_id, str(offer_id), json.dumps({"techs_required": []})),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', '2026-10-16')",
            (offer_id,),
        )
        conn.commit()
        conn.close()

        profile_belgique = """
profile_id: test
role_ceiling: ic
skills:
  python: {level: 6, desire: 8}
zones:
  strasbourg_area:
    insee: []
    dept: []
    keywords: ["strasbourg"]
  belgique_area:
    insee: []
    dept: []
    keywords: ["bruxelles"]
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: [remote]
  contract_types: [cdi]
"""
        (cv_fixture_paths[2]).write_text(profile_belgique, encoding="utf-8")

        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert "Bruxelles, Belgique" in row["localisation"]
        assert "Brussels, Belgium" in row["en_html"]

    def test_strasbourg_inchange(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 9
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert "Strasbourg, France" in row["localisation"]
        assert "Strasbourg, France" in row["en_html"]


class TestCritere10TitrePartage:
    def test_meme_titre_sur_les_deux_versions(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _insert_offer(
            db_path, offer_id, techs=[], ad_language="en", title="Mon Intitulé"
        )
        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert row["titre"] in row["html"]
        assert row["titre"] in row["en_html"]


class TestCritere11PdfAnglaisNommage:
    def test_pdf_anglais_porte_en_avant_extension(
        self, db_path, cv_fixture_paths, monkeypatch, tmp_path
    ):
        import orchestrator.job_search.pdf.coordonnees as coordonnees_module

        coord_path = tmp_path / "coordonnees.txt"
        coord_path.write_text(
            "nom: Grégoire Marchand\n"
            "mail: gregoire@example.com\n"
            "telephone: +33 6 00 00 00 00\n"
            "ville: Strasbourg\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", coord_path)

        offer_id = 11
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        resp_fr = api_cv.get_cv_pdf(offer_id, lang="fr")
        resp_en = api_cv.get_cv_pdf(offer_id, lang="en")
        fname_fr = (
            resp_fr.headers["content-disposition"].split('filename="')[1].rstrip('"')
        )
        fname_en = (
            resp_en.headers["content-disposition"].split('filename="')[1].rstrip('"')
        )
        assert fname_en == fname_fr[:-4] + "_EN.pdf"

    def test_refuse_pdf_anglais_si_absent(
        self, db_path, cv_fixture_paths, monkeypatch, tmp_path
    ):
        import orchestrator.job_search.pdf.coordonnees as coordonnees_module

        coord_path = tmp_path / "coordonnees.txt"
        coord_path.write_text(
            "nom: Grégoire Marchand\n"
            "mail: gregoire@example.com\n"
            "telephone: +33 6 00 00 00 00\n"
            "ville: Strasbourg\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", coord_path)

        offer_id = 12
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_cv.get_cv_pdf(offer_id, lang="en")
        assert exc_info.value.status_code == 409


class TestCritere19CorrectionSurLesDeuxVersions:
    def test_ajout_et_retrait_affectent_les_deux_versions(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 13
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        result = api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(
                action="ajout",
                competence="Kubernetes",
                maitrisee=True,
                groupe="IA & LLM",
            ),
        )
        assert "Kubernetes" in result["html"]
        assert "Kubernetes" in result["en_html"]

        result = api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(action="retrait", competence="Kubernetes"),
        )
        assert "Kubernetes" not in result["html"]
        assert "Kubernetes" not in result["en_html"]


class TestCritere20TitreSurLesDeuxVersions:
    def test_changer_le_titre_change_les_deux(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 14
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        result = api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Titre voulu"))
        assert "Titre voulu" in result["html"]
        assert "Titre voulu" in result["en_html"]


class TestCritere21MarquePreteCommuneAuxDeuxVersions:
    def test_la_production_par_bouton_efface_la_marque(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "prete"

        api_cv.create_cv_en(offer_id)
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"

    def test_une_correction_efface_la_marque_meme_avec_anglais(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 16
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))

        api_cv.correct_cv_skill(
            offer_id, api_cv.SkillCorrectionIn(action="retrait", competence="Rust")
        )
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"


class TestCritere22RelancerRefaitLesDeuxVersions:
    def test_relance_apres_avoir_eu_l_anglais_le_refait(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 17
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)
        assert _cvs_row(db_path, offer_id)["en_html"] is not None

        # Offre relancée alors que l'annonce n'est plus détectée anglaise (cas
        # réel : re-détection, ou l'offre a été corrigée) : l'anglais persiste.
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE offers SET ad_language = 'fr' WHERE id = ?", (offer_id,))
        conn.commit()
        conn.close()

        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["en_html"] is not None


class TestCritere23ReferenceAnglaiseAbsente:
    def test_francais_produit_quand_meme_message_nomme_le_fichier(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        ref_en_path = cv_fixture_paths[1]
        ref_en_path.unlink()

        offer_id = 18
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["html"] is not None
        assert row["en_html"] is None
        assert row["en_error_message"]
        assert str(ref_en_path) in row["en_error_message"]

    def test_bouton_signale_aussi_le_fichier_manquant(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 19
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)

        ref_en_path = cv_fixture_paths[1]
        ref_en_path.unlink()

        result = api_cv.create_cv_en(offer_id)
        assert result["en_html"] is None
        assert result["en_error_message"]
        assert str(ref_en_path) in result["en_error_message"]


class TestAucunAppelModelePourLAnglais:
    def test_bouton_n_appelle_pas_le_sdk(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 20
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)

        def _boom(*, prompt, options):
            raise AssertionError("le modèle a été appelé pour produire le CV anglais")

        monkeypatch.setattr(cv_service, "query", _boom)
        result = api_cv.create_cv_en(offer_id)
        assert result["en_html"] is not None

    def test_cout_enregistre_ne_change_pas_avec_l_anglais(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 21
        _insert_offer(db_path, offer_id, techs=[], ad_language="fr")
        _run_cv(monkeypatch, offer_id)
        cost_avant = _cvs_row(db_path, offer_id)["cost_usd"]

        api_cv.create_cv_en(offer_id)
        assert _cvs_row(db_path, offer_id)["cost_usd"] == cost_avant


class TestLeFrancaisNeChangePasPourUneOffreAnglaise:
    def test_html_francais_identique_avec_ou_sans_anglais(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id_fr = 22
        offer_id_en = 23
        _insert_offer(
            db_path, offer_id_fr, techs=[], ad_language="fr", title="Titre H/F"
        )
        _insert_offer(
            db_path, offer_id_en, techs=[], ad_language="en", title="Titre H/F"
        )
        _run_cv(monkeypatch, offer_id_fr)
        _run_cv(monkeypatch, offer_id_en)
        assert (
            _cvs_row(db_path, offer_id_fr)["html"]
            == _cvs_row(db_path, offer_id_en)["html"]
        )
