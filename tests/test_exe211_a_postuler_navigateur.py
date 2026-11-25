"""Tests EXE-211 — navigateur réel (Playwright/Chromium, H8) : la vue
« À postuler » du menu candidat, ses deux files, ses filtres et ses tris.

Outillage repris de `test_exe202_navigateur.py` : front et API lancés une fois
pour le module, base posée par chaque test dans un dossier temporaire. L'API
tourne dans le même interpréteur : le profil personnel, le lancement des pièces
au geste de retenir et la vérification d'expiration (critère 38) y sont
remplacés par monkeypatch. Aucun site externe, aucun modèle n'est appelé.

Base des tests de la liste (en tête des critères) : 1 offre « IA et
automatisation » (rang 1), 2 offres « Développeur » (rangs 2 et 3) dont une de
l'entreprise Sander, 1 offre « Data et analyse » ; 2 des 3 offres de la liste
principale ont moins de 15 jours.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

import api.cascade as cascade
import orchestrator.job_search.expiration.service as expiration_service
import orchestrator.job_search.paths as paths_mod
from tests import test_exe202_navigateur as nav

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path

PHRASE_A_ETUDIER = (
    "Postes data et analyse, sortis de la liste principale le 25 novembre 2026. "
    "Gardés ici pour les étudier avec le chat avant de décider si la famille reste."
)
FILE_VIDE = "Aucune offre ici. Lance un run ou ajoute une offre."

PROFIL = """\
profile_id: test
role_ceiling: ic
seniority_ceiling: intermediate
skills:
  python: { level: 6, desire: 5 }
  claude: { level: 5, desire: 5 }
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: []
  contract_types: []
"""

IA_ID, DEV_ID, SANDER_ID, DATA_ID = 9101, 9102, 9103, 9104
URL_SANDER = "https://annonce.test/sander"


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths_mod, "PROFILE_PATH", chemin)


@pytest.fixture(autouse=True)
def _sans_pieces(monkeypatch):
    """Retenir (critère 35) ne lance aucune pièce : rien n'appelle de modèle."""

    async def _noop(offer_id):
        return None

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _offre(
    db_path,
    offer_id,
    *,
    title,
    company,
    location,
    contract,
    domain,
    seniority,
    techs,
    jours,
    langues=(),
    description="Poste dans une équipe produit.",
    url=None,
):
    fetched = (datetime.now(timezone.utc) - timedelta(days=jours, hours=1)).isoformat()
    faits = json.dumps(
        {
            "seniority_required": seniority,
            "techs_required": [{"name": t, "importance": i} for t, i in techs],
            "domain": domain,
            "role_level": "ic",
            "langues_requises": list(langues),
        }
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, description_raw, "
            "ad_language, extracted_facts_json, filtered_out) "
            "VALUES (?, 'actiris', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'fr', ?, 0)",
            (
                offer_id,
                f"id-{offer_id}",
                f"fp-{offer_id}",
                title,
                company,
                location,
                contract,
                url or f"https://annonce.test/{offer_id}",
                fetched,
                description,
                description,
                faits,
            ),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def base(db_path):
    _offre(
        db_path,
        IA_ID,
        title="Ingénieur IA",
        company="Zeta IA",
        location="Ixelles",
        contract="CDI",
        domain="ai_engineering",
        seniority="junior",
        techs=(("claude", "core"),),
        jours=3,
    )
    _offre(
        db_path,
        DEV_ID,
        title="Développeur Python",
        company="Mistral Labs",
        location="Bruxelles",
        contract="CDD",
        domain="backend",
        seniority="intermediate",
        techs=(("python", "core"), ("cobol", "required")),
        jours=5,
        langues=("néerlandais",),
        description="Poste backend. Le néerlandais est un atout.",
    )
    _offre(
        db_path,
        SANDER_ID,
        title="Développeur backend",
        company="Sander",
        location="Belgique",
        contract="Interim",
        domain="backend",
        seniority="senior",
        techs=(("python", "core"),),
        jours=30,
        url=URL_SANDER,
    )
    _offre(
        db_path,
        DATA_ID,
        title="Data Analyst",
        company="Datacorp",
        location="Bruxelles",
        contract="CDI",
        domain="backend",
        seniority="junior",
        techs=(("python", "core"),),
        jours=4,
    )
    return db_path


def _api(navigateur_env, **params) -> dict:
    query = urllib.parse.urlencode(params)
    url = f"http://127.0.0.1:{navigateur_env['api_port']}/a-postuler?{query}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def _api_ids(navigateur_env, **params) -> list[int]:
    return [li["id"] for li in _api(navigateur_env, **params)["lignes"]]


def _table(page):
    return page.get_by_role("table", name="Liste à postuler")


def _lignes(page):
    return _table(page).locator("tbody tr")


def _ligne(page, offer_id):
    return _table(page).locator(f'tbody tr[data-offer-id="{offer_id}"]')


def _ids_affiches(page) -> list[int]:
    return [
        int(v)
        for v in _lignes(page).evaluate_all("rows => rows.map(r => r.dataset.offerId)")
    ]


def _attendre_ids(page, attendus: list[int]) -> None:
    expect(_lignes(page)).to_have_count(len(attendus))
    page.wait_for_function(
        "ids => JSON.stringify([...document.querySelectorAll("
        "'table[aria-label=\"Liste à postuler\"] tbody tr')].map("
        "r => Number(r.dataset.offerId))) === JSON.stringify(ids)",
        arg=attendus,
    )
    assert _ids_affiches(page) == attendus


def _ouvrir(page, front_url, chemin="/"):
    page.goto(f"{front_url}{chemin}")
    expect(_table(page).or_(page.get_by_text(FILE_VIDE))).to_be_visible()


def _rang(page, offer_id) -> str:
    return _ligne(page, offer_id).locator("td").first.inner_text().strip()


def _bouton(page, nom):
    return page.get_by_role("button", name=nom, exact=True)


# --- Le menu ---------------------------------------------------------------


class TestMenu:
    def test_criteres_1_2_trois_entrees(self, page, front_url, base):
        _ouvrir(page, front_url)
        menu = page.get_by_role("navigation", name="Vue candidat")
        textes = [t.strip() for t in menu.locator("button, a").all_inner_texts()]
        assert textes == ["À postuler", "Suivi", "Écartées"]
        for ancien in ("Cibles", "Gaps", "Filet"):
            expect(menu.get_by_text(ancien, exact=True)).to_have_count(0)

    def test_critere_3_accueil(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_table(page)).to_be_visible()
        menu = page.get_by_role("navigation", name="Vue candidat")
        expect(menu.get_by_role("button", name="À postuler")).to_have_attribute(
            "aria-current", "page"
        )

    @pytest.mark.parametrize("vue", ["cibles", "gaps", "filet"])
    def test_critere_4_anciens_liens(self, page, front_url, base, vue):
        _ouvrir(page, front_url, f"/?vue={vue}")
        expect(_table(page)).to_be_visible()
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])


# --- Les deux files --------------------------------------------------------


class TestFiles:
    def test_criteres_5_6_boutons_et_trois_lignes(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_bouton(page, "À postuler (3)")).to_be_visible()
        expect(_bouton(page, "À étudier (1)")).to_be_visible()
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])

    def test_criteres_7_8_a_etudier(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        _bouton(page, "À étudier (1)").click()
        _attendre_ids(page, [DATA_ID])
        expect(page.get_by_text(PHRASE_A_ETUDIER, exact=True)).to_be_visible()

    def test_critere_9_phrase_absente_sur_a_postuler(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        expect(page.get_by_text(PHRASE_A_ETUDIER)).to_have_count(0)


# --- La liste --------------------------------------------------------------


class TestListe:
    def test_criteres_10_11_ordre_et_rangs(self, page, front_url, base, navigateur_env):
        attendus = _api_ids(navigateur_env)
        assert attendus == [IA_ID, DEV_ID, SANDER_ID]
        _ouvrir(page, front_url)
        _attendre_ids(page, attendus)
        assert [_rang(page, i) for i in attendus] == ["1", "2", "3"]

    def test_critere_12_poste_entreprise_contrat_lieu(self, page, front_url, base):
        _ouvrir(page, front_url)
        ligne = _ligne(page, DEV_ID)
        for texte in ("Développeur Python", "Mistral Labs", "CDD", "Bruxelles"):
            expect(ligne).to_contain_text(texte)

    def test_critere_13_age(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, IA_ID)).to_contain_text("il y a 3 jours")

    def test_critere_14_famille(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, IA_ID)).to_contain_text("IA et automatisation")
        expect(_ligne(page, DEV_ID)).to_contain_text("Développeur")
        expect(_ligne(page, SANDER_ID)).to_contain_text("Développeur")

    def test_critere_15_niveau(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, IA_ID)).to_contain_text("junior")
        expect(_ligne(page, DEV_ID)).to_contain_text("intermédiaire")
        expect(_ligne(page, SANDER_ID)).to_contain_text("senior")

    def test_critere_16_atteignabilite(self, page, front_url, base, navigateur_env):
        lignes = {li["id"]: li for li in _api(navigateur_env)["lignes"]}
        assert lignes[DEV_ID]["atteignabilite"] == 36
        _ouvrir(page, front_url)
        cellule = _ligne(page, DEV_ID).get_by_test_id("atteignabilite")
        expect(cellule).to_have_text("36")

    def test_critere_17_absentes(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, DEV_ID)).to_contain_text("Absentes : cobol")

    def test_critere_18_sans_absentes(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, SANDER_ID)).to_be_visible()
        expect(_ligne(page, SANDER_ID)).not_to_contain_text("Absentes")

    def test_critere_19_lieu_non_precise(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, SANDER_ID)).to_contain_text("lieu non précisé")

    def test_critere_20_neerlandais_en_atout(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, DEV_ID)).to_contain_text("néerlandais en atout")

    def test_critere_21_file_vide(self, page, front_url, db_path):
        _ouvrir(page, front_url)
        expect(page.get_by_text(FILE_VIDE, exact=True)).to_be_visible()


# --- Filtrer ---------------------------------------------------------------


class TestFiltrer:
    def test_criteres_22_23_24_famille(self, page, front_url, base):
        _ouvrir(page, front_url)
        for nom in ("Toutes (3)", "IA et automatisation (1)", "Développeur (2)"):
            expect(_bouton(page, nom)).to_be_visible()
        _bouton(page, "Développeur (2)").click()
        _attendre_ids(page, [DEV_ID, SANDER_ID])
        for i in (DEV_ID, SANDER_ID):
            expect(_ligne(page, i)).to_contain_text("Développeur")
        assert [_rang(page, i) for i in (DEV_ID, SANDER_ID)] == ["2", "3"]

    def test_critere_25_recentes(self, page, front_url, base):
        _ouvrir(page, front_url)
        _bouton(page, "Récentes (2)").click()
        _attendre_ids(page, [IA_ID, DEV_ID])

    def test_critere_26_recherche(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        champ = page.get_by_role("searchbox", name="Rechercher")
        champ.fill("sander")
        champ.press("Enter")
        _attendre_ids(page, [SANDER_ID])

    def test_critere_27_nombres_stables(self, page, front_url, base):
        _ouvrir(page, front_url)
        _bouton(page, "Développeur (2)").click()
        _attendre_ids(page, [DEV_ID, SANDER_ID])
        _bouton(page, "Récentes (2)").click()
        _attendre_ids(page, [DEV_ID])
        champ = page.get_by_role("searchbox", name="Rechercher")
        champ.fill("python")
        champ.press("Enter")
        _attendre_ids(page, [DEV_ID])
        for nom in (
            "À postuler (3)",
            "À étudier (1)",
            "Toutes (3)",
            "IA et automatisation (1)",
            "Développeur (2)",
            "Récentes (2)",
        ):
            expect(_bouton(page, nom)).to_be_visible()

    def test_critere_28_pas_de_familles_sur_a_etudier(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_bouton(page, "Toutes (3)")).to_be_visible()
        _bouton(page, "À étudier (1)").click()
        _attendre_ids(page, [DATA_ID])
        expect(page.get_by_role("button", name="Toutes")).to_have_count(0)
        expect(page.get_by_role("button", name="Développeur")).to_have_count(0)
        expect(page.get_by_role("button", name="IA et automatisation")).to_have_count(0)


# --- Trier -----------------------------------------------------------------


def _entete(page, nom):
    return _table(page).locator("thead").get_by_role("button", name=nom, exact=True)


class TestTrier:
    def test_criteres_29_30_33_entreprise(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        _entete(page, "Entreprise").click()
        # Mistral Labs, Sander, Zeta IA
        _attendre_ids(page, [DEV_ID, SANDER_ID, IA_ID])
        assert [_rang(page, i) for i in (DEV_ID, SANDER_ID, IA_ID)] == ["2", "3", "1"]
        _entete(page, "Entreprise").click()
        _attendre_ids(page, [IA_ID, SANDER_ID, DEV_ID])

    @pytest.mark.parametrize(
        "entete,tri",
        [
            ("Contrat", "contrat"),
            ("Lieu", "lieu"),
            ("Famille", "famille"),
            ("Récupérée", "recuperee"),
            ("Atteignabilité", "atteignabilite"),
        ],
    )
    def test_critere_31_entetes(
        self, page, front_url, base, navigateur_env, entete, tri
    ):
        attendus = _api_ids(navigateur_env, tri=tri, ordre="asc")
        assert attendus != [IA_ID, DEV_ID, SANDER_ID], "base qui ne prouve rien"
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        _entete(page, entete).click()
        _attendre_ids(page, attendus)

    def test_critere_32_retour_au_rang(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        _entete(page, "Entreprise").click()
        _attendre_ids(page, [DEV_ID, SANDER_ID, IA_ID])
        _entete(page, "Rang").click()
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])


# --- Ouvrir et agir --------------------------------------------------------


class TestOuvrirEtAgir:
    def test_critere_34_ouvrir(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ligne(page, DEV_ID).click()
        expect(page).to_have_url(f"{front_url}/offers/{DEV_ID}")

    def test_critere_35_retenir(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ligne(page, DEV_ID).click()
        expect(page).to_have_url(f"{front_url}/offers/{DEV_ID}")
        _bouton(page, "Retenir").click()
        expect(_bouton(page, "Retenir")).to_have_count(0)
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, SANDER_ID])

    def test_critere_36_ecarter(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ligne(page, SANDER_ID).click()
        expect(page).to_have_url(f"{front_url}/offers/{SANDER_ID}")
        _bouton(page, "Écarter").click()
        expect(_bouton(page, "Écarter")).to_have_count(0)
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID])

    def test_critere_37_bouton_verifier(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_bouton(page, "Vérifier les offres")).to_be_visible()

    def test_critere_38_verifier_retire_l_expiree(
        self, page, front_url, base, monkeypatch
    ):
        def _check(url):
            code = 404 if url == URL_SANDER else 200
            return code, datetime.now(timezone.utc).isoformat()

        monkeypatch.setattr(expiration_service, "check_url", _check)
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        _bouton(page, "Vérifier les offres").click()
        _attendre_ids(page, [IA_ID, DEV_ID])


# --- Ce qui disparait de l'écran --------------------------------------------


class TestReglagesRetires:
    def test_critere_39_profil_de_vue_et_remote(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [IA_ID, DEV_ID, SANDER_ID])
        expect(page.get_by_text("Profil de vue")).to_have_count(0)
        expect(page.get_by_text("Inclure le remote")).to_have_count(0)
