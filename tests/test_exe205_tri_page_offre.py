"""Tests EXE-205 — navigateur réel (Playwright/Chromium, H5) : depuis la page
d'une offre à trier, je la retiens ou je l'écarte, même quand elle est classée
hors.

Outillage repris de `tests/test_exe202_navigateur.py` (front et API lancés par
le module, base posée par chaque test dans un dossier temporaire) : ses
fixtures sont réexposées ici sous leur nom, sans copie.

Aucun test n'appelle un vrai modèle : `run_fiche` et `run_cv` (lancés par
Retenir, via `cascade.launch_pieces`) et `run_lettre` sont remplacés dans
chaque test par des fonctions qui notent l'appel et ne font rien — la fiche et
le CV restent donc « en cours » (ligne `pending` posée par `launch_*`).
"""

from __future__ import annotations

import asyncio
import sqlite3
import time

import pytest
from playwright.sync_api import expect

import api.cv as api_cv
import api.fiche as api_fiche
import api.lettre as api_lettre
import tests.test_exe202_navigateur as outillage
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

navigateur_env = outillage.navigateur_env
navigateur = outillage.navigateur
page = outillage.page
front_url = outillage.front_url
db_path = outillage.db_path

# Libellés des étapes de la frise (`ETAPE_CANDIDATURE_LABELS` de la page).
LIBELLES_ETAPES = [
    "Retenue",
    "Prête à l'envoi",
    "Candidature envoyée",
    "Entretien à préparer",
    "Offre reçue",
    "Refusée",
    "Sans suite",
    "Abandonnée",
]


@pytest.fixture
def appels_modele(monkeypatch):
    """Remplace les trois générations par des enregistreurs inertes (ticket,
    « Ce qui ne doit pas arriver » : aucun vrai modèle). Chaque faux appel
    reste en cours jusqu'à la fin du test : une génération finie sans écrire
    son résultat serait lue par l'API comme interrompue."""
    appels: dict[str, list[int]] = {"fiche": [], "cv": [], "lettre": []}
    boucle: dict[str, asyncio.AbstractEventLoop] = {}
    liberer = asyncio.Event()

    def faux(nom):
        async def _faux(offer_id, *args, **kwargs):
            appels[nom].append(offer_id)
            boucle["api"] = asyncio.get_running_loop()
            await liberer.wait()

        return _faux

    monkeypatch.setattr(api_fiche, "run_fiche", faux("fiche"))
    monkeypatch.setattr(api_cv, "run_cv", faux("cv"))
    monkeypatch.setattr(api_lettre, "run_lettre", faux("lettre"))
    yield appels

    if "api" in boucle:
        boucle["api"].call_soon_threadsafe(liberer.set)
    fin = time.monotonic() + 5
    en_cours = (api_fiche._running, api_cv._running, api_lettre._running)
    while any(en_cours) and time.monotonic() < fin:
        time.sleep(0.05)


def _insert_offer_a_trier(db_path, offer_id, category):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, category) VALUES (?, 'test', ?, 'fp', ?, "
            "'Texte de l offre', ?)",
            (offer_id, str(offer_id), f"Poste EXE-205 {offer_id}", category),
        )
        conn.commit()
    finally:
        conn.close()


def _retenir_en_base(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        suivi_storage.appliquer_geste(conn, offer_id, suivi_etats.RETENIR)
        conn.commit()
    finally:
        conn.close()


def _etat_en_base(db_path, offer_id) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return suivi_storage.etat_stocke(conn, offer_id)
    finally:
        conn.close()


def _classement_en_base(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT category, categorie_suggeree, categorie_corrigee, "
            "hors_perimetre_reason, filtered_out, filter_reason "
            "FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
    finally:
        conn.close()


def _ouvrir(page, front_url, offer_id):
    page.goto(f"{front_url}/offers/{offer_id}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(f"Poste EXE-205 {offer_id}").first).to_be_visible()


def _bouton(page, nom):
    return page.get_by_role("button", name=nom, exact=True)


def _etape_en_couleur(page, libelle):
    return page.locator("div.bg-indigo-600", has_text=libelle)


def _cliquer_et_attendre(page, nom):
    """Clique et attend la réponse du geste — le rechargement de page est
    exclu par l'attente de la même instance de page (aucune navigation)."""
    with page.expect_response(lambda r: r.url.endswith("/geste")):
        _bouton(page, nom).click()


def _sans_rechargement(page):
    """Pose une marque sur `window` : elle disparaît si la page se recharge."""
    page.evaluate("window.__exe205_marque = 1")


def _assert_pas_recharge(page):
    assert page.evaluate("window.__exe205_marque") == 1


# ---------------------------------------------------------------------------
# Critères 1-3 — la page d'une offre à trier
# ---------------------------------------------------------------------------


class TestCritere1et2BoutonsSurOffreATrier:
    @pytest.mark.parametrize("category", ["parfait", "hors"])
    def test_retenir_et_ecarter_visibles(
        self, page, front_url, db_path, appels_modele, category
    ):
        offer_id = 20501 if category == "parfait" else 20502
        _insert_offer_a_trier(db_path, offer_id, category)
        _ouvrir(page, front_url, offer_id)
        expect(_bouton(page, "Retenir")).to_be_visible()
        expect(_bouton(page, "Écarter")).to_be_visible()


class TestCritere3AucuneEtapeEnCouleur:
    def test_aucune_etape_colorée(self, page, front_url, db_path, appels_modele):
        offer_id = 20503
        _insert_offer_a_trier(db_path, offer_id, "parfait")
        _ouvrir(page, front_url, offer_id)
        expect(_bouton(page, "Retenir")).to_be_visible()
        for libelle in LIBELLES_ETAPES:
            assert _etape_en_couleur(page, libelle).count() == 0, libelle


# ---------------------------------------------------------------------------
# Critères 4-6 — Retenir une offre classée parfait
# ---------------------------------------------------------------------------


class TestCriteres4a6RetenirParfait:
    def test_retenir_met_a_jour_la_page_sans_recharger(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 20504
        _insert_offer_a_trier(db_path, offer_id, "parfait")
        _ouvrir(page, front_url, offer_id)
        _sans_rechargement(page)

        _cliquer_et_attendre(page, "Retenir")

        # Critère 4 : l'étape « Retenue » en couleur.
        expect(_etape_en_couleur(page, "Retenue")).to_have_count(1)
        # Critère 5 : Retenir et Écarter ont disparu.
        expect(_bouton(page, "Retenir")).to_have_count(0)
        expect(_bouton(page, "Écarter")).to_have_count(0)
        # Critère 6 : la carte CV affiche « Génération en cours… ».
        page.get_by_text("CV", exact=True).first.click()
        expect(page.get_by_text("Génération en cours…")).to_be_visible()
        _assert_pas_recharge(page)

        # Retenir ne lance que la fiche et le CV : la lettre ne part pas.
        assert appels_modele["fiche"] == [offer_id]
        assert appels_modele["cv"] == [offer_id]
        assert appels_modele["lettre"] == []
        assert _etat_en_base(db_path, offer_id) == suivi_etats.RETENUE


# ---------------------------------------------------------------------------
# Critères 7-8 — Retenir une offre classée hors
# ---------------------------------------------------------------------------


class TestCriteres7et8RetenirHors:
    def test_offre_hors_retenue_apparait_dans_suivi(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 20507
        _insert_offer_a_trier(db_path, offer_id, "hors")
        _ouvrir(page, front_url, offer_id)
        _cliquer_et_attendre(page, "Retenir")
        expect(_bouton(page, "Retenir")).to_have_count(0)

        page.goto(f"{front_url}/?vue=suivi")
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text(f"Poste EXE-205 {offer_id}").first).to_be_visible()

    def test_categorie_affichee_reste_hors(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 20508
        _insert_offer_a_trier(db_path, offer_id, "hors")
        avant = _classement_en_base(db_path, offer_id)
        _ouvrir(page, front_url, offer_id)
        expect(page.get_by_text("✗ Hors", exact=True)).to_be_visible()

        _cliquer_et_attendre(page, "Retenir")
        expect(_bouton(page, "Retenir")).to_have_count(0)
        expect(page.get_by_text("✗ Hors", exact=True)).to_be_visible()

        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("✗ Hors", exact=True)).to_be_visible()
        assert _classement_en_base(db_path, offer_id) == avant


# ---------------------------------------------------------------------------
# Critères 9-10 — Écarter puis Remettre à trier
# ---------------------------------------------------------------------------


class TestCriteres9et10EcarterPuisRemettre:
    def test_ecarter_puis_remettre_sans_recharger(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 20509
        _insert_offer_a_trier(db_path, offer_id, "hors")
        avant = _classement_en_base(db_path, offer_id)
        _ouvrir(page, front_url, offer_id)
        _sans_rechargement(page)

        # Critère 9.
        _cliquer_et_attendre(page, "Écarter")
        expect(page.get_by_text("Écartée", exact=True)).to_be_visible()
        expect(_bouton(page, "Remettre à trier")).to_be_visible()
        assert page.url.endswith(f"/offers/{offer_id}")
        assert _etat_en_base(db_path, offer_id) == suivi_etats.ECARTEE

        # Critère 10.
        _cliquer_et_attendre(page, "Remettre à trier")
        expect(_bouton(page, "Retenir")).to_be_visible()
        expect(_bouton(page, "Écarter")).to_be_visible()
        expect(page.get_by_text("Écartée", exact=True)).to_have_count(0)
        _assert_pas_recharge(page)

        assert _etat_en_base(db_path, offer_id) == suivi_etats.A_TRIER
        assert _classement_en_base(db_path, offer_id) == avant
        assert appels_modele == {"fiche": [], "cv": [], "lettre": []}


# ---------------------------------------------------------------------------
# Critères 11-12 — autres cas
# ---------------------------------------------------------------------------


class TestCritere11OffreDejaRetenue:
    def test_ni_retenir_ni_ecarter(self, page, front_url, db_path, appels_modele):
        offer_id = 20511
        _insert_offer_a_trier(db_path, offer_id, "parfait")
        _retenir_en_base(db_path, offer_id)
        _ouvrir(page, front_url, offer_id)
        expect(_etape_en_couleur(page, "Retenue")).to_have_count(1)
        expect(_bouton(page, "Retenir")).to_have_count(0)
        expect(_bouton(page, "Écarter")).to_have_count(0)


class TestCritere12RefusDeLApiAffiche:
    def test_message_de_refus_affiche(self, page, front_url, db_path, appels_modele):
        offer_id = 20512
        _insert_offer_a_trier(db_path, offer_id, "parfait")
        _ouvrir(page, front_url, offer_id)
        expect(_bouton(page, "Retenir")).to_be_visible()

        _retenir_en_base(db_path, offer_id)
        _cliquer_et_attendre(page, "Retenir")

        message = str(suivi_etats.GesteRefuse(suivi_etats.RETENUE, suivi_etats.RETENIR))
        expect(page.get_by_text(message, exact=True)).to_be_visible()
