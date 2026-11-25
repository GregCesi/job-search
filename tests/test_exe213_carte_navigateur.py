"""Tests EXE-213 — navigateur réel (Playwright/Chromium, H8) sur la page de la
carte, ouverte depuis le disque, sans serveur et réseau coupé (critères 4, 5,
7, 10 à 18, 21 à 25, 27).

Réécrits par EXE-216 pour la carte dessinée : les systèmes et les fichiers sont
des blocs du dessin (`#dessin`), le texte d'un fichier est dans le panneau
(`#panneau`). Ce que chaque test affirme ne change pas.

Ni le front ni l'API ne sont lancés. La page est générée dans un dossier
temporaire, par la commande lancée en sous-processus (`tests/carte_terrains.py`).
"""

from __future__ import annotations

import re
import subprocess

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.carte_navigateur import bloc, cliquer_coin, fleche, panneau, section
from tests.carte_terrains import (
    PAS_DE_PHRASE,
    REPO,
    lancer_carte,
    lire_donnees,
    poser_depot_essai,
)


@pytest.fixture(scope="module")
def page_vraie(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("carte_vraie_nav") / "index.html"
    res = lancer_carte(REPO, sortie)
    return res, sortie


@pytest.fixture(scope="module")
def page_essai(tmp_path_factory):
    racine = poser_depot_essai(tmp_path_factory.mktemp("essai_nav") / "essai")
    res = lancer_carte(racine)
    return res, racine / "docs" / "carte" / "index.html"


@pytest.fixture(scope="module")
def navigateur():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


class _Onglet:
    """Un onglet hors ligne qui note toute requête hors disque et toute erreur."""

    def __init__(self, navigateur):
        self.contexte = navigateur.new_context(offline=True)
        self.page = self.contexte.new_page()
        self.erreurs: list[str] = []
        self.requetes_hors_disque: list[str] = []
        self.page.on(
            "console",
            lambda m: self.erreurs.append(m.text) if m.type == "error" else None,
        )
        self.page.on("pageerror", lambda e: self.erreurs.append(str(e)))
        self.page.on("request", self._requete)

    def _requete(self, requete):
        if not requete.url.startswith(("file:", "data:", "about:")):
            self.requetes_hors_disque.append(requete.url)

    def ouvrir(self, sortie, ancre=""):
        assert sortie.is_file(), f"page absente : {sortie}"
        self.page.goto(sortie.as_uri() + ancre)
        self.page.wait_for_load_state("load")
        return self.page


@pytest.fixture
def onglet(navigateur):
    o = _Onglet(navigateur)
    yield o
    o.contexte.close()


def _ouvrir_fichier(page, chemin):
    page.evaluate("c => { location.hash = '#/fichier/' + c }", chemin)
    expect(panneau(page).locator("h2.chemin")).to_have_text(chemin)


class TestLaPage:
    def test_critere4_un_seul_fichier_hors_ligne_sans_erreur(self, page_vraie, onglet):
        res, sortie = page_vraie
        assert res.returncode == 0, res.stdout + res.stderr
        page = onglet.ouvrir(sortie, "#/systemes")
        expect(page.locator("#dessin g.bloc[data-systeme]").first).to_be_visible()
        _ouvrir_fichier(page, "orchestrator/job_search/cv/service.py")
        assert onglet.erreurs == []
        assert onglet.requetes_hors_disque == []
        assert [p.name for p in sortie.parent.iterdir()] == ["index.html"]

    def test_critere5_date_et_commit(self, page_vraie, onglet):
        _, sortie = page_vraie
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.strip()
        page = onglet.ouvrir(sortie)
        meta = page.locator("#meta")
        expect(meta).to_contain_text(commit)
        assert re.search(r"\d{4}-\d{2}-\d{2}", meta.inner_text())


class TestLesSystemes:
    def test_critere7_la_page_s_ouvre_sur_les_systemes(self, page_essai, onglet):
        res, sortie = page_essai
        assert res.returncode == 0, res.stdout + res.stderr
        page = onglet.ouvrir(sortie, "#/systemes")
        carte_a = bloc(page, "data-systeme", "a")
        expect(carte_a).to_contain_text("Système A")
        expect(carte_a).to_contain_text("2 fichiers")
        carte_a.hover()
        expect(panneau(page).locator(".role")).to_have_text("Rôle du système A.")

    def test_critere10_fleche_de_a_vers_b(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/systemes")
        fleches = page.locator("#dessin path.fl[data-de=a], #dessin path.fl[data-de=b]")
        expect(fleches).to_have_count(1)
        expect(fleches.first).to_have_attribute("data-de", "a")
        expect(fleches.first).to_have_attribute("data-vers", "b")
        expect(fleche(page, "a", "b").locator("title")).to_contain_text("1 import")

    def test_critere11_clic_systeme_montre_ses_fichiers(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/systemes")
        cliquer_coin(page, bloc(page, "data-systeme", "a"))
        expect(bloc(page, "data-fichier", "api/a1.py")).to_be_visible()
        fichiers = section(page, "Ses fichiers")
        expect(fichiers.locator("li", has_text="api/a1.py")).to_contain_text(
            "Première phrase de a1."
        )
        expect(fichiers.locator("li", has_text="api/a2.py")).to_contain_text(
            PAS_DE_PHRASE
        )


class TestUnFichier:
    def test_critere12_phrase_et_lignes(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/systeme/a")
        cliquer_coin(page, bloc(page, "data-fichier", "api/a1.py"))
        expect(panneau(page).locator("h2.chemin")).to_have_text("api/a1.py")
        expect(panneau(page).locator(".phrase")).to_have_text("Première phrase de a1.")
        expect(panneau(page).locator(".lignes")).to_have_text("5 lignes")

    def test_critere13_ce_qu_il_importe(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/api/a1.py")
        expect(section(page, "Ce qu'il importe")).to_contain_text("orchestrator/b1.py")

    def test_critere14_qui_l_importe(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/orchestrator/b1.py")
        expect(section(page, "Qui l'importe")).to_contain_text("api/a1.py")

    def test_critere15_les_tests_qui_l_importent(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/api/a1.py")
        expect(section(page, "Les tests qui l'importent")).to_contain_text(
            "tests/test_a1.py"
        )

    def test_critere16_aucun_test(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/orchestrator/b2.py")
        expect(section(page, "Les tests qui l'importent")).to_contain_text(
            "Aucun test ne l'importe directement."
        )

    def test_critere17_clic_dans_une_liste(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/api/a1.py")
        section(page, "Ce qu'il importe").get_by_role(
            "link", name="orchestrator/b1.py"
        ).click()
        expect(panneau(page).locator("h2.chemin")).to_have_text("orchestrator/b1.py")

    def test_critere18_service_du_cv(self, page_vraie, onglet):
        _, sortie = page_vraie
        page = onglet.ouvrir(sortie)
        _ouvrir_fichier(page, "orchestrator/job_search/cv/service.py")
        expect(section(page, "Ce qu'il importe")).to_contain_text(
            "orchestrator/job_search/cv/skills.py"
        )
        expect(section(page, "Qui l'importe")).to_contain_text("api/cv.py")
        expect(section(page, "Les tests qui l'importent")).to_contain_text(
            "tests/test_cv_service.py"
        )


class TestLesPhrases:
    def test_critere19_premiere_phrase_seule(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/api/a1.py")
        expect(panneau(page).locator(".phrase")).to_have_text("Première phrase de a1.")

    def test_critere21_pas_de_phrase(self, page_essai, onglet):
        res, sortie = page_essai
        assert "signalé : fichier sans phrase : api/a2.py" in res.stdout
        page = onglet.ouvrir(sortie, "#/fichier/api/a2.py")
        expect(panneau(page).locator(".phrase")).to_have_text(PAS_DE_PHRASE)

    def test_critere22_aucun_fichier_sans_phrase(self, page_vraie, onglet):
        _, sortie = page_vraie
        chemins = sorted(lire_donnees(sortie)["fichiers"])
        assert len(chemins) > 100
        page = onglet.ouvrir(sortie)
        sans = []
        for chemin in chemins:
            _ouvrir_fichier(page, chemin)
            texte = panneau(page).locator(".phrase").inner_text().strip()
            if not texte or texte == PAS_DE_PHRASE:
                sans.append(chemin)
        assert sans == []


class TestSeDeplacer:
    def test_critere23_recherche(self, page_vraie, onglet):
        _, sortie = page_vraie
        page = onglet.ouvrir(sortie)
        page.get_by_role("searchbox", name="Rechercher un fichier").fill("skills")
        page.locator("#resultats").get_by_role(
            "link", name="orchestrator/job_search/cv/skills.py"
        ).click()
        expect(panneau(page).locator("h2.chemin")).to_have_text(
            "orchestrator/job_search/cv/skills.py"
        )

    def test_critere24_fil_d_ariane(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/fichier/api/a1.py")
        ariane = page.get_by_role("navigation", name="Fil d'Ariane")
        expect(ariane).to_contain_text("La carte")
        expect(ariane).to_contain_text("Système A")
        expect(ariane).to_contain_text("api/a1.py")
        ariane.get_by_role("link", name="Système A").click()
        expect(bloc(page, "data-fichier", "api/a1.py")).to_be_visible()
        expect(page.locator("#dessin g.bloc[data-fichier]")).to_have_count(2)

    def test_critere25_recharger_garde_le_fichier(self, page_essai, onglet):
        _, sortie = page_essai
        page = onglet.ouvrir(sortie, "#/systemes")
        cliquer_coin(page, bloc(page, "data-systeme", "b"))
        cliquer_coin(page, bloc(page, "data-fichier", "orchestrator/b1.py"))
        expect(panneau(page).locator("h2.chemin")).to_have_text("orchestrator/b1.py")
        page.reload()
        expect(panneau(page).locator("h2.chemin")).to_have_text("orchestrator/b1.py")


class TestAutres:
    def test_critere27_fichier_nouveau_dans_autres(self, tmp_path, navigateur, onglet):
        racine = poser_depot_essai(tmp_path / "essai")
        (racine / "orchestrator" / "nouveau.py").write_text('"""Neuf."""\n')
        res = lancer_carte(racine)
        assert res.returncode == 0, res.stdout + res.stderr
        page = onglet.ouvrir(racine / "docs" / "carte" / "index.html", "#/systemes")
        autres = bloc(page, "data-systeme", "autres")
        expect(autres).to_contain_text("Autres (à ranger)")
        expect(autres).to_contain_text("1 fichier")
        cliquer_coin(page, autres)
        expect(bloc(page, "data-fichier", "orchestrator/nouveau.py")).to_be_visible()
