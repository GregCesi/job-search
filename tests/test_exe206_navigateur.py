"""Tests EXE-206 — navigateur réel (Playwright/Chromium, H5) : le bouton
« Partir d'une de mes lettres » sur la carte d'une lettre à décider, la liste
de mes lettres et la copie vue à l'écran (critères 1 à 7, 9, 10).

Outillage repris de `test_exe202_navigateur.py` : front et API lancés une fois
pour le module, base posée par chaque test dans un dossier temporaire.
"""

import re
import sqlite3

from playwright.sync_api import expect

import orchestrator.job_search.paths as paths_mod
from tests import test_exe202_navigateur as nav
from tests.test_exe206_partir_de_mes_lettres import (
    TEXTE_SIA,
    insert_lettre,
    insert_offer,
)

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path

LIBELLE = "Partir d'une de mes lettres"


def _ouvrir_carte(page, front_url, offer_id):
    page.goto(f"{front_url}/offers/{offer_id}")
    nav._open_onglet_lettre(page)
    expect(page.get_by_role("button", name="Générer la lettre")).to_be_visible()


class TestCritere1Et2Bouton:
    def test_bouton_a_cote_des_deux_autres(self, page, front_url, db_path):
        insert_offer(db_path, 3001)
        insert_offer(db_path, 3002)
        insert_lettre(db_path, 3002, marque_pret_at=nav._now())

        _ouvrir_carte(page, front_url, 3001)
        onglet = nav._onglet(page)
        bouton = onglet.get_by_role("button", name=LIBELLE)
        expect(bouton).to_be_visible()
        expect(bouton).to_be_enabled()
        expect(
            onglet.get_by_role(
                "button", name="Ne pas faire de lettre pour cette annonce"
            )
        ).to_be_visible()

    def test_inactif_avec_survol_sans_lettre_prete(self, page, front_url, db_path):
        insert_offer(db_path, 3003)
        insert_offer(db_path, 3004)
        insert_lettre(db_path, 3004, marque_pret_at=None)

        _ouvrir_carte(page, front_url, 3003)
        bouton = nav._onglet(page).get_by_role("button", name=LIBELLE)
        expect(bouton).to_be_visible()
        expect(bouton).to_be_disabled()
        expect(bouton).to_have_attribute(
            "title", "Aucune lettre marquée Prête à reprendre"
        )


class TestCritere3a10ListeEtCopie:
    def test_liste_puis_copie_sans_rechargement(
        self, page, front_url, db_path, tmp_path, monkeypatch
    ):
        tournures = tmp_path / "tournures.txt"
        tournures.write_text("je serais ravi\n", encoding="utf-8")
        monkeypatch.setattr(paths_mod, "LETTRE_TOURNURES_PATH", tournures)

        insert_offer(db_path, 3010)
        insert_offer(db_path, 3011, title="Dev Python", company="Capgemini")
        insert_offer(db_path, 3012, title="Ingénieur IA", company="SFEIR")
        insert_offer(db_path, 3013, title="Data engineer", company="Sia")
        insert_offer(db_path, 3014, title="Autre poste", company="NonPrete")
        insert_lettre(
            db_path,
            3011,
            texte="Lettre Capgemini.",
            marque_pret_at="2026-10-01T10:00:00+00:00",
        )
        insert_lettre(
            db_path, 3012, texte=TEXTE_SIA, marque_pret_at="2026-11-01T10:00:00+00:00"
        )
        insert_lettre(
            db_path,
            3013,
            texte="Lettre Sia.",
            marque_pret_at="2026-10-15T10:00:00+00:00",
        )
        insert_lettre(db_path, 3014, texte="Lettre non prête.", marque_pret_at=None)

        _ouvrir_carte(page, front_url, 3010)
        onglet = nav._onglet(page)
        onglet.get_by_role("button", name=LIBELLE).click()

        liste = onglet.get_by_label("Mes lettres")
        lignes = liste.get_by_role("listitem")
        expect(lignes).to_have_count(3)
        textes = lignes.all_inner_texts()
        assert "SFEIR" in textes[0] and "Ingénieur IA" in textes[0]
        assert "1 novembre 2026" in textes[0]
        assert "Sia" in textes[1] and "Data engineer" in textes[1]
        assert "15 octobre 2026" in textes[1]
        assert "Capgemini" in textes[2] and "Dev Python" in textes[2]
        assert "1 octobre 2026" in textes[2]

        url_avant = page.url
        lignes.nth(0).get_by_role("button").click()

        # Critère 7 : l'éditeur montre le texte copié, mot pour mot.
        editeur = onglet.locator("textarea:not(#lettre-angle)")
        expect(editeur).to_have_value(TEXTE_SIA)
        assert page.url == url_avant
        # Critère 3 : le bouton n'est plus affiché.
        assert onglet.get_by_role("button", name=LIBELLE).count() == 0
        # Critère 10 : nombre de mots et tournures signalées du texte copié.
        expect(
            onglet.get_by_text(re.compile(rf"^Mots\s+{len(TEXTE_SIA.split())}$"))
        ).to_be_visible()
        expect(onglet.get_by_text("Je serais ravi", exact=True)).to_be_visible()
        # Critère 9 : l'historique montre la version « moi ».
        conn = sqlite3.connect(db_path)
        try:
            versions = conn.execute(
                "SELECT origine, texte FROM lettre_versions WHERE offer_id = 3010"
            ).fetchall()
        finally:
            conn.close()
        assert versions == [("moi", TEXTE_SIA)]
