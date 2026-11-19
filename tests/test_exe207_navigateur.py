"""Tests EXE-207 — navigateur réel (Playwright/Chromium, H4) : le PDF du CV se
télécharge depuis l'aperçu plein écran, et la bascule de profil ne vit plus que
dans Modifier (critères 1 à 9, et « aucun bouton PDF tant que le CV n'est pas
terminé »).

Outillage repris de `test_exe202_navigateur.py` : front et API lancés une fois
pour le module, base posée par chaque test dans un dossier temporaire. Le
téléchargement est attrapé par Playwright, et son texte lu par
`tests/pdf_inspect.py` pour dire quelle version du CV il porte. Coordonnées, CV
de référence et fichiers de profil sont sous `tmp_path` : aucun test ne lit ni
n'écrit sous data/.
"""

import sqlite3
from pathlib import Path

import pytest
from playwright.sync_api import expect

import orchestrator.job_search.cv.profil as cv_profil
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
from tests import test_exe202_navigateur as nav
from tests.pdf_inspect import extract_text
from tests.test_exe185_cv_profil_affichage import (
    PROFIL_CLAUDE_EN,
    PROFIL_CLAUDE_FR,
    PROFIL_DE_BASE_FR,
    REF_CV_HTML_EN,
    REF_CV_HTML_FR,
)

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path

MARQUE_FR = "Curriculum en francais EXE207"
MARQUE_EN = "Resume in English EXE207"


def _cv_html(marque: str, lead: str) -> str:
    return (
        "<html><body><h1>"
        f'{marque}</h1><section><p class="lead">{lead}</p></section>'
        "</body></html>"
    )


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


@pytest.fixture
def cv_fixture_paths(tmp_path, monkeypatch):
    ref = tmp_path / "cv_reference.html"
    ref.write_text(REF_CV_HTML_FR, encoding="utf-8")
    ref_en = tmp_path / "cv_reference_en.html"
    ref_en.write_text(REF_CV_HTML_EN, encoding="utf-8")
    claude_fr = tmp_path / "profil_claude.fr.txt"
    claude_fr.write_text(PROFIL_CLAUDE_FR, encoding="utf-8")
    claude_en = tmp_path / "profil_claude.en.txt"
    claude_en.write_text(PROFIL_CLAUDE_EN, encoding="utf-8")
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_EN_PATH", ref_en)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_FR_PATH", claude_fr)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_EN_PATH", claude_en)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_EN_PATH", ref_en)


def _insert_cv(db_path, offer_id, *, html, en_html=None, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, en_html, titre, localisation, "
            "groupes_json, notions_json, created_at) "
            "VALUES (?, ?, ?, ?, 'Titre', 'Strasbourg', '[]', '[]', ?)",
            (offer_id, statut, html, en_html, nav._now()),
        )
        conn.commit()
    finally:
        conn.close()


def _ouvrir_apercu_cv(page, front_url, offer_id):
    page.goto(f"{front_url}/offers/{offer_id}")
    page.wait_for_load_state("networkidle")
    page.get_by_text("CV", exact=True).first.click()
    expect(page.get_by_title("Aperçu du CV")).to_be_visible()


def _entete_apercu(page):
    """En-tête de l'aperçu plein écran : le bloc qui porte le bouton
    « Fermer l'aperçu »."""
    fermer = page.get_by_role("button", name="Fermer l'aperçu")
    return fermer.locator("xpath=ancestor::div[contains(@class,'justify-between')][1]")


def _texte_telecharge(page, bouton) -> str:
    with page.expect_download() as info:
        bouton.click()
    chemin = info.value.path()
    assert info.value.suggested_filename.endswith(".pdf")
    return extract_text(Path(chemin).read_bytes())


class TestCritere1Et2SansVersionAnglaise:
    def test_bouton_unique_telecharge_le_cv_francais(
        self, page, front_url, db_path, coordonnees_path
    ):
        nav._insert_offer(db_path, 7001)
        _insert_cv(db_path, 7001, html=_cv_html(MARQUE_FR, PROFIL_DE_BASE_FR))

        _ouvrir_apercu_cv(page, front_url, 7001)
        entete = _entete_apercu(page)
        bouton = entete.get_by_role("button", name="Télécharger le PDF")
        expect(bouton).to_be_visible()
        assert entete.get_by_role("button", name="PDF EN").count() == 0

        texte = _texte_telecharge(page, bouton)
        assert MARQUE_FR in texte
        assert MARQUE_EN not in texte


class TestCritere3a5AvecVersionAnglaise:
    def test_deux_boutons_et_chaque_langue(
        self, page, front_url, db_path, coordonnees_path
    ):
        nav._insert_offer(db_path, 7002)
        _insert_cv(
            db_path,
            7002,
            html=_cv_html(MARQUE_FR, PROFIL_DE_BASE_FR),
            en_html=_cv_html(MARQUE_EN, "Base profile, unchanged."),
        )

        _ouvrir_apercu_cv(page, front_url, 7002)
        entete = _entete_apercu(page)
        pdf_fr = entete.get_by_role("button", name="PDF FR")
        pdf_en = entete.get_by_role("button", name="PDF EN")
        expect(pdf_fr).to_be_visible()
        expect(pdf_en).to_be_visible()
        assert entete.get_by_role("button", name="Télécharger le PDF").count() == 0

        texte_en = _texte_telecharge(page, pdf_en)
        assert MARQUE_EN in texte_en
        assert MARQUE_FR not in texte_en

        texte_fr = _texte_telecharge(page, pdf_fr)
        assert MARQUE_FR in texte_fr
        assert MARQUE_EN not in texte_fr


class TestCritere6ApercuSansBasculeDeProfil:
    def test_entete_sans_profil_base_ni_claude(self, page, front_url, db_path):
        nav._insert_offer(db_path, 7003)
        _insert_cv(db_path, 7003, html=_cv_html(MARQUE_FR, PROFIL_DE_BASE_FR))

        _ouvrir_apercu_cv(page, front_url, 7003)
        entete = _entete_apercu(page)
        expect(entete.get_by_role("button", name="Modifier")).to_be_visible()
        assert entete.get_by_role("button", name="Profil base").count() == 0
        assert entete.get_by_role("button", name="Profil Claude").count() == 0


class TestCritere7a9Modifier:
    def test_profil_et_pdf_dans_modifier(
        self, page, front_url, db_path, cv_fixture_paths
    ):
        nav._insert_offer(db_path, 7004)
        _insert_cv(db_path, 7004, html=REF_CV_HTML_FR)

        _ouvrir_apercu_cv(page, front_url, 7004)
        page.get_by_role("button", name="Modifier").click()
        overlay = nav._onglet(page)

        # Critère 7.
        base = overlay.get_by_role("button", name="Profil base")
        claude = overlay.get_by_role("button", name="Profil Claude")
        expect(base).to_be_visible()
        expect(claude).to_be_visible()
        # Critère 9.
        expect(overlay.get_by_role("button", name="Télécharger le PDF")).to_be_visible()

        # Critère 8.
        phrase_avant = "CV généré avant le choix automatique du profil"
        expect(overlay.get_by_text(phrase_avant, exact=True)).to_be_visible()
        claude.click()
        expect(overlay.get_by_text("Choisi par toi", exact=True)).to_be_visible()
        assert overlay.get_by_text(phrase_avant, exact=True).count() == 0


class TestPasDeBoutonPdfAvantTermine:
    def test_cv_en_generation_sans_bouton_pdf(self, page, front_url, db_path):
        nav._insert_offer(db_path, 7005)
        _insert_cv(db_path, 7005, html=None, statut="pending")

        page.goto(f"{front_url}/offers/7005")
        page.wait_for_load_state("networkidle")
        page.get_by_text("CV", exact=True).first.click()
        # Un CV en cours n'ouvre pas l'aperçu : aucun bouton PDF nulle part.
        expect(page.get_by_title("Aperçu du CV")).to_have_count(0)
        for nom in ("Télécharger le PDF", "PDF FR", "PDF EN"):
            assert page.get_by_role("button", name=nom).count() == 0
