"""Tests EXE-185 — le profil du CV se voit en tête de carte, constaté sur le
texte du CV, jamais sur le seul champ enregistré (critères 2, 4 à 8, 10, 11).

Aucun test n'appelle le modèle. Aucun test ne lit ni n'écrit sous data/ : CV de
référence FR/EN et fichiers de profil sont des fichiers tmp_path (H4 du
ticket).
"""

import sqlite3

import pytest

import api.cv as api_cv
import api.db as api_db
import orchestrator.job_search.cv.profil as cv_profil
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
    <section><h2 class="m">Profil</h2><p class="lead">Profil de base, inchangé.</p></section>

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

REF_CV_HTML_EN = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Old title</div>
    <section><h2 class="m">Profile</h2><p class="lead">Base profile, unchanged.</p></section>
  </div>
</body></html>
"""

PROFIL_CLAUDE_FR = "Je travaille chaque jour avec Claude et son écosystème."
PROFIL_CLAUDE_EN = "I work every day with the Claude ecosystem."
PROFIL_DE_BASE_FR = "Profil de base, inchangé."


def _cv_html(lead: str) -> str:
    return f'<html><body><section><p class="lead">{lead}</p></section></body></html>'


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
    profil_claude_fr = tmp_path / "profil_claude.fr.txt"
    profil_claude_fr.write_text(PROFIL_CLAUDE_FR, encoding="utf-8")
    profil_claude_en = tmp_path / "profil_claude.en.txt"
    profil_claude_en.write_text(PROFIL_CLAUDE_EN, encoding="utf-8")
    # `constate_profil` (cv/profil.py) et `set_profile_manual` (cv/service.py)
    # lisent chacun leur propre nom importé : les deux modules sont patchés
    # vers les mêmes fichiers tmp_path (H1, H4 du ticket).
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_EN_PATH", ref_en)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_FR_PATH", profil_claude_fr)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_EN_PATH", profil_claude_en)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_EN_PATH", ref_en)
    return ref, ref_en, profil_claude_fr, profil_claude_en


def _insert_cv(
    db_path,
    offer_id,
    *,
    html,
    en_html=None,
    profil=None,
    profil_motif=None,
    statut="done",
    titre="Titre H/F",
    localisation="Strasbourg, France",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, en_html, profil, profil_motif, "
            "titre, localisation, groupes_json, notions_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', '2026-10-16')",
            (
                offer_id,
                statut,
                html,
                en_html,
                profil,
                profil_motif,
                titre,
                localisation,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TestCritere2ProfilConstateSurLeTexte:
    """Le bouton mis en évidence suit le texte du CV, jamais le seul champ enregistré."""

    def test_cv_porte_le_profil_claude(self, db_path, cv_fixture_paths):
        offer_id = 1
        _insert_cv(db_path, offer_id, html=_cv_html(PROFIL_CLAUDE_FR))
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "claude"

    def test_cv_porte_le_profil_de_base(self, db_path, cv_fixture_paths):
        offer_id = 2
        _insert_cv(db_path, offer_id, html=_cv_html(PROFIL_DE_BASE_FR))
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "base"

    def test_le_champ_enregistre_seul_ne_suffit_pas(self, db_path, cv_fixture_paths):
        """Un profil enregistré 'claude' sans que le texte du CV le porte ne
        doit pas suffire à mettre le bouton Claude en évidence (le texte
        prévaut, cf. critère 8)."""
        offer_id = 3
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_DE_BASE_FR),
            profil="claude",
            profil_motif="technos_offre",
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "base"


class TestCritere5SansProfilEnregistre:
    def test_phrase_cv_genere_avant_le_choix_automatique(
        self, db_path, cv_fixture_paths
    ):
        offer_id = 4
        _insert_cv(db_path, offer_id, html=_cv_html(PROFIL_DE_BASE_FR))
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "base"
        assert cv["profil_phrase"] == cv_profil.PHRASE_SANS_PROFIL

    def test_vaut_aussi_pour_le_profil_claude(self, db_path, cv_fixture_paths):
        offer_id = 5
        _insert_cv(db_path, offer_id, html=_cv_html(PROFIL_CLAUDE_FR))
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "claude"
        assert cv["profil_phrase"] == cv_profil.PHRASE_SANS_PROFIL


class TestCritere6ProfilNonReconnu:
    def test_texte_etranger_aux_deux_profils(self, db_path, cv_fixture_paths):
        offer_id = 6
        _insert_cv(
            db_path, offer_id, html=_cv_html("Un texte quelconque, écrit à la main.")
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] is None
        assert cv["profil_phrase"] == cv_profil.PHRASE_NON_RECONNU


class TestCritere7VersionsFrEnDifferentes:
    def test_fr_base_en_claude(self, db_path, cv_fixture_paths):
        offer_id = 7
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_DE_BASE_FR),
            en_html=_cv_html(PROFIL_CLAUDE_EN),
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_phrase"] == cv_profil.PHRASE_FR_EN_DIFFERENT

    def test_fr_et_en_identiques_ne_declenche_pas_le_message(
        self, db_path, cv_fixture_paths
    ):
        offer_id = 8
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_CLAUDE_FR),
            en_html=_cv_html(PROFIL_CLAUDE_EN),
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_phrase"] != cv_profil.PHRASE_FR_EN_DIFFERENT


class TestCritere8ProfilEnregistreIncoherent:
    def test_enregistre_base_mais_texte_claude(self, db_path, cv_fixture_paths):
        offer_id = 9
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_CLAUDE_FR),
            profil="base",
            profil_motif="aucune_mention",
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_affiche"] == "claude"
        assert cv["profil_phrase"] == cv_profil.PHRASE_INCOHERENT

    def test_coherent_ne_declenche_pas_le_message(self, db_path, cv_fixture_paths):
        offer_id = 10
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_CLAUDE_FR),
            profil="claude",
            profil_motif="technos_offre",
        )
        cv = api_cv.get_cv(offer_id)
        assert cv["profil_phrase"] != cv_profil.PHRASE_INCOHERENT


class TestCritere10ClicPoseLeProfilChoisi:
    def test_clic_sur_le_bouton_non_mis_en_evidence(self, db_path, cv_fixture_paths):
        offer_id = 11
        _insert_cv(
            db_path,
            offer_id,
            html=_cv_html(PROFIL_DE_BASE_FR),
            profil="base",
            profil_motif="aucune_mention",
        )
        result = api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))
        assert result["profil_affiche"] == "claude"
        assert result["profil_phrase"] == "Choisi par toi"


class TestCritere11ClicSansProfilEnregistre:
    def test_clic_sur_cv_sans_profil_enregistre(self, db_path, cv_fixture_paths):
        offer_id = 12
        _insert_cv(db_path, offer_id, html=_cv_html(PROFIL_DE_BASE_FR))
        result = api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))
        assert result["profil_affiche"] == "claude"
        assert result["profil_phrase"] == "Choisi par toi"
