"""Tests EXE-208 — navigateur réel (Playwright/Chromium, H7) : dans Modifier, la
bascule de profil a un troisième bouton « Profil développeur » (critères 1, 4,
5, 7, 8, 10).

Outillage repris de `test_exe202_navigateur.py` et `test_exe207_navigateur.py` :
front et API lancés une fois pour le module, base, CV de référence, coordonnées
et fichiers de profil posés sous `tmp_path` par chaque test. Aucun test ne lit
ni n'écrit sous data/.
"""

import re

import pytest
from playwright.sync_api import expect

import orchestrator.job_search.cv.profil as cv_profil
from tests import test_exe202_navigateur as nav
from tests import test_exe207_navigateur as nav207
from tests.test_exe185_cv_profil_affichage import REF_CV_HTML_EN, REF_CV_HTML_FR

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path
coordonnees_path = nav207.coordonnees_path
cv_fixture_paths = nav207.cv_fixture_paths

PROFIL_DEV_FR = "Developpeur backend Python EXE208, je construis des API solides."
PROFIL_DEV_EN = "Backend Python developer EXE208, I build solid APIs."
MIS_EN_EVIDENCE = re.compile(r"(^|\s)bg-indigo-600(\s|$)")


@pytest.fixture
def dev_paths(tmp_path, monkeypatch):
    fr = tmp_path / "profil_dev.fr.txt"
    fr.write_text(PROFIL_DEV_FR, encoding="utf-8")
    en = tmp_path / "profil_dev.en.txt"
    en.write_text(PROFIL_DEV_EN, encoding="utf-8")
    monkeypatch.setattr(cv_profil, "CV_PROFIL_DEV_FR_PATH", fr, raising=False)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_DEV_EN_PATH", en, raising=False)
    return fr, en


def _ouvrir_modifier(page, front_url, offer_id):
    nav207._ouvrir_apercu_cv(page, front_url, offer_id)
    page.get_by_role("button", name="Modifier").click()
    return nav._onglet(page)


class TestCritere1TroisBoutons:
    def test_base_claude_developpeur(self, page, front_url, db_path, cv_fixture_paths):
        nav._insert_offer(db_path, 8001)
        nav207._insert_cv(db_path, 8001, html=REF_CV_HTML_FR)

        overlay = _ouvrir_modifier(page, front_url, 8001)
        for nom in ("Profil base", "Profil Claude", "Profil développeur"):
            expect(overlay.get_by_role("button", name=nom)).to_be_visible()


class TestCritere4Et5Et7Et8ChoixDeveloppeur:
    def test_mis_en_evidence_phrase_rechargement_et_pdf(
        self,
        page,
        front_url,
        db_path,
        cv_fixture_paths,
        dev_paths,
        coordonnees_path,
    ):
        nav._insert_offer(db_path, 8002)
        nav207._insert_cv(db_path, 8002, html=REF_CV_HTML_FR)

        overlay = _ouvrir_modifier(page, front_url, 8002)
        dev = overlay.get_by_role("button", name="Profil développeur")
        expect(dev).to_be_visible()
        dev.click()

        # Critères 4 et 5.
        expect(overlay.get_by_text("Choisi par toi", exact=True)).to_be_visible()
        expect(dev).to_have_class(MIS_EN_EVIDENCE)

        # Critère 8 : le PDF porte le paragraphe développeur.
        bouton_pdf = overlay.get_by_role("button", name="Télécharger le PDF")
        texte = nav207._texte_telecharge(page, bouton_pdf)
        assert "EXE208" in " ".join(texte.split())

        # Critère 7 : après rechargement, le bouton reste mis en évidence.
        page.reload()
        page.wait_for_load_state("networkidle")
        overlay = _ouvrir_modifier(page, front_url, 8002)
        dev = overlay.get_by_role("button", name="Profil développeur")
        expect(dev).to_have_class(MIS_EN_EVIDENCE)
        expect(overlay.get_by_text("Choisi par toi", exact=True)).to_be_visible()


class TestCritere10FichierFrancaisAbsent:
    def test_message_nomme_le_fichier(
        self, page, front_url, db_path, cv_fixture_paths, dev_paths
    ):
        dev_fr, _ = dev_paths
        dev_fr.unlink()
        nav._insert_offer(db_path, 8003)
        nav207._insert_cv(db_path, 8003, html=REF_CV_HTML_FR)

        overlay = _ouvrir_modifier(page, front_url, 8003)
        dev = overlay.get_by_role("button", name="Profil développeur")
        expect(dev).to_be_visible()
        dev.click()
        expect(overlay.get_by_text(str(dev_fr))).to_be_visible()


class TestCritere11FichierAnglaisAbsent:
    def test_francais_change_anglais_nomme_le_fichier(
        self, page, front_url, db_path, cv_fixture_paths, dev_paths
    ):
        _, dev_en = dev_paths
        dev_en.unlink()
        nav._insert_offer(db_path, 8004)
        nav207._insert_cv(db_path, 8004, html=REF_CV_HTML_FR, en_html=REF_CV_HTML_EN)

        overlay = _ouvrir_modifier(page, front_url, 8004)
        dev = overlay.get_by_role("button", name="Profil développeur")
        expect(dev).to_be_visible()
        dev.click()
        expect(overlay.get_by_text("Choisi par toi", exact=True)).to_be_visible()
        expect(overlay.get_by_text(str(dev_en))).to_be_visible()
