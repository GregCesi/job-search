"""Tests EXE-215 — navigateur réel (Playwright/Chromium, H9) sur la page de la
carte, ouverte depuis le disque, sans serveur et réseau coupé : vue d'ensemble
(critères 1 à 6), parcours (7 à 13, 20) et « Depuis la dernière carte » (24,
26, 31), plus le total hors stockage sur la vue d'ouverture (33).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.carte_terrains import (
    REPO,
    lancer_carte,
    lire_donnees,
    poser_depot_essai_etendu,
)

BLOCS = [
    "Écrans",
    "API",
    "Cœur métier",
    "Base",
    "Modèles",
    "Sources d'offres",
    "Profils",
]
FLECHES = [
    ("ecrans", "api"),
    ("api", "coeur"),
    ("api", "base"),
    ("coeur", "base"),
    ("coeur", "modeles"),
    ("coeur", "sources"),
    ("coeur", "profils"),
]
RETENIR = "Je retiens une offre : son CV est généré et rangé en base"
COUCHES = {"écran", "route", "métier", "stockage", "table"}
TITRE_DU_GENRE = {
    "fichier": "#vue h2.chemin",
    "route": "#vue h2.route",
    "table": "#vue h2.table",
}


@pytest.fixture(scope="module")
def page_vraie(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("parcours_nav")
    sortie = dossier / "page" / "index.html"
    res = lancer_carte(REPO, sortie, dossier / "graphe.json")
    assert res.returncode == 0, res.stdout + res.stderr
    return sortie


@pytest.fixture(scope="module")
def navigateur():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(navigateur):
    contexte = navigateur.new_context(offline=True)
    onglet = contexte.new_page()
    erreurs: list[str] = []
    onglet.on("pageerror", lambda e: erreurs.append(str(e)))
    yield onglet
    contexte.close()
    assert erreurs == []


def _ouvrir(page, sortie, ancre=""):
    page.goto(sortie.as_uri() + ancre)
    page.wait_for_load_state("load")
    return page


def _vue(page):
    return page.locator("#vue")


def _bloc(page, nom):
    return (
        _vue(page)
        .locator("article.bloc-ensemble")
        .filter(has=page.get_by_role("heading", name=nom, exact=True))
    )


class TestLaVueDEnsemble:
    def test_critere1_sept_blocs_avec_leur_role(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        blocs = _vue(page).locator("article.bloc-ensemble")
        expect(blocs.locator("h3")).to_have_text(BLOCS)
        for nom in BLOCS:
            role = _bloc(page, nom).locator(".role").inner_text().strip()
            assert role, nom

    def test_critere2_sept_fleches_avec_libelle(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        fleches = _vue(page).locator("li.fleche-ensemble")
        expect(fleches).to_have_count(7)
        lues = []
        for i in range(7):
            f = fleches.nth(i)
            lues.append((f.get_attribute("data-de"), f.get_attribute("data-vers")))
            assert f.locator(".libelle").inner_text().strip(" ·")
        assert sorted(lues) == sorted(FLECHES)

    def test_critere3_bloc_ecrans(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _bloc(page, "Écrans").get_by_role("link", name="Écrans").click()
        expect(_vue(page).locator("h2").first).to_have_text("Écrans")
        expect(_vue(page).locator("li.fichier").first).to_be_visible()

    @pytest.mark.parametrize("nom", ["API", "Cœur métier"])
    def test_critere4_blocs_api_et_coeur(self, page_vraie, page, nom):
        _ouvrir(page, page_vraie)
        _bloc(page, nom).get_by_role("link", name=nom, exact=True).click()
        expect(page.get_by_role("heading", name="Systèmes", exact=True)).to_be_visible()
        expect(_vue(page).locator("article.systeme").first).to_be_visible()

    def test_critere5_bloc_base(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _bloc(page, "Base").get_by_role("link", name="Base", exact=True).click()
        expect(page.locator("#vue h2").first).to_have_text("Tables")
        expect(_vue(page).locator("li.table", has_text="cvs")).to_be_visible()

    def test_critere6_les_systemes_et_retour(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _vue(page).get_by_role("link", name="Les systèmes", exact=True).click()
        expect(page.get_by_role("heading", name="Systèmes", exact=True)).to_be_visible()
        page.get_by_role("navigation", name="Fil d'Ariane").get_by_role(
            "link", name="Carte"
        ).click()
        expect(_vue(page).locator("article.bloc-ensemble")).to_have_count(7)

    def test_critere33_total_hors_stockage_a_l_ouverture(self, page_vraie, page):
        total = lire_donnees(page_vraie)["base"]["hors_stockage"]
        _ouvrir(page, page_vraie)
        expect(_vue(page).locator(".total-base")).to_contain_text(
            f"{total} appels directs à la base hors stockage"
        )


def _ouvrir_parcours(page, nom):
    page.locator("ul.liste-parcours").get_by_role("link", name=nom, exact=True).click()
    expect(page.locator("#vue h2.parcours-nom")).to_have_text(nom)


class TestSuivreUnParcours:
    def test_critere7_quatre_parcours_proposes(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        expect(page.locator("ul.liste-parcours li a")).to_have_text(
            [
                RETENIR,
                "Le run : d'une source à une offre classée",
                "Je change mon profil : tout se reclasse sans appeler un modèle",
                "Je marque une candidature envoyée",
            ]
        )

    def test_critere8_etape_1(self, page_vraie, page):
        n = len(lire_donnees(page_vraie)["parcours"][0]["etapes"])
        _ouvrir(page, page_vraie)
        _ouvrir_parcours(page, RETENIR)
        expect(page.locator("#vue .numero")).to_have_text(f"Étape 1 sur {n}")
        expect(page.locator("#vue .element a")).to_have_text(
            "web/app/pages/offers/[id].vue"
        )
        assert page.locator("#vue .phrase-etape").inner_text().strip()

    def test_criteres9_10_suivant_et_precedent(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _ouvrir_parcours(page, RETENIR)
        page.get_by_role("link", name="Suivant", exact=True).click()
        expect(page.locator("#vue .numero")).to_contain_text("Étape 2 sur")
        page.get_by_role("link", name="Précédent", exact=True).click()
        expect(page.locator("#vue .numero")).to_contain_text("Étape 1 sur")

    def test_critere11_couche_de_l_etape(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _ouvrir_parcours(page, RETENIR)
        expect(page.locator("#vue .couche-etape")).to_have_text("Couche : écran")

    def test_critere12_clic_sur_l_element(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        _ouvrir_parcours(page, RETENIR)
        page.locator("#vue .element a").click()
        expect(page.locator("#vue h2.chemin")).to_have_text(
            "web/app/pages/offers/[id].vue"
        )

    def test_critere13_parcours_sur_la_page_d_un_fichier(self, page_vraie, page):
        _ouvrir(page, page_vraie, "#/fichier/orchestrator/job_search/cv/service.py")
        entete = page.get_by_role("heading", name=re.compile("^Parcours qui passent"))
        section = page.locator("#vue section.liens", has=entete)
        expect(section.get_by_role("link", name=RETENIR)).to_be_visible()

    def test_critere20_chaque_etape_mene_a_un_element(self, page_vraie, page):
        donnees = lire_donnees(page_vraie)
        _ouvrir(page, page_vraie)
        vues = 0
        for p in donnees["parcours"]:
            page.evaluate("a => { location.hash = a }", "#/")
            _ouvrir_parcours(page, p["nom"])
            for n, etape in enumerate(p["etapes"], 1):
                expect(page.locator("#vue .numero")).to_contain_text(f"Étape {n} sur")
                couche = page.locator("#vue .couche-etape").inner_text()
                assert couche.removeprefix("Couche : ") in COUCHES, couche
                lien = page.locator("#vue .element a")
                expect(lien).to_have_text(etape["element"])
                lien.click()
                expect(page.locator(TITRE_DU_GENRE[etape["genre"]])).to_have_text(
                    etape["element"]
                )
                page.go_back()
                if n < len(p["etapes"]):
                    page.get_by_role("link", name="Suivant", exact=True).click()
                vues += 1
        assert vues == sum(len(p["etapes"]) for p in donnees["parcours"])


def _etat_depuis(page, sortie):
    _ouvrir(page, sortie)
    _vue(page).get_by_role("link", name="Depuis la dernière carte").click()
    expect(page.locator("#vue h2").first).to_have_text("Depuis la dernière carte")
    return _vue(page)


class TestDepuisLaDerniereCarte:
    def test_critere24_premier_releve(self, tmp_path, page):
        racine = poser_depot_essai_etendu(tmp_path / "e")
        res = lancer_carte(racine)
        assert res.returncode == 0, res.stdout + res.stderr
        vue = _etat_depuis(page, racine / "docs/carte/index.html")
        expect(vue.locator(".depuis-etat")).to_have_text("Premier relevé.")

    def test_critere26_la_fleche_disparue_est_listee(self, tmp_path, page):
        racine = poser_depot_essai_etendu(tmp_path / "e")
        lancer_carte(racine)
        a1 = racine / "api" / "a1.py"
        a1.write_text(
            a1.read_text(encoding="utf-8").replace(
                "from orchestrator import b1\n\nVALEUR = b1.VALEUR", ""
            ),
            encoding="utf-8",
        )
        lancer_carte(racine)
        vue = _etat_depuis(page, racine / "docs/carte/index.html")
        expect(vue.locator("ul.changements li")).to_contain_text(
            ["flèche disparue : api/a1.py → orchestrator/b1.py"]
        )

    def test_critere31_rien_n_a_change(self, tmp_path, page):
        racine = poser_depot_essai_etendu(tmp_path / "e")
        lancer_carte(racine)
        res = lancer_carte(racine)
        assert res.returncode == 0, res.stdout + res.stderr
        vue = _etat_depuis(page, racine / "docs/carte/index.html")
        expect(vue.locator(".depuis-etat")).to_have_text(
            "Rien n'a changé depuis la dernière carte."
        )
