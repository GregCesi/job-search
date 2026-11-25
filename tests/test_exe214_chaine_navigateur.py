"""Tests EXE-214 — navigateur réel (Playwright/Chromium, H8) sur la page de la
carte, ouverte depuis le disque, sans serveur et réseau coupé : routes, écrans,
tables, couches et appels directs à la base (critères 1 à 4, 6 à 11, 14, 15,
18 à 21, 23 à 26).

Ni le front ni l'API ne sont lancés. La page est générée dans un dossier
temporaire, par la commande lancée en sous-processus (`tests/carte_terrains.py`).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.carte_terrains import (
    PAS_DE_PHRASE,
    REPO,
    fichiers_front_du_disque,
    lancer_carte,
    poser_depot_essai_etendu,
)

GET_CHOSE = "GET /choses/{chose_id}"
DELETE_CHOSE = "DELETE /choses/{chose_id}"


@pytest.fixture(scope="module")
def page_vraie(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("chaine_vraie_nav") / "index.html"
    res = lancer_carte(REPO, sortie)
    assert res.returncode == 0, res.stdout + res.stderr
    return sortie


@pytest.fixture(scope="module")
def page_essai(tmp_path_factory):
    racine = poser_depot_essai_etendu(tmp_path_factory.mktemp("chaine_nav") / "e")
    res = lancer_carte(racine)
    assert res.returncode == 0, res.stdout + res.stderr
    return racine / "docs" / "carte" / "index.html"


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


def _aller(page, ancre):
    page.evaluate("a => { location.hash = a }", ancre)


def _ancre_route(route_id):
    return "#/route/" + route_id.replace(" ", "%20")


def _section(page, titre):
    entete = page.get_by_role("heading", name=re.compile("^" + re.escape(titre) + " "))
    return page.locator("#vue section.liens", has=entete)


def _vue(page):
    return page.locator("#vue")


class TestLesRoutes:
    def test_critere1_routes_du_fichier_d_api(self, page_essai, page):
        _ouvrir(page, page_essai, "#/fichier/api/choses.py")
        routes = _section(page, "Routes qu'il déclare")
        expect(routes.locator("li")).to_have_count(2)
        expect(routes.locator("li", has_text=GET_CHOSE)).to_contain_text("lire_chose")
        expect(routes.locator("li", has_text=DELETE_CHOSE)).to_contain_text(
            "supprimer_chose"
        )

    def test_critere2_recherche_d_une_route(self, page_essai, page):
        _ouvrir(page, page_essai)
        page.get_by_role("searchbox", name="Rechercher").fill("/choses")
        page.locator("#resultats").get_by_role("link", name=GET_CHOSE).click()
        expect(page.locator("#vue h2.route")).to_have_text(GET_CHOSE)

    def test_critere3_fichier_et_fonction_qui_la_servent(self, page_essai, page):
        _ouvrir(page, page_essai, _ancre_route(GET_CHOSE))
        servie = page.locator("#vue .servie-par")
        expect(servie).to_contain_text("api/choses.py")
        expect(servie).to_contain_text("lire_chose")
        servie.get_by_role("link", name="api/choses.py").click()
        expect(page.locator("#vue h2.chemin")).to_have_text("api/choses.py")

    def test_critere4_acces_a_la_base(self, page_essai, page):
        _ouvrir(page, page_essai, _ancre_route(GET_CHOSE))
        expect(page.locator("#vue .acces-base")).to_have_text(
            "Accès à la base : délègue"
        )
        _aller(page, _ancre_route(DELETE_CHOSE))
        expect(page.locator("#vue h2.route")).to_have_text(DELETE_CHOSE)
        expect(page.locator("#vue .acces-base")).to_have_text(
            "Accès à la base : base directe"
        )


class TestLesEcrans:
    def test_critere6_systeme_ecrans(self, page_vraie, page):
        _ouvrir(page, page_vraie)
        page.locator("article.systeme").get_by_role("link", name="Écrans").click()
        expect(_vue(page).locator("li.fichier")).to_have_count(
            len(fichiers_front_du_disque(REPO))
        )

    def test_critere7_chaque_ecran_a_sa_phrase(self, page_vraie, page):
        chemins = fichiers_front_du_disque(REPO)
        assert len(chemins) >= 30
        _ouvrir(page, page_vraie)
        sans = []
        for chemin in chemins:
            _aller(page, "#/fichier/" + chemin)
            expect(page.locator("#vue h2.chemin")).to_have_text(chemin)
            texte = page.locator("#vue .phrase").inner_text().strip()
            if not texte or texte == PAS_DE_PHRASE:
                sans.append(chemin)
        assert sans == []

    def test_critere8_route_appelee_par_le_store(self, page_essai, page):
        _ouvrir(page, page_essai, "#/fichier/web/app/stores/choses.ts")
        expect(_section(page, "Routes qu'il appelle").locator("li")).to_have_text(
            [re.compile(re.escape(GET_CHOSE))]
        )

    def test_critere9_appelee_par(self, page_essai, page):
        _ouvrir(page, page_essai, _ancre_route(GET_CHOSE))
        expect(_section(page, "Appelée par")).to_contain_text(
            "web/app/stores/choses.ts"
        )

    def test_critere10_store_et_composant_de_la_page(self, page_essai, page):
        _ouvrir(page, page_essai, "#/fichier/web/app/pages/choses.vue")
        _section(page, "Stores qu'il importe").get_by_role(
            "link", name="web/app/stores/choses.ts"
        ).click()
        expect(page.locator("#vue h2.chemin")).to_have_text("web/app/stores/choses.ts")
        page.go_back()
        expect(page.locator("#vue h2.chemin")).to_have_text("web/app/pages/choses.vue")
        _section(page, "Composants qu'il utilise").get_by_role(
            "link", name="web/app/components/ChoseCarte.vue"
        ).click()
        expect(page.locator("#vue h2.chemin")).to_have_text(
            "web/app/components/ChoseCarte.vue"
        )

    def test_critere11_route_sans_appel(self, page_essai, page):
        _ouvrir(page, page_essai, _ancre_route(DELETE_CHOSE))
        expect(_section(page, "Appelée par")).to_contain_text(
            "Aucun appel trouvé dans le front."
        )

    def test_critere14_vue_a_verifier(self, page_essai, page):
        _ouvrir(page, page_essai)
        page.get_by_role("link", name="À vérifier").first.click()
        expect(_section(page, "Appel sans route trouvée")).to_contain_text(
            "${base}/inconnu"
        )
        expect(_section(page, "Adresse illisible")).to_contain_text(
            "${props.adresse}/suite"
        )
        expect(_section(page, "Aucun appel trouvé dans le front")).to_contain_text(
            DELETE_CHOSE
        )
        expect(
            _section(page, "Aucun appel trouvé dans le front").locator("li")
        ).to_have_count(1)

    def test_critere15_la_page_d_une_offre_appelle_geste(self, page_vraie, page):
        _ouvrir(page, page_vraie, "#/fichier/web/app/pages/offers/[id].vue")
        expect(page.locator("#vue h2.chemin")).to_have_text(
            "web/app/pages/offers/[id].vue"
        )
        expect(
            _section(page, "Routes qu'il appelle").get_by_role(
                "link", name="POST /offers/{offer_id}/geste", exact=True
            )
        ).to_be_visible()


class TestLesTables:
    def test_critere16_liste_des_tables(self, page_essai, page):
        _ouvrir(page, page_essai)
        page.get_by_role("link", name="Tables").first.click()
        expect(_vue(page).locator("li.table")).to_have_count(1)
        expect(_vue(page).locator("li.table")).to_contain_text("choses")

    def test_critere18_le_metier_de_a_lit_choses(self, page_essai, page):
        _ouvrir(page, page_essai, "#/fichier/orchestrator/a_metier.py")
        expect(_section(page, "Tables qu'il lit").locator("li")).to_have_text(
            ["choses"]
        )

    def test_critere19_le_stockage_ecrit_choses(self, page_essai, page):
        _ouvrir(page, page_essai, "#/fichier/orchestrator/storage/choses.py")
        expect(_section(page, "Tables qu'il écrit").locator("li")).to_have_text(
            ["choses"]
        )

    def test_critere20_lecteurs_et_ecrivains_avec_systeme(self, page_essai, page):
        _ouvrir(page, page_essai, "#/table/choses")
        lisent = _section(page, "Fichiers qui la lisent")
        expect(lisent.locator("li")).to_have_text(
            [re.compile(r"orchestrator/a_metier\.py.*Système A")]
        )
        ecrivent = _section(page, "Fichiers qui l'écrivent")
        expect(ecrivent.locator("li")).to_have_text(
            [
                re.compile(r"api/choses\.py.*Système A"),
                re.compile(r"orchestrator/b_choses\.py.*Système B"),
                re.compile(r"orchestrator/storage/choses\.py.*Système A"),
            ]
        )

    def test_critere21_systemes_qui_ecrivent(self, page_essai, page):
        _ouvrir(page, page_essai, "#/table/choses")
        expect(page.locator("#vue .ecrivains")).to_have_text(
            "2 systèmes écrivent cette table"
        )

    def test_critere22_table_illisible_dans_a_verifier(self, page_essai, page):
        _ouvrir(page, page_essai, "#/a-verifier")
        expect(_section(page, "Table illisible")).to_contain_text(
            "orchestrator/b_choses.py:9"
        )

    def test_critere23_cvs_ecrite_par_le_service_du_cv(self, page_vraie, page):
        _ouvrir(page, page_vraie, "#/table/cvs")
        expect(page.locator("#vue h2.table")).to_have_text("cvs")
        expect(
            _section(page, "Fichiers qui l'écrivent").get_by_role(
                "link", name="orchestrator/job_search/cv/service.py"
            )
        ).to_be_visible()


class TestLesCouchesEtLaBase:
    @pytest.mark.parametrize(
        "chemin, couche, appels",
        [
            ("api/choses.py", "route", 1),
            ("orchestrator/a_metier.py", "métier", 1),
            ("orchestrator/storage/choses.py", "stockage", 2),
            ("orchestrator/b_choses.py", "métier", 2),
            ("api/a2.py", "métier", 0),
        ],
    )
    def test_criteres24_25_couche_et_appels(
        self, page_essai, page, chemin, couche, appels
    ):
        _ouvrir(page, page_essai, "#/fichier/" + chemin)
        expect(page.locator("#vue .couche")).to_have_text(f"Couche : {couche}")
        expect(page.locator("#vue .appels-base")).to_have_text(
            f"Appels directs à la base : {appels}"
        )

    def test_critere26_accueil(self, page_essai, page):
        _ouvrir(page, page_essai)
        expect(page.locator("#vue .total-base")).to_have_text(
            "4 appels directs à la base hors stockage, dans 3 fichiers"
        )
        expect(page.locator("#vue ol.base-fichiers li")).to_have_text(
            [
                re.compile(r"orchestrator/b_choses\.py.*2"),
                re.compile(r"api/choses\.py.*1"),
                re.compile(r"orchestrator/a_metier\.py.*1"),
            ]
        )
