"""Tests EXE-222 — navigateur réel (Playwright/Chromium, H8) : chaque ligne de
« À postuler » dit où postuler, où est le poste et depuis quand l'annonce est en
ligne ; « À étudier » sépare « trop senior ? » de « est-ce intéressant ? ».

Outillage de `test_exe211_a_postuler_navigateur.py` : front et API lancés une
fois pour le module, base posée par chaque test dans un dossier temporaire, avec
ses parcours, comme la vérification les aurait écrits. Aucun site externe n'est
appelé : la vérification (critère 19) ne lit aucun parcours et `check_url` est
remplacé, et le lien « Postuler » (critère 3) est servi par une route du
navigateur.

Base des tests (en tête des critères du ticket). File principale : P1 finit sur
la page Sander, lieu réel « La Hulpe », en ligne depuis le 13 octobre 2026, une
jumelle actiris ; P2 finit sur un mail ; P3 a une adresse, jamais vérifiée.
File à étudier : S1 et S2 « trop senior ? », D1 « est-ce intéressant ? ».
Hors des files : 2 annonces expirées, la jumelle de P1 en doublon.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import expect

import orchestrator.job_search.expiration.service as expiration_service
from tests import test_exe202_navigateur as nav
from tests import test_exe211_a_postuler_navigateur as t211

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path

_profil = t211._profil
_sans_pieces = t211._sans_pieces
_table = t211._table
_ligne = t211._ligne
_lignes = t211._lignes
_ids_affiches = t211._ids_affiches
_ouvrir = t211._ouvrir
_bouton = t211._bouton

SANDER = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
MAIL = "c.brabant@connect-people.eu"
EDITX_FORM = "https://editx.eu/en/job/20200/apply"
URL_P2 = "https://annonce.test/p2"

PHRASE_DATA = (
    "Postes data et analyse, sortis de la liste principale le 25 novembre 2026. "
    "Gardés ici pour les étudier avec le chat avant de décider si la famille reste."
)
PHRASE_SENIOR = (
    "Offres que le modèle lit comme senior, sorties de la liste principale le "
    "27 novembre 2026. Tu peux encore en retenir une depuis sa page."
)

P1, JUMELLE, P2, P3 = 9201, 9202, 9203, 9204
S1, S2, D1 = 9211, 9212, 9213
EXP1, EXP2 = 9221, 9222


def _offre(
    db_path,
    offer_id,
    *,
    title="Développeur backend",
    company="Acme",
    location="Bruxelles",
    source="actiris",
    seniority="intermediate",
    jours=3,
    url=None,
):
    fetched = (datetime.now(timezone.utc) - timedelta(days=jours, hours=1)).isoformat()
    faits = json.dumps(
        {
            "seniority_required": seniority,
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": "backend",
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, description_raw, "
            "ad_language, extracted_facts_json, filtered_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'CDI', ?, ?, ?, ?, 'fr', ?, 0)",
            (
                offer_id,
                source,
                f"id-{offer_id}",
                f"fp-{offer_id}",
                title,
                company,
                location,
                f"https://annonce.test/{offer_id}" if url is None else url,
                fetched,
                "Poste dans une équipe produit.",
                "Poste dans une équipe produit.",
                faits,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _parcours(
    db_path,
    offer_id,
    *,
    fin_forme,
    fin_adresse=None,
    cle=None,
    lieu_reel=None,
    en_ligne_depuis=None,
):
    """Le parcours lu de l'offre, comme la vérification l'aurait écrit."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, "
            "fin_adresse, cle, lieu_reel, code_postal, provinces_json, "
            "en_ligne_depuis, ouverture, verifiee_le, fermeture_json) "
            "VALUES (?, ?, '[]', ?, ?, ?, ?, NULL, '[]', ?, 'ouverte', ?, NULL)",
            (
                offer_id,
                "2026-11-26T08:00:00+00:00",
                fin_forme,
                fin_adresse,
                cle or f"cle-{offer_id}",
                lieu_reel,
                en_ligne_depuis,
                "2026-11-26T08:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _expiree(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO expirations (offer_id, employer_url, expired, "
            "last_checked_at, checks_json) VALUES (?, NULL, 1, ?, '[]')",
            (offer_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _files(db_path):
    """Les deux files de la base, sans rien hors des files."""
    _offre(db_path, P1, title="Laravel developer", company="Sander", source="eures")
    _parcours(
        db_path,
        P1,
        fin_forme="page",
        fin_adresse=SANDER,
        cle="cle-sander",
        lieu_reel="La Hulpe",
        en_ligne_depuis="2026-10-13",
    )
    _offre(db_path, P2, title="Développeur PHP", company="Connect", url=URL_P2)
    _parcours(db_path, P2, fin_forme="mail", fin_adresse=MAIL)
    _offre(db_path, P3, title="Développeur Python", company="Mistral Labs")
    _offre(db_path, S1, title="Développeur Java", company="Zeta", seniority="senior")
    _offre(db_path, S2, title="Développeur Go", company="Omega", seniority="senior")
    _offre(db_path, D1, title="Data Analyst", company="Datacorp")


@pytest.fixture
def base_sans_sorties(db_path):
    _files(db_path)
    return db_path


@pytest.fixture
def base(db_path):
    _files(db_path)
    _offre(db_path, JUMELLE, title="Laravel developer", company="Sander SA", jours=10)
    _parcours(db_path, JUMELLE, fin_forme="page", fin_adresse=SANDER, cle="cle-sander")
    for oid in (EXP1, EXP2):
        _offre(db_path, oid, title=f"Développeur {oid}", company=f"Expirée {oid}")
        _expiree(db_path, oid)
    return db_path


PRINCIPALE = [P1, P2, P3]


def _attendre_ids(page, attendus: list[int]) -> None:
    """Les lignes affichées sont exactement `attendus`, dans n'importe quel ordre :
    le rang est décidé par l'API et n'est pas l'objet de ce ticket."""
    expect(_lignes(page)).to_have_count(len(attendus))
    page.wait_for_function(
        "ids => JSON.stringify([...document.querySelectorAll("
        "'table[aria-label=\"Liste à postuler\"] tbody tr')].map("
        "r => Number(r.dataset.offerId)).sort()) === JSON.stringify(ids)",
        arg=sorted(attendus),
    )
    assert sorted(_ids_affiches(page)) == sorted(attendus)


def _lien_postuler(page, offer_id):
    return _ligne(page, offer_id).get_by_role("link", name="wearesander.com")


# --- Où postuler -----------------------------------------------------------


class TestOuPostuler:
    def test_critere_01_postuler_nom_du_site(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        expect(_ligne(page, P1)).to_contain_text("Postuler : wearesander.com")

    def test_critere_02_lien_nouvel_onglet(self, page, front_url, base):
        _ouvrir(page, front_url)
        lien = _lien_postuler(page, P1)
        expect(lien).to_have_attribute("href", SANDER)
        expect(lien).to_have_attribute("target", "_blank")

    def test_critere_03_clic_n_ouvre_pas_la_page_de_l_offre(
        self, page, front_url, base
    ):
        page.context.route(
            "https://www.wearesander.com/**",
            lambda route: route.fulfill(status=200, body="<html>Sander</html>"),
        )
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        with page.context.expect_page() as onglet:
            _lien_postuler(page, P1).click()
        assert onglet.value.url.startswith(SANDER)
        page.wait_for_timeout(500)
        assert page.url.rstrip("/") == front_url
        expect(_table(page)).to_be_visible()

    def test_critere_04_postuler_mail(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P2)).to_contain_text(f"Postuler : {MAIL}")
        lien = _ligne(page, P2).get_by_role("link", name=MAIL)
        expect(lien).to_have_attribute("href", f"mailto:{MAIL}")

    def test_critere_05_formulaire_editx(self, page, front_url, base):
        _parcours(base, P3, fin_forme="formulaire", fin_adresse=EDITX_FORM)
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_contain_text("Postuler : formulaire EDITx")
        lien = _ligne(page, P3).get_by_role("link", name="formulaire EDITx")
        expect(lien).to_have_attribute("href", EDITX_FORM)

    def test_critere_06_sans_fin_pas_de_postuler(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_be_visible()
        expect(_ligne(page, P3)).not_to_contain_text("Postuler")

    def test_critere_07_jamais_verifiee(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_contain_text("jamais vérifiée")


# --- Le lieu et la date ----------------------------------------------------


class TestLieuEtDate:
    def test_critere_08_lieu_reel(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P1)).to_contain_text("La Hulpe")

    def test_critere_09_en_ligne_depuis(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P1)).to_contain_text("en ligne depuis le 13/10/2026")

    def test_critere_10_sans_date(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P2)).to_be_visible()
        expect(_ligne(page, P2)).not_to_contain_text("en ligne depuis")

    def test_critere_11_age_de_la_recuperation(self, page, front_url, base):
        _ouvrir(page, front_url)
        for oid in PRINCIPALE:
            expect(_ligne(page, oid)).to_contain_text("il y a 3 jours")


# --- Les marques et les jumelles -------------------------------------------


class TestMarquesEtJumelles:
    def test_critere_12_sans_lien(self, page, front_url, base_sans_sorties):
        conn = sqlite3.connect(base_sans_sorties)
        conn.execute("UPDATE offers SET url = '' WHERE id = ?", (P3,))
        conn.commit()
        conn.close()
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_contain_text("sans lien")

    def test_critere_13_page_d_accueil(self, page, front_url, base):
        _parcours(
            base, P3, fin_forme="accueil", fin_adresse="https://www.mistral.test/"
        )
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_contain_text("page d'accueil de l'employeur")

    def test_critere_14_plus_de_6_mois(self, page, front_url, base):
        _parcours(
            base,
            P3,
            fin_forme="page",
            en_ligne_depuis="2026-01-05",
            fin_adresse="https://www.mistral.test/jobs/1",
        )
        _ouvrir(page, front_url)
        expect(_ligne(page, P3)).to_contain_text("en ligne depuis plus de 6 mois")

    def test_critere_15_aussi_chez(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P1)).to_contain_text("aussi chez actiris")

    def test_critere_16_sans_jumelle(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_ligne(page, P2)).to_be_visible()
        expect(_ligne(page, P2)).not_to_contain_text("aussi chez")


# --- Ce qui est sorti de la liste ------------------------------------------


class TestSorties:
    def test_critere_17_phrase_des_sorties(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        expect(
            page.get_by_text(
                "Sorties de la liste : 2 annonces expirées, 1 doublon", exact=True
            )
        ).to_be_visible()

    def test_critere_18_sans_sorties(self, page, front_url, base_sans_sorties):
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        expect(page.get_by_text("Sorties de la liste")).to_have_count(0)

    def test_critere_19_verifier_sort_p2(self, page, front_url, base, monkeypatch):
        def _check(url):
            code = 404 if url == URL_P2 else 200
            return code, datetime.now(timezone.utc).isoformat()

        monkeypatch.setattr(expiration_service, "check_url", _check)
        monkeypatch.setattr(expiration_service, "ouvrir_lecteur", lambda: None)
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        _bouton(page, "Vérifier les offres").click()
        _attendre_ids(page, [P1, P3])
        expect(page.get_by_text("Sorties de la liste :")).to_contain_text(
            "3 annonces expirées"
        )


# --- « À étudier » et ses deux groupes -------------------------------------


def _a_etudier(page, front_url):
    _ouvrir(page, front_url)
    _attendre_ids(page, PRINCIPALE)
    _bouton(page, "À étudier (3)").click()
    _attendre_ids(page, [S1, S2, D1])


class TestGroupes:
    def test_critere_20_trois_boutons(self, page, front_url, base):
        _a_etudier(page, front_url)
        for nom in ("Tous (3)", "Trop senior ? (2)", "Est-ce intéressant ? (1)"):
            expect(_bouton(page, nom)).to_be_visible()

    def test_critere_21_ouvre_sur_tous(self, page, front_url, base):
        _a_etudier(page, front_url)
        expect(_table(page).locator("tbody tr")).to_have_count(3)

    def test_critere_22_groupe_de_chaque_ligne(self, page, front_url, base):
        _a_etudier(page, front_url)
        expect(_ligne(page, S1)).to_contain_text("trop senior ?")
        expect(_ligne(page, S2)).to_contain_text("trop senior ?")
        expect(_ligne(page, D1)).to_contain_text("est-ce intéressant ?")

    def test_critere_23_trop_senior(self, page, front_url, base):
        _a_etudier(page, front_url)
        _bouton(page, "Trop senior ? (2)").click()
        _attendre_ids(page, [S1, S2])

    def test_critere_24_interessant(self, page, front_url, base):
        _a_etudier(page, front_url)
        _bouton(page, "Est-ce intéressant ? (1)").click()
        _attendre_ids(page, [D1])

    def test_critere_25_nombres_stables(self, page, front_url, base):
        _a_etudier(page, front_url)
        _bouton(page, "Trop senior ? (2)").click()
        _attendre_ids(page, [S1, S2])
        for nom in ("Tous (3)", "Trop senior ? (2)", "Est-ce intéressant ? (1)"):
            expect(_bouton(page, nom)).to_be_visible()
        _bouton(page, "Est-ce intéressant ? (1)").click()
        _attendre_ids(page, [D1])
        for nom in ("Tous (3)", "Trop senior ? (2)", "Est-ce intéressant ? (1)"):
            expect(_bouton(page, nom)).to_be_visible()

    def test_critere_26_phrase_data(self, page, front_url, base):
        _a_etudier(page, front_url)
        expect(page.get_by_text(PHRASE_DATA, exact=True)).to_be_visible()
        _bouton(page, "Est-ce intéressant ? (1)").click()
        _attendre_ids(page, [D1])
        expect(page.get_by_text(PHRASE_DATA, exact=True)).to_be_visible()
        _bouton(page, "Trop senior ? (2)").click()
        _attendre_ids(page, [S1, S2])
        expect(page.get_by_text(PHRASE_DATA, exact=True)).to_have_count(0)

    def test_critere_27_phrase_senior(self, page, front_url, base):
        _a_etudier(page, front_url)
        expect(page.get_by_text(PHRASE_SENIOR, exact=True)).to_be_visible()
        _bouton(page, "Trop senior ? (2)").click()
        _attendre_ids(page, [S1, S2])
        expect(page.get_by_text(PHRASE_SENIOR, exact=True)).to_be_visible()
        _bouton(page, "Est-ce intéressant ? (1)").click()
        _attendre_ids(page, [D1])
        expect(page.get_by_text(PHRASE_SENIOR, exact=True)).to_have_count(0)

    def test_critere_28_pas_de_groupes_sur_a_postuler(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        expect(page.get_by_role("button", name="Trop senior ?")).to_have_count(0)
        expect(page.get_by_role("button", name="Est-ce intéressant ?")).to_have_count(0)
        expect(page.get_by_role("button", name="Tous (", exact=False)).to_have_count(0)

    def test_critere_29_retenir_depuis_trop_senior(self, page, front_url, base):
        _a_etudier(page, front_url)
        _bouton(page, "Trop senior ? (2)").click()
        _attendre_ids(page, [S1, S2])
        _ligne(page, S1).click()
        expect(page).to_have_url(f"{front_url}/offers/{S1}")
        _bouton(page, "Retenir").click()
        expect(_bouton(page, "Retenir")).to_have_count(0)
        _ouvrir(page, front_url)
        _attendre_ids(page, PRINCIPALE)
        _bouton(page, "À étudier (2)").click()
        _attendre_ids(page, [S2, D1])
