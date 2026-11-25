"""Tests EXE-216 — la carte dessinée, dans un vrai Chromium (Playwright, H8) :
page ouverte depuis le disque, sans serveur, fenêtre de 1440 sur 900, sur le
vrai dépôt ou sur le dépôt d'essai étendu (critères 1 à 51).

Les tests lisent le dessin par ses attributs (`data-bloc`, `data-systeme`,
`data-fichier`, `data-de`…), les positions par les boîtes, les couleurs et
opacités par le style calculé.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect, sync_playwright

from tests.carte_navigateur import (
    aller,
    attendre_dessin,
    bloc,
    boite,
    cliquer_coin,
    fleche,
    niveau,
    ouvrir,
    panneau,
    section,
    style,
)
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
PAIRES = {
    ("ecrans", "api"),
    ("api", "coeur"),
    ("api", "base"),
    ("coeur", "base"),
    ("coeur", "modeles"),
    ("coeur", "sources"),
    ("coeur", "profils"),
}
SERVICE_CV = "orchestrator/job_search/cv/service.py"
SKILLS_CV = "orchestrator/job_search/cv/skills.py"
RETENIR = "Je retiens une offre : son CV est généré et rangé en base"
GET_CHOSE = "GET /choses/{chose_id}"


@pytest.fixture(scope="module")
def vraie(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("dessin_vrai")
    sortie = dossier / "page" / "index.html"
    res = lancer_carte(REPO, sortie, dossier / "graphe.json")
    assert res.returncode == 0, res.stdout + res.stderr
    return sortie


@pytest.fixture(scope="module")
def essai(tmp_path_factory):
    racine = poser_depot_essai_etendu(tmp_path_factory.mktemp("dessin_essai") / "e")
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
def erreurs():
    return []


def _contexte(navigateur, erreurs, **options):
    contexte = navigateur.new_context(
        offline=True, viewport={"width": 1440, "height": 900}, **options
    )
    onglet = contexte.new_page()
    onglet.on(
        "console", lambda m: erreurs.append(m.text) if m.type == "error" else None
    )
    onglet.on("pageerror", lambda e: erreurs.append(str(e)))
    return contexte, onglet


@pytest.fixture
def page(navigateur, erreurs):
    contexte, onglet = _contexte(navigateur, erreurs)
    yield onglet
    contexte.close()
    assert erreurs == []


def _donnees(sortie):
    return lire_donnees(sortie)


# ── La page ──────────────────────────────────────────────────────────────────


class TestLaPage:
    def test_critere1_trois_zones(self, vraie, page):
        ouvrir(page, vraie)
        entete = page.locator("header")
        expect(entete.locator("h1")).to_be_visible()
        expect(entete.locator("nav.onglets a")).to_have_count(4)
        expect(entete.get_by_role("searchbox")).to_be_visible()
        d, p = boite(page.locator("#dessin")), boite(panneau(page))
        h = boite(entete)
        assert d["y"] >= h["y"] + h["height"] and p["y"] >= h["y"] + h["height"]
        assert d["x"] + d["width"] <= p["x"]
        assert d["y"] < p["y"] + p["height"] and p["y"] < d["y"] + d["height"]

    def test_critere2_quatre_onglets_et_l_onglet_actif(self, vraie, page):
        ouvrir(page, vraie)
        onglets = page.locator("nav.onglets a")
        expect(onglets).to_have_text(
            ["La carte", "La base", "À vérifier", "Depuis la dernière carte"]
        )
        for i, ancre in enumerate(["#/", "#/base", "#/a-verifier", "#/depuis"]):
            aller(page, ancre)
            expect(onglets.nth(i)).to_have_attribute("aria-current", "page")
            fonds = [style(onglets.nth(j), "backgroundColor") for j in range(4)]
            autres = [f for j, f in enumerate(fonds) if j != i]
            assert all(f != fonds[i] for f in autres), fonds

    def test_critere3_fil_d_ariane_et_niveau(self, vraie, page):
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        ariane = page.get_by_role("navigation", name="Fil d'Ariane")
        expect(ariane).to_contain_text("niveau 4 sur 4")
        expect(ariane.get_by_role("link")).to_have_text(
            ["La carte", "Les systèmes", "CV", SERVICE_CV]
        )
        ariane.get_by_role("link", name="CV", exact=True).click()
        expect(ariane).to_contain_text("niveau 3 sur 4")
        ariane.get_by_role("link", name="Les systèmes").click()
        expect(ariane).to_contain_text("niveau 2 sur 4")
        ariane.get_by_role("link", name="La carte").click()
        expect(ariane).to_contain_text("niveau 1 sur 4")

    def test_critere4_theme_sombre(self, vraie, navigateur, erreurs):
        contexte, onglet = _contexte(navigateur, erreurs, color_scheme="dark")
        try:
            ouvrir(onglet, vraie)
            fond = style(onglet.locator("body"), "backgroundColor")
            texte = style(onglet.locator("body"), "color")
        finally:
            contexte.close()

        def clarte(rgb):
            r, g, b = (int(x) for x in re.findall(r"\d+", rgb)[:3])
            return (r + g + b) / 3

        assert clarte(fond) < 60 and clarte(texte) > 180, (fond, texte)

    def test_critere5_un_fichier_hors_ligne_sans_erreur(self, vraie, page):
        requetes = []
        page.on(
            "request",
            lambda r: (
                None
                if r.url.startswith(("file:", "data:", "about:"))
                else requetes.append(r.url)
            ),
        )
        vues = [
            "#/",
            "#/systemes",
            "#/systeme/cv",
            "#/systeme/ecrans",
            "#/fichier/" + SERVICE_CV,
            "#/fichier/web/app/pages/offers/[id].vue",
            "#/route/" + "POST /offers/{offer_id}/geste".replace(" ", "%20"),
            "#/tables",
            "#/table/cvs",
            "#/base",
            "#/a-verifier",
            "#/depuis",
        ]
        ouvrir(page, vraie)
        for v in vues:
            aller(page, v)
            page.wait_for_timeout(50)
        aller(page, "#/systemes")
        bloc(page, "data-systeme", "cv").hover()
        page.get_by_role("button", name=RETENIR).click()
        page.get_by_role("button", name="Après").click()
        assert requetes == []
        assert [p.name for p in vraie.parent.iterdir()] == ["index.html"]
        externe = r"<(script|link)[^>]+(src|href)=\"https?:"
        assert re.search(externe, vraie.read_text(encoding="utf-8")) is None


# ── Niveau 1 ─────────────────────────────────────────────────────────────────


class TestNiveau1:
    def test_critere6_sept_blocs(self, vraie, page):
        ouvrir(page, vraie)
        attendre_dessin(page, "vue d'ensemble")
        noms = page.locator("#dessin g.bloc[data-bloc] text.nom")
        expect(noms).to_have_count(7)
        assert sorted(n.get_attribute("data-nom") for n in noms.all()) == sorted(BLOCS)

    def test_critere7_sept_fleches_avec_libelle_court_le_long_du_trait(
        self, vraie, page
    ):
        courts = {
            (f["de"], f["vers"]): f["court"]
            for f in _donnees(vraie)["ensemble"]["fleches"]
        }
        ouvrir(page, vraie)
        traits = page.locator("#dessin path.fl[data-de]")
        expect(traits).to_have_count(7)
        lues = {
            (t.get_attribute("data-de"), t.get_attribute("data-vers"))
            for t in traits.all()
        }
        assert lues == PAIRES
        for de, vers in PAIRES:
            court = courts[(de, vers)]
            assert court and len(court.split()) <= 3, court
            etiq = page.locator(
                f'#dessin text.etiq-court[data-de="{de}"][data-vers="{vers}"]'
            )
            expect(etiq).to_have_text(court)
            milieu = fleche(page, de, vers).evaluate(
                "p => { const l = p.getTotalLength(), m = p.getPointAtLength(l / 2),"
                " r = p.ownerSVGElement.getBoundingClientRect(),"
                " k = r.width / p.ownerSVGElement.viewBox.baseVal.width;"
                " return { x: r.x + m.x * k, y: r.y + m.y * k }; }"
            )
            b = boite(etiq)
            cx, cy = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
            assert abs(cx - milieu["x"]) < 30 and abs(cy - milieu["y"]) < 30, (de, vers)

    def test_critere8_ecrans_api_coeur_base_sur_une_ligne(self, vraie, page):
        ouvrir(page, vraie)
        boites = [
            boite(bloc(page, "data-bloc", b))
            for b in ("ecrans", "api", "coeur", "base")
        ]
        assert len({round(b["y"]) for b in boites}) == 1
        xs = [b["x"] for b in boites]
        assert xs == sorted(xs) and len(set(xs)) == 4

    def test_critere9_clic_dans_un_coin_du_bloc_api(self, vraie, page):
        ouvrir(page, vraie)
        cliquer_coin(page, bloc(page, "data-bloc", "api"))
        attendre_dessin(page, "les systèmes")
        assert niveau(page) == "2"

    def test_critere10_ecrans_et_base(self, vraie, page):
        ouvrir(page, vraie)
        cliquer_coin(page, bloc(page, "data-bloc", "ecrans"), "bas-droite")
        attendre_dessin(page, "le système Écrans")
        expect(page.locator("#dessin g.bloc[data-fichier]")).to_have_count(
            len(_donnees(vraie)["fichiers_front"])
        )
        aller(page, "#/")
        cliquer_coin(page, bloc(page, "data-bloc", "base"))
        attendre_dessin(page, "les tables")
        expect(page.locator("#dessin g.bloc[data-table]")).to_have_count(
            len(_donnees(vraie)["tables"])
        )

    def test_critere11_survol_d_un_bloc(self, vraie, page):
        role = next(
            b["role"]
            for b in _donnees(vraie)["ensemble"]["blocs"]
            if b["id"] == "modeles"
        )
        ouvrir(page, vraie)
        expect(panneau(page).locator(".accueil")).to_be_visible()
        bloc(page, "data-bloc", "modeles").hover()
        expect(panneau(page).locator("h2")).to_have_text("Modèles")
        expect(panneau(page).locator(".role")).to_have_text(role)
        page.mouse.move(2, 2)
        expect(panneau(page).locator(".accueil")).to_be_visible()

    def test_critere12_survol_d_une_fleche_ou_de_son_libelle(self, vraie, page):
        longs = {
            (f["de"], f["vers"]): f["libelle"]
            for f in _donnees(vraie)["ensemble"]["fleches"]
        }
        ouvrir(page, vraie)
        page.locator(
            '#dessin text.etiq-court[data-de="coeur"][data-vers="modeles"]'
        ).hover()
        expect(panneau(page).locator(".libelle-long")).to_have_text(
            longs[("coeur", "modeles")]
        )
        page.mouse.move(2, 2)
        expect(panneau(page).locator(".accueil")).to_be_visible()
        point = fleche(page, "ecrans", "api").evaluate(
            "p => { const l = p.getTotalLength(), m = p.getPointAtLength(l * 0.3),"
            " r = p.ownerSVGElement.getBoundingClientRect(),"
            " k = r.width / p.ownerSVGElement.viewBox.baseVal.width;"
            " return { x: r.x + m.x * k, y: r.y + m.y * k }; }"
        )
        page.mouse.move(point["x"], point["y"])
        expect(panneau(page).locator(".libelle-long")).to_have_text(
            longs[("ecrans", "api")]
        )

    def test_critere13_texte_d_accueil(self, vraie, page):
        d = _donnees(vraie)
        ouvrir(page, vraie)
        accueil = panneau(page).locator(".accueil")
        expect(accueil.locator("p").first).to_contain_text("Cette carte")
        expect(accueil.locator("ol.niveaux li")).to_have_count(4)
        expect(accueil).to_contain_text(d["genere_le"])
        expect(accueil).to_contain_text(d["commit"])
        expect(accueil.locator("code")).to_contain_text("python -m outils.carte")
        expect(accueil.locator(".total-base")).to_contain_text(
            f"{d['base']['hors_stockage']} appels directs à la base hors stockage"
        )


# ── Niveau 2 ─────────────────────────────────────────────────────────────────


class TestNiveau2:
    def test_critere14_un_bloc_par_systeme(self, vraie, page):
        d = _donnees(vraie)
        attendus = [d["ecrans"]] + d["systemes"] + ([1] if d["autres"] else [])
        assert len(attendus) == 17
        ouvrir(page, vraie, "#/systemes")
        blocs = page.locator("#dessin g.bloc[data-systeme]")
        expect(blocs).to_have_count(len(attendus))
        for s in [d["ecrans"]] + d["systemes"]:
            b = bloc(page, "data-systeme", s["id"])
            expect(b.locator("text.nom")).to_have_attribute("data-nom", s["nom"])
            n = len(s["fichiers"])
            expect(b).to_contain_text(f"{n} fichier" + ("s" if n > 1 else ""))

    def test_critere15_une_couleur_par_systeme(self, vraie, page):
        ouvrir(page, vraie, "#/systemes")
        fonds = [
            style(r, "fill")
            for r in page.locator("#dessin g.bloc[data-systeme] rect.fond").all()
        ]
        assert len(fonds) == 17 and len(set(fonds)) == 17

    def test_critere16_fleche_de_a_vers_b_seulement(self, essai, page):
        ouvrir(page, essai, "#/systemes")
        expect(fleche(page, "a", "b")).to_have_count(1)
        expect(fleche(page, "b", "a")).to_have_count(0)

    def test_critere17_fleche_d_ecrans_vers_a(self, essai, page):
        ouvrir(page, essai, "#/systemes")
        expect(fleche(page, "ecrans", "a")).to_have_count(1)

    def test_critere18_epaisseur_selon_les_imports(self, vraie, page):
        fl = _donnees(vraie)["fleches"]
        haut, bas = max(fl, key=lambda f: f["n"]), min(fl, key=lambda f: f["n"])
        assert haut["n"] > bas["n"]
        ouvrir(page, vraie, "#/systemes")
        e_haut = float(
            style(fleche(page, haut["de"], haut["vers"]), "strokeWidth").rstrip("px")
        )
        e_bas = float(
            style(fleche(page, bas["de"], bas["vers"]), "strokeWidth").rstrip("px")
        )
        assert e_haut > e_bas

    def test_critere19_survol_colore_et_estompe(self, vraie, page):
        ouvrir(page, vraie, "#/systemes")
        bloc(page, "data-systeme", "cv").hover()
        sortantes = page.locator('#dessin path.fl[data-de="cv"]')
        entrantes = page.locator('#dessin path.fl[data-vers="cv"]')
        autres = page.locator(
            '#dessin path.fl:not([data-de="cv"]):not([data-vers="cv"])'
        )
        expect(sortantes.first).to_have_class(re.compile(r"\bsort\b"))
        c_sort = {style(t, "stroke") for t in sortantes.all()}
        c_entre = {style(t, "stroke") for t in entrantes.all()}
        assert len(c_sort) == 1 and len(c_entre) == 1 and c_sort != c_entre
        assert all(float(style(t, "opacity")) < 0.2 for t in autres.all())
        assert float(style(sortantes.first, "opacity")) > 0.8

    def test_critere20_panneau_pendant_le_survol(self, vraie, page):
        cv = next(s for s in _donnees(vraie)["systemes"] if s["id"] == "cv")
        ouvrir(page, vraie, "#/systemes")
        bloc(page, "data-systeme", "cv").hover()
        expect(panneau(page).locator("h2")).to_have_text("CV")
        expect(panneau(page).locator(".role")).to_have_text(cv["role"])
        expect(section(page, "Ses fichiers").locator("li")).to_have_count(
            len(cv["fichiers"])
        )

    def test_critere21_clic_n_importe_ou_dans_le_bloc(self, vraie, page):
        ouvrir(page, vraie, "#/systemes")
        cliquer_coin(page, bloc(page, "data-systeme", "lettre"), "bas-droite")
        attendre_dessin(page, "le système Lettre de motivation")
        assert niveau(page) == "3"

    def test_critere22_panneau_sans_survol(self, vraie, page):
        ouvrir(page, vraie, "#/systemes")
        expect(panneau(page)).to_contain_text("Une flèche de A vers B")
        traits = panneau(page).locator(".legende i")
        expect(traits).to_have_count(2)
        assert style(traits.nth(0), "backgroundColor") != style(
            traits.nth(1), "backgroundColor"
        )
        liste = panneau(page).locator("ul.liste-systemes li a")
        expect(liste).to_have_count(17)
        liste.filter(has_text="Fiche entreprise").click()
        attendre_dessin(page, "le système Fiche entreprise")


# ── Niveau 3 ─────────────────────────────────────────────────────────────────


class TestNiveau3:
    def test_critere23_les_8_fichiers_du_cv(self, vraie, page):
        ouvrir(page, vraie, "#/systeme/cv")
        expect(page.locator("#dessin g.bloc[data-fichier]")).to_have_count(8)

    def test_critere24_service_au_dessus_de_skills(self, vraie, page):
        ouvrir(page, vraie, "#/systeme/cv")
        haut = boite(bloc(page, "data-fichier", SERVICE_CV))
        bas = boite(bloc(page, "data-fichier", SKILLS_CV))
        assert haut["y"] + haut["height"] <= bas["y"]
        expect(fleche(page, SERVICE_CV, SKILLS_CV)).to_have_count(1)

    def test_critere25_nom_lignes_et_couche(self, vraie, page):
        d = _donnees(vraie)["fichiers"]
        ouvrir(page, vraie, "#/systeme/cv")
        blocs = page.locator("#dessin g.bloc[data-fichier]")
        expect(blocs).to_have_count(8)
        for g in blocs.all():
            c = g.get_attribute("data-fichier")
            texte = g.text_content()
            assert c.split("/")[-1] in texte
            assert f"{d[c]['lignes']} lignes" in texte
            assert d[c]["couche"] in {"route", "métier", "stockage"}
            assert d[c]["couche"] in texte

    def test_critere26_pastille_des_appels_directs(self, vraie, page):
        d = _donnees(vraie)["fichiers"]
        ouvrir(page, vraie, "#/systeme/cv")
        avec = [c for c in d if d[c]["systeme"] == "cv" and d[c]["appels_base"]]
        sans = [c for c in d if d[c]["systeme"] == "cv" and not d[c]["appels_base"]]
        assert avec and sans
        for c in avec:
            expect(
                bloc(page, "data-fichier", c).locator(".pastille-base text")
            ).to_have_text(str(d[c]["appels_base"]))
        for c in sans:
            expect(
                bloc(page, "data-fichier", c).locator(".pastille-base")
            ).to_have_count(0)

    def test_critere27_colonnes_des_systemes_voisins(self, vraie, page):
        fl = _donnees(vraie)["fleches"]
        ouvrir(page, vraie, "#/systeme/cv")
        droite = page.locator('#dessin g.bloc[data-cote="droite"]')
        gauche = page.locator('#dessin g.bloc[data-cote="gauche"]')
        attendus_d = {f["vers"]: f["n"] for f in fl if f["de"] == "cv"}
        lus_d = {
            g.get_attribute("data-voisin"): int(g.get_attribute("data-n"))
            for g in droite.all()
        }
        assert lus_d == attendus_d
        lus_g = {g.get_attribute("data-voisin") for g in gauche.all()}
        assert {f["de"] for f in fl if f["vers"] == "cv"} | {"ecrans"} == lus_g
        assert (
            boite(gauche.first)["x"]
            < boite(bloc(page, "data-fichier", SERVICE_CV))["x"]
        )
        assert (
            boite(droite.first)["x"]
            > boite(bloc(page, "data-fichier", SERVICE_CV))["x"]
        )
        expect(gauche.first).to_contain_text(re.compile(r"\(\d+\)"))
        cliquer_coin(page, droite.filter(has_text="Pièces et PDF"))
        attendre_dessin(page, "le système Pièces et PDF")

    def test_critere28_survol_d_un_fichier(self, vraie, page):
        ouvrir(page, vraie, "#/systeme/cv")
        bloc(page, "data-fichier", SERVICE_CV).hover()
        expect(fleche(page, SERVICE_CV, SKILLS_CV)).to_have_class(
            re.compile(r"\bsort\b")
        )
        expect(fleche(page, "api/cv.py", SERVICE_CV)).to_have_class(
            re.compile(r"\bentre\b")
        )
        expect(panneau(page).locator("h2.chemin")).to_have_text(SERVICE_CV)

    def test_critere29_clic_sur_un_fichier(self, vraie, page):
        ouvrir(page, vraie, "#/systeme/cv")
        cliquer_coin(page, bloc(page, "data-fichier", SKILLS_CV))
        attendre_dessin(page, "le fichier " + SKILLS_CV)
        assert niveau(page) == "4"

    def test_critere30_panneau_du_systeme(self, vraie, page):
        cv = next(s for s in _donnees(vraie)["systemes"] if s["id"] == "cv")
        ouvrir(page, vraie, "#/systeme/cv")
        expect(panneau(page).locator(".role")).to_have_text(cv["role"])
        expect(section(page, "Ses fichiers").locator("li")).to_have_count(8)
        expect(section(page, "Ses routes")).to_contain_text("/cv")
        expect(section(page, "Les tables qu'il écrit")).to_contain_text("cvs")
        expect(section(page, "Il utilise")).to_contain_text("Pièces et PDF")
        expect(section(page, "Il est utilisé par")).to_contain_text("Écrans")

    def test_critere31_le_systeme_ecrans(self, essai, page):
        ouvrir(page, essai, "#/systeme/ecrans")
        expect(page.locator("#dessin g.bloc[data-fichier]")).to_have_count(4)
        expect(
            fleche(page, "web/app/pages/choses.vue", "web/app/stores/choses.ts")
        ).to_have_count(1)
        expect(
            fleche(
                page, "web/app/pages/choses.vue", "web/app/components/ChoseCarte.vue"
            )
        ).to_have_count(1)


# ── Niveau 4 ─────────────────────────────────────────────────────────────────


class TestNiveau4:
    def test_critere32_le_fichier_au_centre(self, vraie, page):
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        centre = boite(page.locator("#dessin g.bloc.centre"))
        gauche = page.locator(
            '#dessin g.groupe[data-cote="gauche"][data-groupe-systeme]'
        )
        droite = page.locator(
            '#dessin g.groupe[data-cote="droite"][data-groupe-systeme]'
        )
        expect(gauche).to_have_count(2)
        expect(droite).to_have_count(3)
        for g in gauche.all():
            assert boite(g)["x"] + boite(g)["width"] < centre["x"]
            titre = g.get_attribute("data-groupe-systeme")
            expect(
                page.locator(
                    f'#dessin path.fl[data-vers="centre"][data-de="{g.locator(".titre-groupe").text_content()}"]'
                )
            ).to_have_count(1)
            assert titre
        for g in droite.all():
            assert boite(g)["x"] > centre["x"] + centre["width"]
            expect(
                page.locator(
                    f'#dessin path.fl[data-de="centre"][data-vers="{g.locator(".titre-groupe").text_content()}"]'
                )
            ).to_have_count(1)

    def test_critere33_service_du_cv(self, vraie, page):
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        expect(
            page.locator(
                f'#dessin g.groupe[data-cote="droite"] [data-fichier="{SKILLS_CV}"]'
            )
        ).to_have_count(1)
        expect(
            page.locator(
                '#dessin g.groupe[data-cote="gauche"] [data-fichier="api/cv.py"]'
            )
        ).to_have_count(1)

    def test_critere34_tables_lues_et_ecrites(self, vraie, page):
        f = _donnees(vraie)["fichiers"][SERVICE_CV]
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        lues = page.locator('#dessin [data-acces="lit"]')
        ecrites = page.locator('#dessin [data-acces="ecrit"]')
        expect(lues).to_have_text(f["tables_lues"])
        expect(ecrites).to_have_text(f["tables_ecrites"])
        t_lit = page.locator("#dessin path.fl.lit")
        t_ecrit = page.locator("#dessin path.fl.ecrit")
        expect(t_lit).to_have_count(1)
        expect(t_ecrit).to_have_count(1)
        assert (style(t_lit, "stroke"), style(t_lit, "strokeDasharray")) != (
            style(t_ecrit, "stroke"),
            style(t_ecrit, "strokeDasharray"),
        )

    def test_critere35_clic_sur_un_nom_du_dessin(self, vraie, page):
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        page.locator(f'#dessin text.lignef[data-fichier="{SKILLS_CV}"]').click()
        attendre_dessin(page, "le fichier " + SKILLS_CV)
        page.go_back()
        page.locator(
            '#dessin g.groupe[data-groupe-systeme="socle"] .titre-groupe'
        ).click()
        attendre_dessin(page, "le système Socle")
        page.go_back()
        page.locator('#dessin text.lignef[data-acces="ecrit"]', has_text="cvs").click()
        attendre_dessin(page, "la table cvs")

    def test_critere36_le_panneau_du_fichier(self, vraie, page):
        f = _donnees(vraie)["fichiers"][SERVICE_CV]
        ouvrir(page, vraie, "#/fichier/" + SERVICE_CV)
        p = panneau(page)
        expect(p.locator("h2.chemin")).to_have_text(SERVICE_CV)
        expect(p.locator(".phrase")).to_have_text(f["phrase"])
        expect(p.locator(".systeme-du-fichier")).to_contain_text("CV")
        expect(p.locator(".lignes")).to_have_text(f"{f['lignes']} lignes")
        expect(p.locator(".couche")).to_have_text("Couche : métier")
        expect(p.locator(".appels-base")).to_have_text(
            f"Appels directs à la base : {f['appels_base']}"
        )
        for titre, n in [
            ("Routes qu'il déclare", len(f["routes"])),
            ("Tables qu'il lit", len(f["tables_lues"])),
            ("Tables qu'il écrit", len(f["tables_ecrites"])),
            ("Les tests qui l'importent", len(f["tests"])),
            ("Ce qu'il importe", len(f["importe"])),
            ("Qui l'importe", len(f["importe_par"])),
        ]:
            expect(section(page, titre).locator("h3")).to_have_text(f"{titre} ({n})")
        expect(section(page, "Parcours qui passent par lui")).to_contain_text(RETENIR)


# ── Routes et tables ─────────────────────────────────────────────────────────


class TestRoutesEtTables:
    def test_critere37_la_route(self, essai, page):
        ouvrir(page, essai, "#/route/" + GET_CHOSE.replace(" ", "%20"))
        centre = boite(page.locator("#dessin g.bloc.centre"))
        appelant = page.locator(
            '#dessin g.groupe[data-cote="gauche"] [data-fichier="web/app/stores/choses.ts"]'
        )
        servant = page.locator(
            '#dessin g.groupe[data-cote="droite"] [data-fichier="api/choses.py"]'
        )
        assert boite(appelant)["x"] < centre["x"] < boite(servant)["x"]
        expect(page.locator("#dessin g.bloc.centre")).to_contain_text(GET_CHOSE)
        p = panneau(page)
        expect(p.locator(".methode")).to_have_text("Méthode : GET")
        expect(p.locator(".chemin-route")).to_have_text("Chemin : /choses/{chose_id}")
        expect(p.locator(".servie-par")).to_contain_text("lire_chose")
        expect(p.locator(".acces-base")).to_have_text("Accès à la base : délègue")

    def test_critere38_la_table(self, essai, page):
        ouvrir(page, essai, "#/table/choses")
        centre = boite(page.locator("#dessin g.bloc.centre"))
        lecteur = page.locator(
            '#dessin g.groupe[data-cote="gauche"] [data-fichier="orchestrator/a_metier.py"]'
        )
        assert boite(lecteur)["x"] < centre["x"]
        ecrivains = page.locator('#dessin g.groupe[data-cote="droite"] [data-fichier]')
        expect(ecrivains).to_have_count(3)
        assert all(boite(e)["x"] > centre["x"] for e in ecrivains.all())
        expect(panneau(page).locator(".ecrivains")).to_have_text(
            "2 systèmes écrivent cette table"
        )

    def test_critere39_le_dessin_des_tables(self, vraie, page):
        tables = _donnees(vraie)["tables"]
        ouvrir(page, vraie)
        cliquer_coin(page, bloc(page, "data-bloc", "base"))
        attendre_dessin(page, "les tables")
        expect(page.locator("#dessin g.bloc[data-table]")).to_have_count(len(tables))
        expect(bloc(page, "data-table", "cvs")).to_contain_text(
            re.compile(r"\d+ systèmes? l'écri")
        )
        cliquer_coin(page, bloc(page, "data-table", "cvs"))
        attendre_dessin(page, "la table cvs")

    @pytest.mark.parametrize(
        "requete, nom, dessin_attendu",
        [
            ("skills", SKILLS_CV, "le fichier " + SKILLS_CV),
            ("Fiche entre", "Fiche entreprise", "le système Fiche entreprise"),
            ("/cv/titre", "GET /cv/titre-defaut", "la route GET /cv/titre-defaut"),
            ("cv_corr", "cv_corrections", "la table cv_corrections"),
        ],
    )
    def test_critere40_la_recherche(self, vraie, page, requete, nom, dessin_attendu):
        ouvrir(page, vraie)
        page.get_by_role("searchbox").fill(requete)
        page.locator("#resultats").get_by_role("link", name=nom, exact=True).click()
        attendre_dessin(page, dessin_attendu)


# ── Les parcours ─────────────────────────────────────────────────────────────


def _lancer(page, nom=RETENIR):
    page.locator("#parcours-barre").get_by_role("button", name=nom).click()
    attendre_dessin(page, "les systèmes")


def _systeme_de_l_etape(d, e):
    if e["genre"] == "table":
        return "base"
    if e["genre"] == "route":
        return d["fichiers"][d["routes"][e["element"]]["fichier"]]["systeme"]
    f = d["fichiers"].get(e["element"]) or d["fichiers_front"][e["element"]]
    return f["systeme"]


class TestParcours:
    def test_critere41_la_barre_a_chaque_niveau(self, vraie, page):
        noms = [p["nom"] for p in _donnees(vraie)["parcours"]]
        assert len(noms) == 4
        ouvrir(page, vraie)
        for ancre in ("#/", "#/systemes", "#/systeme/cv", "#/fichier/" + SERVICE_CV):
            aller(page, ancre)
            barre = page.locator("#parcours-barre")
            expect(barre).to_contain_text("Suivre un parcours")
            expect(barre.get_by_role("button")).to_have_text(noms)

    def test_critere42_halo_sur_le_systeme_de_l_etape_1(self, vraie, page):
        d = _donnees(vraie)
        premier = _systeme_de_l_etape(d, d["parcours"][0]["etapes"][0])
        ouvrir(page, vraie, "#/systeme/cv")
        _lancer(page)
        assert niveau(page) == "2"
        courant = bloc(page, "data-systeme", premier)
        expect(courant).to_have_class(re.compile(r"\bcourant\b"))
        assert style(courant.locator("rect.fond"), "filter") != "none"
        for g in page.locator("#dessin g.bloc[data-systeme]").all():
            if g.get_attribute("data-systeme") != premier:
                assert float(style(g, "opacity")) < 0.5

    def test_critere43_la_carte_d_etape(self, vraie, page):
        p = _donnees(vraie)["parcours"][0]
        e = p["etapes"][0]
        ouvrir(page, vraie)
        _lancer(page)
        carte = page.locator("#etape")
        assert boite(carte)["y"] < boite(page.locator("#dessin"))["y"]
        expect(carte.locator(".num")).to_have_text(f"Étape 1 sur {len(p['etapes'])}")
        expect(carte.locator(".element")).to_have_text(e["element"])
        expect(carte.locator(".couche-etape")).to_have_text(f"Couche : {e['couche']}")
        expect(carte.locator(".phrase-etape")).to_have_text(e["phrase"])
        expect(carte.get_by_role("button")).to_have_text(
            ["Avant", "Lecture", "Après", "Quitter"]
        )

    def test_critere44_apres_et_la_pastille_1(self, vraie, page):
        d = _donnees(vraie)
        premier = _systeme_de_l_etape(d, d["parcours"][0]["etapes"][0])
        ouvrir(page, vraie)
        _lancer(page)
        page.get_by_role("button", name="Après").click()
        expect(page.locator("#etape .num")).to_contain_text("Étape 2 sur")
        badge = page.locator("#dessin g.badge-etape").filter(has=page.locator("text"))
        boite_sys = boite(bloc(page, "data-systeme", premier))
        trouves = [
            b.get_attribute("data-etapes")
            for b in badge.all()
            if abs(boite(b)["y"] + boite(b)["height"] / 2 - boite_sys["y"]) < 15
            and boite_sys["x"] < boite(b)["x"] < boite_sys["x"] + boite_sys["width"]
        ]
        assert any("1" in t.split("·") for t in trouves), trouves

    def test_critere45_fleche_de_parcours_entre_deux_systemes(self, vraie, page):
        d = _donnees(vraie)
        etapes = d["parcours"][0]["etapes"]
        systemes = [_systeme_de_l_etape(d, e) for e in etapes]
        i = next(k for k in range(1, len(etapes)) if systemes[k] != systemes[k - 1])
        ouvrir(page, vraie)
        _lancer(page)
        for _ in range(i):
            page.get_by_role("button", name="Après").click()
        expect(
            page.locator(
                f'#dessin path.fl.parcours[data-de="{systemes[i - 1]}"][data-vers="{systemes[i]}"]'
            )
        ).to_have_count(1)

    def test_critere46_base_et_ecrans_s_allument(self, vraie, page):
        etapes = _donnees(vraie)["parcours"][0]["etapes"]
        assert (
            etapes[0]["element"].startswith("web/") and etapes[-1]["genre"] == "table"
        )
        ouvrir(page, vraie, "#/systemes")
        expect(bloc(page, "data-systeme", "base")).to_have_count(0)
        _lancer(page)
        expect(bloc(page, "data-systeme", "ecrans")).to_have_class(
            re.compile(r"\bcourant\b")
        )
        expect(bloc(page, "data-systeme", "base")).to_have_count(1)
        for _ in range(len(etapes) - 1):
            page.get_by_role("button", name="Après").click()
        expect(bloc(page, "data-systeme", "base")).to_have_class(
            re.compile(r"\bcourant\b")
        )

    def test_critere47_le_clavier(self, vraie, page):
        ouvrir(page, vraie)
        _lancer(page)
        page.keyboard.press("ArrowRight")
        expect(page.locator("#etape .num")).to_contain_text("Étape 2 sur")
        page.keyboard.press("ArrowLeft")
        expect(page.locator("#etape .num")).to_contain_text("Étape 1 sur")
        page.keyboard.press("Escape")
        expect(page.locator("#etape")).to_be_hidden()

    def test_critere48_lecture(self, vraie, navigateur, erreurs):
        n = len(_donnees(vraie)["parcours"][0]["etapes"])
        contexte, onglet = _contexte(navigateur, erreurs)
        try:
            onglet.clock.install()
            ouvrir(onglet, vraie)
            _lancer(onglet)
            onglet.get_by_role("button", name="Lecture").click()
            expect(
                onglet.locator("#etape").get_by_role("button", name="Pause")
            ).to_be_visible()
            expect(onglet.locator("#etape .num")).to_contain_text("Étape 2 sur")
            onglet.clock.run_for(2600 * (n + 1))
            expect(onglet.locator("#etape .num")).to_have_text(f"Étape {n} sur {n}")
            expect(
                onglet.locator("#etape").get_by_role("button", name="Lecture")
            ).to_be_visible()
        finally:
            contexte.close()
        assert erreurs == []

    def test_critere49_le_panneau_liste_les_etapes(self, vraie, page):
        n = len(_donnees(vraie)["parcours"][0]["etapes"])
        ouvrir(page, vraie)
        _lancer(page)
        etapes = panneau(page).locator("ol.etapes-parcours li")
        expect(etapes).to_have_count(n)
        assert int(style(etapes.nth(0), "fontWeight")) >= 600
        assert int(style(etapes.nth(1), "fontWeight")) < 600
        etapes.nth(2).click()
        expect(page.locator("#etape .num")).to_contain_text("Étape 3 sur")
        assert (
            int(
                style(
                    panneau(page).locator("ol.etapes-parcours li").nth(2), "fontWeight"
                )
            )
            >= 600
        )

    def test_critere50_l_element_s_ouvre_et_le_parcours_reste(self, vraie, page):
        e = _donnees(vraie)["parcours"][0]["etapes"][2]
        ouvrir(page, vraie)
        _lancer(page)
        page.get_by_role("button", name="Après").click()
        page.get_by_role("button", name="Après").click()
        page.locator("#etape .element").click()
        expect(panneau(page).locator("h2.chemin")).to_have_text(e["element"])
        expect(page.locator("#etape .num")).to_contain_text("Étape 3 sur")
        page.get_by_role("navigation", name="Fil d'Ariane").get_by_role(
            "link", name="Les systèmes"
        ).click()
        attendre_dessin(page, "les systèmes")
        expect(page.locator("#etape .num")).to_contain_text("Étape 3 sur")


# ── Les trois autres onglets ─────────────────────────────────────────────────


class TestOnglets:
    def test_critere51_la_base(self, vraie, page):
        d = _donnees(vraie)
        ouvrir(page, vraie)
        page.locator("nav.onglets").get_by_role("link", name="La base").click()
        vue = page.locator(".page")
        expect(vue.locator(".total-base")).to_contain_text(
            f"{d['base']['hors_stockage']} appels directs à la base hors stockage"
        )
        expect(vue.locator("ol.base-fichiers li a")).to_have_count(
            len(d["base"]["fichiers"])
        )
        expect(vue.locator("ul.tables li a")).to_have_count(len(d["tables"]))
        expect(vue.locator("ul.routes li a")).to_have_count(len(d["routes"]))
        vue.locator("ul.tables li a", has_text="cvs").first.click()
        attendre_dessin(page, "la table cvs")

    def test_critere51_a_verifier(self, essai, page):
        ouvrir(page, essai)
        page.locator("nav.onglets").get_by_role("link", name="À vérifier").click()
        expect(section(page, "Appel sans route trouvée", ".page")).to_contain_text(
            "${base}/inconnu"
        )
        expect(section(page, "Adresse illisible", ".page")).to_contain_text(
            "${props.adresse}/suite"
        )
        expect(
            section(page, "Aucun appel trouvé dans le front", ".page")
        ).to_contain_text("DELETE /choses/{chose_id}")
        expect(section(page, "Table illisible", ".page")).to_contain_text(
            "orchestrator/b_choses.py:9"
        )
        section(page, "Aucun appel trouvé dans le front", ".page").get_by_role(
            "link"
        ).click()
        attendre_dessin(page, "la route DELETE /choses/{chose_id}")

    def test_critere51_depuis(self, tmp_path, page):
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
        ouvrir(page, racine / "docs/carte/index.html")
        page.locator("nav.onglets").get_by_role(
            "link", name="Depuis la dernière carte"
        ).click()
        ligne = page.locator(".page ul.changements li", has_text="flèche disparue")
        expect(ligne).to_have_text("flèche disparue : api/a1.py → orchestrator/b1.py")
        ligne.get_by_role("link", name="api/a1.py").click()
        attendre_dessin(page, "le fichier api/a1.py")
