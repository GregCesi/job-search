"""Tests EXE-224 — navigateur réel (Playwright/Chromium) : un clic sur « Vérifier
les offres » vérifie tout, un panneau « Sorties » montre chaque offre sortie avec
sa raison et permet de la remettre, et « Suivi » dit quand une annonce est fermée.

Outillage de `test_exe222_ou_postuler_navigateur.py` : front et API lancés une
fois pour le module, base posée par chaque test dans un dossier temporaire, avec
ses offres, leurs parcours et leurs sorties, comme la vérification les aurait
écrits. Aucun site n'est appelé : pour les critères 1 à 3, l'API tourne dans
l'interpréteur du test, qui remplace le point d'appel réseau du parcours
(`parcours.reseau.lire`) et `check_url` (H8).
"""

from __future__ import annotations

import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
_lignes = t211._lignes
_ligne = t211._ligne
_ouvrir = t211._ouvrir
_bouton = t211._bouton

SOURCE = "la source ne rend plus l'offre"
PHRASE = "la page dit que l'offre est fermée"
PHRASE_LUE = "Cette offre n'est plus disponible"
# 23 h 30 à Greenwich le 25 : le 26 novembre à Bruxelles (critère 12).
TARD_LE_25 = "2026-11-25T23:30:00+00:00"
JAMAIS = "jamais vérifiée"

DEV, IA, ETUDE = 9401, 9402, 9403
EXP1, EXP2, EXP_ETUDE = 9411, 9412, 9413
HERSTAL, GARDEE, DOUBLON, ENVOYEE, TRAITEE, SANS_SIGNE = (
    9421,
    9422,
    9423,
    9424,
    9425,
    9426,
)
SUIVI_FERMEE, SUIVI_OUVERTE = 9431, 9432


# --- La base ---------------------------------------------------------------


def _offre(
    db_path,
    offer_id,
    *,
    title="Développeur Python",
    company=None,
    location="Bruxelles",
    source="actiris",
    domain="backend",
    techs=(("python", "core"),),
    jours=3,
):
    fetched = (datetime.now(timezone.utc) - timedelta(days=jours, hours=1)).isoformat()
    faits = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": t, "importance": i} for t, i in techs],
            "domain": domain,
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    with sqlite3.connect(db_path) as conn:
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
                company or f"Entreprise {offer_id}",
                location,
                f"https://annonce.test/{offer_id}",
                fetched,
                "Poste dans une équipe produit.",
                "Poste dans une équipe produit.",
                faits,
            ),
        )


def _parcours(
    db_path,
    offer_id,
    *,
    fin_forme="page",
    fin_adresse=None,
    cle=None,
    lieu_reel=None,
    code_postal=None,
    ouverture="ouverte",
    fermeture=None,
    verifiee_le=TARD_LE_25,
):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, "
            "fin_adresse, cle, lieu_reel, code_postal, provinces_json, "
            "en_ligne_depuis, ouverture, verifiee_le, fermeture_json) "
            "VALUES (?, ?, '[]', ?, ?, ?, ?, ?, '[]', NULL, ?, ?, ?)",
            (
                offer_id,
                verifiee_le,
                fin_forme,
                fin_adresse,
                cle,
                lieu_reel,
                code_postal,
                ouverture,
                verifiee_le,
                json.dumps(fermeture) if fermeture else None,
            ),
        )


def _expiree(db_path, offer_id, quand=TARD_LE_25):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO expirations (offer_id, employer_url, expired, "
            "last_checked_at, checks_json) VALUES (?, NULL, 1, ?, '[]')",
            (offer_id, quand),
        )


def _etat(db_path, offer_id, etat):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?)", (offer_id, etat)
        )


def _fermee(db_path, offer_id, fermeture):
    """Fermée par une vérification : parcours fermé et verdict d'expiration."""
    _parcours(
        db_path,
        offer_id,
        fin_forme="inconnue",
        ouverture="fermée",
        fermeture=fermeture,
    )
    _expiree(db_path, offer_id)


def _eures_fermee(db_path, offer_id, **autres):
    _offre(db_path, offer_id, source="eures", **autres)
    _fermee(
        db_path,
        offer_id,
        {"signe": SOURCE, "site": "europa.eu", "code": 404, "phrase": None},
    )


@pytest.fixture
def base(db_path):
    """Une ligne dans « À postuler », deux sorties de cette file."""
    _offre(db_path, DEV, title="Développeur backend", company="Mistral Labs")
    _eures_fermee(db_path, EXP1, title="Développeur Laravel", company="Sander")
    _offre(db_path, EXP2, title="Développeur Django", company="Zeta")
    _fermee(
        db_path,
        EXP2,
        {"signe": PHRASE, "site": "zeta.test", "code": 200, "phrase": PHRASE_LUE},
    )
    return db_path


@pytest.fixture
def base_motifs(db_path):
    """Une ligne dans la liste et une sortie par motif."""
    _offre(db_path, DEV, title="Développeur backend", company="Mistral Labs")
    _offre(db_path, HERSTAL, title="Développeur Herstal", location="Belgique")
    _parcours(
        db_path,
        HERSTAL,
        fin_adresse="https://www.herstal.test/jobs/1",
        cle="https://www.herstal.test/jobs/1",
        lieu_reel="Herstal",
        code_postal="4040",
    )
    _offre(db_path, GARDEE, title="Développeur PHP", jours=1)
    _offre(db_path, DOUBLON, title="PHP developer", jours=6)
    _parcours(db_path, GARDEE, cle="https://exemple.be/postuler/42")
    _parcours(db_path, DOUBLON, cle="https://exemple.be/postuler/42")
    _offre(db_path, ENVOYEE, title="Développeur Go")
    _etat(db_path, ENVOYEE, "candidature_envoyee")
    _parcours(db_path, ENVOYEE, cle="https://exemple.be/postuler/7")
    _offre(db_path, TRAITEE, title="Go developer")
    _parcours(db_path, TRAITEE, cle="https://exemple.be/postuler/7")
    _offre(db_path, SANS_SIGNE, title="Développeur Rust")
    _expiree(db_path, SANS_SIGNE)
    return db_path


# --- Le navigateur ---------------------------------------------------------


def _panneau(page):
    return page.get_by_role("list", name="Sorties")


def _sortie(page, offer_id):
    return _panneau(page).locator(f'li[data-offer-id="{offer_id}"]')


def _ouvrir_sorties(page, n):
    expect(_bouton(page, f"Sorties ({n})")).to_be_visible()
    _bouton(page, f"Sorties ({n})").click()
    expect(_panneau(page).locator("li")).to_have_count(n)


def _attendre_ids(page, attendus):
    expect(_lignes(page)).to_have_count(len(attendus))
    page.wait_for_function(
        "ids => JSON.stringify([...document.querySelectorAll("
        "'table[aria-label=\"Liste à postuler\"] tbody tr')].map("
        "r => Number(r.dataset.offerId)).sort()) === JSON.stringify(ids)",
        arg=sorted(attendus),
    )


def _menu(page, nom):
    page.get_by_role("navigation", name="Vue candidat").get_by_role(
        "button", name=nom
    ).click()


# --- Un clic vérifie tout --------------------------------------------------


@pytest.fixture
def reseau_simule(monkeypatch):
    """Toute page lue répond 200, sans signe de fermeture."""
    reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    monkeypatch.setattr(
        reseau,
        "lire",
        lambda adresse: SimpleNamespace(
            chaine=[(adresse, 200)], texte="<html><title>Offre</title></html>"
        ),
    )
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)
    monkeypatch.setattr(
        expiration_service,
        "check_url",
        lambda url: (200, datetime.now(timezone.utc).isoformat()),
    )


@pytest.fixture
def base_familles(db_path):
    _offre(db_path, DEV, title="Développeur Python", company="Mistral Labs")
    _offre(
        db_path,
        IA,
        title="Ingénieur IA",
        company="Zeta IA",
        domain="ai_engineering",
        techs=(("claude", "core"),),
    )
    _offre(db_path, ETUDE, title="Data Analyst", company="Datacorp")
    return db_path


def _verifier(page):
    _bouton(page, "Vérifier les offres").click()
    expect(_bouton(page, "Vérification en cours…")).to_have_count(0, timeout=20000)
    expect(_bouton(page, "Vérifier les offres")).to_be_enabled()


class TestUnClicVerifieTout:
    def test_critere_01_famille_ia(self, page, front_url, base_familles, reseau_simule):
        _ouvrir(page, front_url)
        _bouton(page, "IA et automatisation (1)").click()
        expect(_ligne(page, IA)).to_contain_text(JAMAIS)
        _bouton(page, "Développeur (1)").click()
        expect(_ligne(page, DEV)).to_be_visible()
        _verifier(page)
        _bouton(page, "IA et automatisation (1)").click()
        expect(_ligne(page, IA)).to_be_visible()
        expect(_ligne(page, IA)).not_to_contain_text(JAMAIS)

    def test_critere_02_a_etudier(self, page, front_url, base_familles, reseau_simule):
        _ouvrir(page, front_url)
        _bouton(page, "Développeur (1)").click()
        expect(_ligne(page, DEV)).to_be_visible()
        _verifier(page)
        _bouton(page, "À étudier (1)").click()
        expect(_ligne(page, ETUDE)).to_be_visible()
        expect(_ligne(page, ETUDE)).not_to_contain_text(JAMAIS)

    def test_critere_03_depuis_suivi(
        self, page, front_url, base_familles, reseau_simule
    ):
        # Une candidature en cours : la vue Suivi n'est pas vide.
        _offre(base_familles, SUIVI_OUVERTE, title="Développeur retenu")
        _etat(base_familles, SUIVI_OUVERTE, "retenue")
        _ouvrir(page, front_url)
        expect(_ligne(page, DEV)).to_contain_text(JAMAIS)
        _menu(page, "Suivi")
        expect(_ligne_suivi(page, "Développeur retenu")).to_be_visible()
        _verifier(page)
        _menu(page, "À postuler")
        expect(_ligne(page, DEV)).to_be_visible()
        expect(_ligne(page, DEV)).not_to_contain_text(JAMAIS)


# --- Le panneau « Sorties » ------------------------------------------------


class TestPanneau:
    def test_critere_04_bouton_sorties(self, page, front_url, base):
        _ouvrir(page, front_url)
        _attendre_ids(page, [DEV])
        expect(_bouton(page, "Sorties (2)")).to_be_visible()

    def test_critere_05_sans_sortie(self, page, front_url, db_path):
        _offre(db_path, DEV)
        _ouvrir(page, front_url)
        _attendre_ids(page, [DEV])
        expect(page.get_by_role("button", name="Sorties (")).to_have_count(0)

    def test_h4_ferme_par_defaut(self, page, front_url, base):
        _ouvrir(page, front_url)
        expect(_bouton(page, "Sorties (2)")).to_be_visible()
        expect(_panneau(page)).to_have_count(0)
        _bouton(page, "Sorties (2)").click()
        expect(_panneau(page)).to_be_visible()
        _bouton(page, "Sorties (2)").click()
        expect(_panneau(page)).to_have_count(0)

    def test_critere_06_deux_lignes(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        expect(_sortie(page, EXP1)).to_contain_text("Développeur Laravel")
        expect(_sortie(page, EXP1)).to_contain_text("Sander")
        expect(_sortie(page, EXP2)).to_contain_text("Développeur Django")
        expect(_sortie(page, EXP2)).to_contain_text("Zeta")

    def test_critere_07_eures(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        expect(_sortie(page, EXP1)).to_contain_text(
            "annonce expirée : la source ne rend plus l'offre (europa.eu, 404)"
        )

    def test_critere_08_phrase(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        expect(_sortie(page, EXP2)).to_contain_text(f"« {PHRASE_LUE} »")

    def test_critere_09_lieu(self, page, front_url, base_motifs):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 4)
        expect(_sortie(page, HERSTAL)).to_contain_text("lieu : Herstal 4040")

    def test_critere_10_doublon(self, page, front_url, base_motifs):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 4)
        expect(_sortie(page, DOUBLON)).to_contain_text("doublon de Développeur PHP")

    def test_critere_11_deja_traitee(self, page, front_url, base_motifs):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 4)
        expect(_sortie(page, TRAITEE)).to_contain_text(
            "déjà traitée : candidature envoyée"
        )

    def test_critere_12_date_de_bruxelles(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        for oid in (EXP1, EXP2):
            expect(_sortie(page, oid)).to_contain_text("vérifiée le 26/11/2026")

    def test_critere_13_voir_la_preuve(self, page, front_url, base, navigateur_env):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        url = f"http://127.0.0.1:{navigateur_env['api_port']}/a-postuler/sorties"
        preuves = {s["id"]: s["preuve"] for s in page.request.get(url).json()}
        for oid in (EXP1, EXP2):
            lien = _sortie(page, oid).get_by_role("link", name="Voir la preuve")
            expect(lien).to_have_attribute("href", preuves[oid])
            expect(lien).to_have_attribute("target", "_blank")

    def test_critere_14_poste_ouvre_l_offre(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        poste = _sortie(page, EXP1).get_by_role("link", name="Développeur Laravel")
        expect(poste).to_be_visible()
        poste.click()
        expect(page).to_have_url(f"{front_url}/offers/{EXP1}")

    def test_critere_15_remettre(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        remettre = _sortie(page, EXP1).get_by_role(
            "button", name="Remettre dans la liste"
        )
        expect(remettre).to_be_visible()
        remettre.click()
        expect(_sortie(page, EXP1)).to_have_count(0)
        expect(_bouton(page, "Sorties (1)")).to_be_visible()

    def test_critere_16_remise_dans_la_liste(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        remettre = _sortie(page, EXP1).get_by_role(
            "button", name="Remettre dans la liste"
        )
        expect(remettre).to_be_visible()
        remettre.click()
        _attendre_ids(page, [DEV, EXP1])
        expect(_ligne(page, EXP1)).to_contain_text("remise à la main")

    def test_critere_17_chaque_file_ses_sorties(self, page, front_url, base):
        _offre(base, EXP_ETUDE, title="Data Analyst", company="Datacorp")
        _expiree(base, EXP_ETUDE)
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        expect(_sortie(page, EXP_ETUDE)).to_have_count(0)
        expect(_bouton(page, "À étudier (0)")).to_be_visible()
        _bouton(page, "À étudier (0)").click()
        # Le panneau ouvert le reste d'une file à l'autre.
        expect(_bouton(page, "Sorties (1)")).to_be_visible()
        expect(_panneau(page).locator("li")).to_have_count(1)
        expect(_sortie(page, EXP_ETUDE)).to_be_visible()
        expect(_sortie(page, EXP1)).to_have_count(0)

    def test_critere_18_sans_signe(self, page, front_url, base_motifs):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 4)
        motif = _sortie(page, SANS_SIGNE).get_by_test_id("raison")
        expect(motif).to_have_text("annonce expirée")

    def test_critere_19_phrase_des_sorties(self, page, front_url, base):
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        expect(
            page.get_by_text("Sorties de la liste : 2 annonces expirées", exact=True)
        ).to_be_visible()

    def test_interdit_aucune_remise_sans_clic(self, page, front_url, base):
        remises = []
        page.on(
            "request",
            lambda r: remises.append(r.url) if "/remise" in r.url else None,
        )
        _ouvrir(page, front_url)
        _ouvrir_sorties(page, 2)
        _bouton(page, "Sorties (2)").click()
        page.wait_for_timeout(300)
        assert remises == []


# --- Suivi -----------------------------------------------------------------


def _ligne_suivi(page, titre):
    return page.locator("tbody tr").filter(has_text=titre)


@pytest.fixture
def base_suivi(db_path):
    _offre(db_path, SUIVI_FERMEE, title="Développeur fermé", source="eures")
    _etat(db_path, SUIVI_FERMEE, "candidature_envoyee")
    _fermee(
        db_path,
        SUIVI_FERMEE,
        {"signe": SOURCE, "site": "europa.eu", "code": 404, "phrase": None},
    )
    _offre(db_path, SUIVI_OUVERTE, title="Développeur ouvert")
    _etat(db_path, SUIVI_OUVERTE, "candidature_envoyee")
    _parcours(db_path, SUIVI_OUVERTE, cle="https://exemple.be/ouverte")
    return db_path


class TestSuivi:
    def test_critere_20_annonce_fermee(self, page, front_url, base_suivi):
        page.goto(f"{front_url}/?vue=suivi")
        ligne = _ligne_suivi(page, "Développeur fermé")
        expect(ligne).to_contain_text("Expiré")
        expect(ligne).to_contain_text(
            "la source ne rend plus l'offre, vue le 26/11/2026"
        )

    def test_critere_21_annonce_ouverte(self, page, front_url, base_suivi):
        page.goto(f"{front_url}/?vue=suivi")
        expect(_ligne_suivi(page, "Développeur fermé")).to_contain_text("vue le")
        ligne = _ligne_suivi(page, "Développeur ouvert")
        expect(ligne).to_be_visible()
        expect(ligne).not_to_contain_text("Expiré")
        expect(ligne).not_to_contain_text("vue le")
