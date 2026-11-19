"""Tests EXE-209 — navigateur réel (Playwright/Chromium, H7) : la version
anglaise de la lettre vue à l'écran (critères 1, 2, 5, 6, 8, 13 à 16).

Outillage repris de `test_exe202_navigateur.py`. L'API tourne dans un thread
du même process : remplacer `claude_agent_sdk.query` ici remplace le client
qu'elle appelle. Aucun vrai modèle n'est appelé.
"""

import asyncio

import claude_agent_sdk
import pytest
from claude_agent_sdk import ResultMessage
from playwright.sync_api import expect

import orchestrator.job_search.paths as paths_mod
from tests import test_exe202_navigateur as nav
from tests.test_exe206_partir_de_mes_lettres import insert_lettre, insert_offer

navigateur_env = nav.navigateur_env
navigateur = nav.navigateur
page = nav.page
front_url = nav.front_url
db_path = nav.db_path

TEXTE_FR = "Madame, Monsieur,\n\nJe candidate chez Capgemini.\n\nCordialement."
TEXTE_EN = "Dear Sir or Madam,\n\nI am applying to Capgemini.\n\nKind regards."
GENERER = "Générer la version anglaise"
REGENERER = "Régénérer la version anglaise"
MESSAGE_PERIMEE = (
    "La version anglaise date d'avant ta dernière modification du texte français"
)


class _Client:
    def __init__(self):
        self.texte = TEXTE_EN
        self.erreur = None
        self.attente_s = 1.0
        self.nb = 0

    def query(self, *, prompt, options=None, **kwargs):
        self.nb += 1
        client = self

        async def _gen():
            await asyncio.sleep(client.attente_s)
            if client.erreur is not None:
                raise client.erreur
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake",
                total_cost_usd=0.01,
                result=None,
                structured_output={"texte": client.texte},
            )

        return _gen()


@pytest.fixture
def client_modele(monkeypatch, tmp_path):
    c = _Client()
    monkeypatch.setattr(claude_agent_sdk, "query", c.query)
    tournures = tmp_path / "tournures.txt"
    tournures.write_text("", encoding="utf-8")
    monkeypatch.setattr(paths_mod, "LETTRE_TOURNURES_PATH", tournures)
    return c


def _ouvrir(page, front_url, db_path, offer_id):
    insert_offer(db_path, offer_id, title="Ingénieur données", company="Capgemini")
    insert_lettre(db_path, offer_id, texte=TEXTE_FR)
    page.goto(f"{front_url}/offers/{offer_id}")
    nav._open_onglet_lettre(page)
    return nav._onglet(page)


def _editeur_fr(onglet):
    return onglet.locator("textarea:not(#lettre-angle):not([aria-label])")


def _editeur_en(onglet):
    return onglet.get_by_label("Texte anglais de la lettre")


def _bascule(onglet):
    return onglet.get_by_role("group", name="Langue de la lettre")


class TestCriteres1a6:
    def test_generer_attente_bascule_editeur_enregistrer(
        self, page, front_url, db_path, client_modele
    ):
        onglet = _ouvrir(page, front_url, db_path, 4001)
        bouton = onglet.get_by_role("button", name=GENERER)
        expect(bouton).to_be_visible()
        expect(_bascule(onglet)).to_have_count(0)

        bouton.click()
        expect(onglet.get_by_role("status")).to_contain_text("Traduction en cours")
        expect(_bascule(onglet)).to_be_visible()
        expect(onglet.get_by_role("status")).to_have_count(0)
        assert client_modele.nb == 1

        _bascule(onglet).get_by_role("button", name="EN").click()
        expect(_editeur_en(onglet)).to_have_value(TEXTE_EN)

        corrige = TEXTE_EN.replace("Kind regards.", "Best regards.")
        _editeur_en(onglet).fill(corrige)
        onglet.get_by_role("button", name="Enregistrer", exact=True).click()
        expect(_editeur_en(onglet)).to_have_value(corrige)

        page.reload()
        onglet = nav._onglet(page)
        nav._open_onglet_lettre(page)
        _bascule(onglet).get_by_role("button", name="EN").click()
        expect(_editeur_en(onglet)).to_have_value(corrige)
        assert client_modele.nb == 1


class TestCritere8Apercu:
    def test_apercu_bascule_en_mise_en_page_anglaise(
        self, page, front_url, db_path, client_modele, tmp_path, monkeypatch
    ):
        import orchestrator.job_search.pdf.coordonnees as coordonnees_module

        coord = tmp_path / "coordonnees.txt"
        coord.write_text(
            "nom: Grégoire Marchand\nmail: g@example.com\n"
            "telephone: +33 6 00 00 00 00\nville: Bruxelles\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", coord)

        onglet = _ouvrir(page, front_url, db_path, 4002)
        onglet.get_by_role("button", name=GENERER).click()
        expect(_bascule(onglet)).to_be_visible()

        page.reload()
        page.wait_for_load_state("networkidle")
        page.get_by_text("Lettre de motivation", exact=True).first.click()
        groupe = page.get_by_role("group", name="Langue de l'aperçu")
        expect(groupe).to_be_visible()
        cadre = page.frame_locator("iframe[title='Aperçu de la lettre']")
        expect(cadre.locator("body")).to_contain_text("Objet : candidature")

        groupe.get_by_role("button", name="EN").click()
        expect(cadre.locator("body")).to_contain_text(
            "Subject: Application for the position of Ingénieur données"
        )
        expect(cadre.locator("body")).to_contain_text("I am applying to Capgemini.")

        groupe.get_by_role("button", name="FR").click()
        expect(cadre.locator("body")).to_contain_text("Objet : candidature")


class TestCriteres13a15Fraicheur:
    def test_modif_fr_message_puis_regenerer(
        self, page, front_url, db_path, client_modele
    ):
        onglet = _ouvrir(page, front_url, db_path, 4003)
        onglet.get_by_role("button", name=GENERER).click()
        expect(_bascule(onglet)).to_be_visible()
        expect(onglet.get_by_text(MESSAGE_PERIMEE)).to_have_count(0)

        _editeur_fr(onglet).fill(TEXTE_FR + "\n\nPS : disponible.")
        onglet.get_by_role("button", name="Enregistrer", exact=True).click()
        expect(onglet.get_by_text(MESSAGE_PERIMEE)).to_be_visible()
        regenerer = onglet.get_by_role("button", name=REGENERER)
        expect(regenerer).to_be_visible()

        client_modele.texte = TEXTE_EN + "\n\nPS: available."
        regenerer.click()
        expect(onglet.get_by_text(MESSAGE_PERIMEE)).to_have_count(0)
        _bascule(onglet).get_by_role("button", name="EN").click()
        expect(_editeur_en(onglet)).to_have_value(client_modele.texte)
        assert client_modele.nb == 2


class TestCritere16Echec:
    @pytest.mark.parametrize(
        "erreur", [RuntimeError("modèle en panne"), asyncio.TimeoutError()]
    )
    def test_echec_message_fr_intact_bouton_actif(
        self, page, front_url, db_path, client_modele, erreur
    ):
        client_modele.erreur = erreur
        client_modele.attente_s = 0.2
        offer_id = 4004 if isinstance(erreur, RuntimeError) else 4005
        onglet = _ouvrir(page, front_url, db_path, offer_id)
        onglet.get_by_role("button", name=GENERER).click()
        expect(onglet.get_by_text("La traduction a échoué")).to_be_visible()
        expect(_editeur_fr(onglet)).to_have_value(TEXTE_FR)
        expect(onglet.get_by_role("button", name=GENERER)).to_be_enabled()
