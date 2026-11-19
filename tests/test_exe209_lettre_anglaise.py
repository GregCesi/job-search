"""Tests EXE-209 — version anglaise de la lettre, côté API et service.

Chaque test qui traverse l'appel de traduction remplace le client
(`claude_agent_sdk.query`) : aucun vrai modèle n'est appelé. Base sous
tmp_path (fixture autouse `_isolate_db_path` de conftest). Les critères vus à
l'écran ont leur test navigateur (`test_exe209_navigateur.py`).
"""

import asyncio
import sqlite3
from datetime import date

import claude_agent_sdk
import ollama
import pytest
from claude_agent_sdk import ResultMessage
from fastapi.testclient import TestClient

import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.pdf.lettre_html as lettre_html_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from tests.pdf_inspect import extract_text
from tests.test_exe206_partir_de_mes_lettres import insert_lettre, insert_offer

TEXTE_FR = (
    "Madame, Monsieur,\n\nChez Capgemini, j'ai livré des pipelines Python "
    "pour trois clients.\n\nJe vous prie d'agréer mes salutations distinguées."
)
TEXTE_EN = (
    "Dear Sir or Madam,\n\nAt Capgemini, I delivered Python pipelines for "
    "three clients.\n\nYours faithfully."
)
INTITULE = "Ingénieur données"
MESSAGE_PERIMEE = (
    "La version anglaise date d'avant ta dernière modification du texte français"
)


class _Appels:
    def __init__(self, texte=TEXTE_EN, erreur=None):
        self.texte = texte
        self.erreur = erreur
        self.liste = []

    def query(self, *, prompt, options=None, **kwargs):
        self.liste.append({"prompt": prompt, "options": options})
        appels = self

        async def _gen():
            if appels.erreur is not None:
                raise appels.erreur
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake",
                total_cost_usd=0.01,
                result=None,
                structured_output={"texte": appels.texte},
            )

        return _gen()


@pytest.fixture
def db_path():
    path = storage_db.DB_PATH
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    from api.main import app

    return TestClient(app)


@pytest.fixture
def appels(monkeypatch):
    a = _Appels()
    monkeypatch.setattr(claude_agent_sdk, "query", a.query)

    def _ollama_interdit(*args, **kwargs):
        raise AssertionError("Ollama appelé pour la lettre anglaise")

    monkeypatch.setattr(ollama, "chat", _ollama_interdit)
    monkeypatch.setattr(ollama, "generate", _ollama_interdit)
    return a


def _coordonnees(tmp_path, monkeypatch, ville):
    path = tmp_path / "coordonnees.txt"
    path.write_text(
        "nom: Grégoire Marchand\n"
        "mail: gregoire@example.com\n"
        "telephone: +33 6 00 00 00 00\n"
        f"ville: {ville}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", path)


@pytest.fixture
def deux_novembre(monkeypatch):
    class _Date(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 2)

    monkeypatch.setattr(lettre_html_module, "date", _Date)


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _etat_fr(db_path, offer_id):
    conn = _conn(db_path)
    try:
        row = conn.execute(
            "SELECT texte, marque_pret_at FROM lettres WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()
        versions = conn.execute(
            "SELECT id, texte, origine FROM lettre_versions WHERE offer_id = ? "
            "ORDER BY id",
            (offer_id,),
        ).fetchall()
        offre = conn.execute(
            "SELECT * FROM offers WHERE id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()
    return (
        tuple(row),
        [tuple(v) for v in versions],
        tuple(offre),
    )


def _lettre_prete(db_path, offer_id, marque_pret_at="2026-11-01T10:00:00+00:00"):
    insert_offer(db_path, offer_id, title=INTITULE, company="Capgemini")
    insert_lettre(db_path, offer_id, texte=TEXTE_FR, marque_pret_at=marque_pret_at)


class TestCritere1Bouton:
    @pytest.mark.parametrize("marque", [None, "2026-11-01T10:00:00+00:00"])
    def test_lettre_terminee_generee_ou_prete_montre_generer(
        self, client, db_path, marque
    ):
        _lettre_prete(db_path, 9001, marque_pret_at=marque)
        r = client.get("/offers/9001/lettre/en")
        assert r.status_code == 200
        assert r.json()["bouton"] == "Générer la version anglaise"


class TestCritere3Et4UnAppel:
    def test_un_seul_appel_sonnet_sans_outil_avec_le_texte_fr(
        self, client, db_path, appels
    ):
        _lettre_prete(db_path, 9002)
        r = client.post("/offers/9002/lettre/en")
        assert r.status_code == 200
        assert len(appels.liste) == 1
        options = appels.liste[0]["options"]
        assert options.model == "sonnet"
        assert options.tools == []
        assert options.allowed_tools == []
        assert TEXTE_FR in appels.liste[0]["prompt"]
        assert r.json()["texte"] == TEXTE_EN


class TestCritere6Et7Enregistrer:
    def test_correction_relue_et_fr_intact(self, client, db_path, appels):
        _lettre_prete(db_path, 9003)
        avant = _etat_fr(db_path, 9003)
        assert client.post("/offers/9003/lettre/en").status_code == 200
        assert _etat_fr(db_path, 9003) == avant

        corrige = TEXTE_EN.replace("three", "four")
        r = client.put("/offers/9003/lettre/en/texte", json={"texte": corrige})
        assert r.status_code == 200
        assert client.get("/offers/9003/lettre/en").json()["texte"] == corrige
        assert _etat_fr(db_path, 9003) == avant
        assert len(appels.liste) == 1


class TestCriteres9a12Pdf:
    def test_pdf_anglais_bruxelles(
        self, client, db_path, appels, deux_novembre, tmp_path, monkeypatch
    ):
        _coordonnees(tmp_path, monkeypatch, "Bruxelles")
        _lettre_prete(db_path, 9004)
        client.post("/offers/9004/lettre/en")
        corrige = TEXTE_EN.replace("three", "four")
        client.put("/offers/9004/lettre/en/texte", json={"texte": corrige})

        r = client.get("/offers/9004/lettre/en/pdf")
        assert r.status_code == 200
        texte = extract_text(r.content)
        assert "Brussels, 2 November 2026" in texte
        assert f"Subject: Application for the position of {INTITULE}" in texte
        assert "four clients" in texte
        assert "Capgemini, j'ai" not in texte

    def test_autre_ville_telle_quelle(
        self, client, db_path, appels, deux_novembre, tmp_path, monkeypatch
    ):
        _coordonnees(tmp_path, monkeypatch, "Strasbourg")
        _lettre_prete(db_path, 9005)
        client.post("/offers/9005/lettre/en")
        texte = extract_text(client.get("/offers/9005/lettre/en/pdf").content)
        assert "Strasbourg, 2 November 2026" in texte

    def test_pdf_francais_inchange(
        self, client, db_path, appels, deux_novembre, tmp_path, monkeypatch
    ):
        _coordonnees(tmp_path, monkeypatch, "Bruxelles")
        _lettre_prete(db_path, 9006)
        avant = extract_text(client.get("/offers/9006/lettre/pdf").content)
        assert client.post("/offers/9006/lettre/en").status_code == 200
        apres = extract_text(client.get("/offers/9006/lettre/pdf").content)
        assert apres == avant
        assert "Bruxelles, le 2 novembre 2026" in apres
        assert f"Objet : candidature au poste de {INTITULE}" in apres
        assert "Dear Sir" not in apres


class TestCriteres13a15Fraicheur:
    def test_modif_fr_rend_perimee_puis_regenerer(
        self, client, db_path, appels, tmp_path, monkeypatch
    ):
        tournures = tmp_path / "tournures.txt"
        tournures.write_text("", encoding="utf-8")
        import orchestrator.job_search.paths as paths_mod

        monkeypatch.setattr(paths_mod, "LETTRE_TOURNURES_PATH", tournures)
        _lettre_prete(db_path, 9007)
        client.post("/offers/9007/lettre/en")
        carte = client.get("/offers/9007/lettre/en").json()
        assert carte["message"] is None

        nouveau_fr = TEXTE_FR + "\n\nPS : disponible tout de suite."
        assert (
            client.put(
                "/offers/9007/lettre/texte", json={"texte": nouveau_fr}
            ).status_code
            == 200
        )
        carte = client.get("/offers/9007/lettre/en").json()
        assert carte["message"] == MESSAGE_PERIMEE
        assert carte["bouton"] == "Régénérer la version anglaise"

        appels.texte = TEXTE_EN + "\n\nPS: available right away."
        r = client.post("/offers/9007/lettre/en")
        assert r.status_code == 200
        carte = client.get("/offers/9007/lettre/en").json()
        assert carte["texte"] == appels.texte
        assert carte["message"] is None
        assert nouveau_fr in appels.liste[-1]["prompt"]


class TestCritere16Echec:
    @pytest.mark.parametrize(
        "erreur", [RuntimeError("modèle en panne"), asyncio.TimeoutError()]
    )
    def test_echec_message_et_fr_intact(self, client, db_path, appels, erreur):
        appels.erreur = erreur
        _lettre_prete(db_path, 9008)
        avant = _etat_fr(db_path, 9008)
        r = client.post("/offers/9008/lettre/en")
        assert r.status_code >= 400
        assert r.json()["detail"]
        assert _etat_fr(db_path, 9008) == avant
        carte = client.get("/offers/9008/lettre/en").json()
        assert carte["texte"] is None
        assert carte["bouton"] == "Générer la version anglaise"


class TestCeQuiNeDoitPasArriver:
    def test_aucun_appel_hors_du_clic(self, client, db_path, appels, tmp_path):
        """Lire la carte, enregistrer le français, marquer Prête : aucun appel."""
        _lettre_prete(db_path, 9009, marque_pret_at=None)
        client.get("/offers/9009/lettre/en")
        client.get("/offers/9009/lettre")
        client.get("/offers/9009/pieces")
        assert appels.liste == []

    def test_traduction_hors_lettres_versions_offers(self, client, db_path, appels):
        _lettre_prete(db_path, 9010)
        client.post("/offers/9010/lettre/en")
        conn = _conn(db_path)
        try:
            dumps = "\n".join(
                str(tuple(r))
                for table in ("lettres", "lettre_versions", "offers")
                for r in conn.execute(f"SELECT * FROM {table}").fetchall()
            )
        finally:
            conn.close()
        assert "Dear Sir" not in dumps
