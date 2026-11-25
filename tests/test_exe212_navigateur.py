"""Tests EXE-212 — navigateur réel (Playwright/Chromium, H6) sur les critères
6 et 9 : sur une offre retenue sans fiche, l'onglet de la fiche entreprise
propose « Préparer la fiche », et « Générer la lettre » laisse la carte de la
lettre en attente de la fiche.

Outillage repris de `tests/test_exe202_navigateur.py` (front et API lancés par
le module, base posée par chaque test dans un dossier temporaire) et
enregistreurs de `tests/test_exe205_tri_page_offre.py` (`run_fiche`, `run_cv`,
`run_lettre` remplacés : aucun vrai modèle), réexposés ici sans copie.
"""

from __future__ import annotations

import sqlite3

from playwright.sync_api import expect

import tests.test_exe202_navigateur as outillage
import tests.test_exe205_tri_page_offre as outillage_205
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

navigateur_env = outillage.navigateur_env
navigateur = outillage.navigateur
page = outillage.page
front_url = outillage.front_url
db_path = outillage.db_path
appels_modele = outillage_205.appels_modele


def _insert_offer_retenue(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, category) VALUES (?, 'test', ?, 'fp', ?, "
            "'Texte de l offre', 'parfait')",
            (offer_id, str(offer_id), f"Poste EXE-212 {offer_id}"),
        )
        suivi_storage.appliquer_geste(conn, offer_id, suivi_etats.RETENIR)
        conn.commit()
    finally:
        conn.close()


def _ouvrir(page, front_url, offer_id):
    page.goto(f"{front_url}/offers/{offer_id}")
    page.wait_for_load_state("networkidle")
    expect(page.get_by_text(f"Poste EXE-212 {offer_id}").first).to_be_visible()


def _bouton(page, nom):
    return page.get_by_role("button", name=nom, exact=True)


class TestCritere6PreparerLaFicheAffiche:
    def test_bouton_preparer_la_fiche_sur_offre_retenue_sans_fiche(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 21206
        _insert_offer_retenue(db_path, offer_id)
        _ouvrir(page, front_url, offer_id)

        page.get_by_text("Entreprise", exact=True).first.click()

        expect(_bouton(page, "Préparer la fiche")).to_be_visible()
        assert appels_modele["fiche"] == []


class TestCritere9LettreAttendLaFiche:
    def test_carte_lettre_attend_la_fiche_apres_generer(
        self, page, front_url, db_path, appels_modele
    ):
        offer_id = 21209
        _insert_offer_retenue(db_path, offer_id)
        _ouvrir(page, front_url, offer_id)

        page.get_by_text("Lettre de motivation", exact=True).first.click()
        with page.expect_response(lambda r: r.url.endswith("/lettre")):
            _bouton(page, "Générer la lettre").click()

        expect(
            page.get_by_text(
                "La lettre partira dès que la fiche entreprise sera terminée."
            )
        ).to_be_visible()
        assert appels_modele["fiche"] == [offer_id]
        assert appels_modele["lettre"] == []
