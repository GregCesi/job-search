"""Tests EXE-217, critères 40 à 45 — la vérification à la fin d'un run.

Le run se lance comme dans tests/test_exe100_gemma_lots.py, sources simulées,
sans Ollama. Trois offres sont en base avant le run : le témoin, dans la file
« À postuler » ; D, de domaine data_science, dans « À étudier » ; B, au lieu
d'annonce « 67 - Strasbourg », dans aucune file. Aucun test de ce fichier
n'appelle POST /offers/check-expirations. Aucun n'appelle un site : le point
d'appel réseau du parcours et `check_url` sont simulés.
"""

import importlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
from orchestrator.job_search.expiration import service as expiration_service

REPO = Path(__file__).resolve().parent.parent

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EDITX_API = "https://api.editx.eu/en/api/editx/job/{num}"
EDITX_20200 = (
    "https://editx.eu/en/job/20200/laravel-developer?utm_source=vdab&utm_medium=cpc"
)
SANDER = (
    "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
    "?utm_source=editx&utm_medium=job_board"
)
D_URL = "https://exemple.be/offre/data"
B_URL = "https://exemple.be/offre/strasbourg"


def _rep(adresse: str, texte: str = "", code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(chaine=[(adresse, code)], texte=texte)


def _pages() -> dict:
    consigne = f'<a href="{EDITX_20200.replace("&", "&amp;")}">Postuler</a>'
    eures = json.dumps({"jvProfiles": {"fr": {"applicationInstructions": [consigne]}}})
    editx = json.dumps(
        {
            "applicationType": "url",
            "applicationAction": SANDER,
            "locality": "La Hulpe",
            "postalCode": "1310",
            "areas": [{"label": "Namur"}, {"label": "Walloon Brabant"}],
            "onlineDate": {"value": "2026-10-13 06:41:14"},
        }
    )
    return {
        EURES_API.format(id="AAA"): _rep(EURES_API.format(id="AAA"), eures),
        EDITX_API.format(num=20200): _rep(EDITX_API.format(num=20200), editx),
        SANDER: _rep(SANDER),
        D_URL: _rep(D_URL),
        B_URL: _rep(B_URL),
    }


class Toile:
    def __init__(self, pages: dict, panne: BaseException | None = None) -> None:
        self.pages = pages
        self.panne = panne
        self.demandes: list[str] = []

    def __call__(self, adresse: str):
        self.demandes.append(adresse)
        if self.panne is not None:
            raise self.panne
        rep = self.pages.get(adresse)
        if rep is None:
            raise requests.exceptions.Timeout(adresse)
        return rep


def _simuler(monkeypatch, toile: Toile) -> None:
    try:
        reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    except ImportError:
        return
    monkeypatch.setattr(reseau, "lire", toile)
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)


def _offre(conn, *, source, source_id, url, location, domain) -> int:
    facts = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": domain,
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    fetched = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    cur = conn.execute(
        "INSERT INTO offers (source, source_id, fingerprint, title, company, "
        "location, contract_type, url, fetched_at, description, ad_language, "
        "extracted_facts_json, filtered_out) "
        "VALUES (?, ?, ?, ?, ?, ?, 'directhire', ?, ?, ?, 'fr', ?, 0)",
        (
            source,
            source_id,
            f"fp-{source_id}",
            f"Développeur {source_id}",
            f"Entreprise {source_id}",
            location,
            url,
            fetched,
            "Poste de développeur dans une équipe produit à pourvoir. " * 5,
            facts,
        ),
    )
    return cur.lastrowid


@pytest.fixture
def offres(monkeypatch):
    from orchestrator.job_search.storage.db import init_db

    conn = sqlite3.connect(paths.DB_PATH)
    init_db(conn)
    ids = {
        "temoin": _offre(
            conn,
            source="eures",
            source_id="AAA",
            url="https://europa.eu/eures/portal/jv-se/jv-details/AAA?lang=fr",
            location="Belgique",
            domain="backend",
        ),
        "D": _offre(
            conn,
            source="manuel",
            source_id="D",
            url=D_URL,
            location="Bruxelles",
            domain="data_science",
        ),
        "B": _offre(
            conn,
            source="manuel",
            source_id="B",
            url=B_URL,
            location="67 - Strasbourg",
            domain="backend",
        ),
    }
    conn.commit()
    conn.close()
    return ids


@pytest.fixture
def client():
    import api.main as api_main

    with TestClient(api_main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def _sans_reseau_ni_modele(monkeypatch, tmp_path):
    profil_api = tmp_path / "profil_api.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", profil_api)
    monkeypatch.setattr(paths, "PROFILE_PATH", profil_api)
    monkeypatch.setattr(
        expiration_service,
        "check_url",
        lambda url: (None, datetime.now(timezone.utc).isoformat()),
    )
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda host, model: None)


def _lancer_run(monkeypatch, tmp_path) -> Path:
    import orchestrator.job_search.sources.france_travail as ft

    class _Source:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self):
            return []

    profil = tmp_path / "profil.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", profil)
    monkeypatch.setattr(ft, "FranceTravailSource", _Source)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", "tri-test")
    monkeypatch.setenv("OLLAMA_MODEL", "precision-test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--profile",
            str(profil),
            "--no-remotive",
            "--no-indeed",
            "--no-eures",
            "--no-actiris",
            "--no-forem",
        ],
    )
    run.main()
    return tmp_path / "data"


def _etat(client, offer_id: int) -> str | None:
    r = client.get(f"/offers/{offer_id}/parcours")
    assert r.status_code == 200, r.text
    return r.json()["etat"]


def _files(client) -> tuple[list[int], list[int]]:
    principale = client.get("/a-postuler").json()["lignes"]
    a_etudier = client.get("/a-postuler", params={"file": "a_etudier"}).json()["lignes"]
    return [li["id"] for li in principale], [li["id"] for li in a_etudier]


def _digests(data: Path) -> list[Path]:
    return list(data.glob("digest_*.txt"))


class TestFinDeRun:
    def test_les_trois_offres_sont_ou_le_ticket_les_pose(self, client, offres):
        principale, a_etudier = _files(client)
        assert principale == [offres["temoin"]]
        assert a_etudier == [offres["D"]]

    def test_critere_40_temoin_lu(self, client, offres, monkeypatch, tmp_path):
        _simuler(monkeypatch, Toile(_pages()))
        _lancer_run(monkeypatch, tmp_path)
        assert _etat(client, offres["temoin"]) == "lu"

    def test_critere_41_d_lu(self, client, offres, monkeypatch, tmp_path):
        _simuler(monkeypatch, Toile(_pages()))
        _lancer_run(monkeypatch, tmp_path)
        assert _etat(client, offres["D"]) == "lu"

    def test_critere_42_b_jamais_lu(self, client, offres, monkeypatch, tmp_path):
        toile = Toile(_pages())
        _simuler(monkeypatch, toile)
        _lancer_run(monkeypatch, tmp_path)
        assert _etat(client, offres["temoin"]) == "lu"
        assert _etat(client, offres["B"]) == "jamais lu"
        assert B_URL not in toile.demandes

    def test_critere_43_ligne_de_sortie(
        self, client, offres, monkeypatch, tmp_path, capsys
    ):
        _simuler(monkeypatch, Toile(_pages()))
        _lancer_run(monkeypatch, tmp_path)
        assert "[run] vérification : 2 offres vérifiées" in capsys.readouterr().out

    def test_critere_44_sites_injoignables(
        self, client, offres, monkeypatch, tmp_path, capsys
    ):
        toile = Toile({}, panne=requests.exceptions.ConnectionError("hors ligne"))
        _simuler(monkeypatch, toile)
        data = _lancer_run(monkeypatch, tmp_path)
        assert len(_digests(data)) == 1
        assert "[run] vérification : 2 offres vérifiées" in capsys.readouterr().out
        assert toile.demandes

    def test_critere_45_erreur_inattendue(
        self, client, offres, monkeypatch, tmp_path, capsys
    ):
        toile = Toile({}, panne=RuntimeError("erreur inattendue"))
        _simuler(monkeypatch, toile)
        data = _lancer_run(monkeypatch, tmp_path)
        assert len(_digests(data)) == 1
        assert toile.demandes
        assert "[run] vérification :" in capsys.readouterr().out

    def test_les_files_ne_changent_pas(self, client, offres, monkeypatch, tmp_path):
        avant = _files(client)
        _simuler(monkeypatch, Toile(_pages()))
        _lancer_run(monkeypatch, tmp_path)
        assert _etat(client, offres["temoin"]) == "lu"
        assert _files(client) == avant
