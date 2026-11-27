"""Tests EXE-220 — le vrai lieu de chaque offre, la zone de 40 km, les marques.

Offre témoin : celle de tests/test_exe210_a_postuler.py, au lieu d'annonce
« Belgique ». Chaque test pose sa base (fixture `_isolate_db_path` de conftest.py)
et son profil personnel dans un dossier temporaire (H10). Les offres et leurs
parcours sont posés directement en base : aucun site n'est appelé. Les critères
44 et 45 lancent le run comme tests/test_exe217_fin_de_run.py, sources et réseau
simulés, sans appeler POST /offers/check-expirations.
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

PROFIL = """\
profile_id: test
role_ceiling: ic
seniority_ceiling: intermediate
skills:
  python: { level: 6, desire: 5 }
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: []
  contract_types: []
"""

ONZE_PROVINCES = [
    "Antwerp",
    "Brussels",
    "East Flanders",
    "Flemish Brabant",
    "Hainaut",
    "Liège",
    "Limburg",
    "Luxembourg",
    "Namur",
    "Walloon Brabant",
    "West Flanders",
]
SANDER = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"

_compteur = {"n": 0}


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths, "PROFILE_PATH", chemin)
    return chemin


@pytest.fixture
def client():
    import api.main as api_main

    with TestClient(api_main.app) as c:
        yield c


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(paths.DB_PATH)


def _offre(
    *,
    location="Belgique",
    domain="backend",
    langues=(),
    description="Poste de développeur dans une équipe produit.",
    url="auto",
) -> int:
    """Insère le témoin, sauf ce que le critère change, et rend son id."""
    _compteur["n"] += 1
    n = _compteur["n"]
    fetched = (datetime.now(timezone.utc) - timedelta(days=3, hours=1)).isoformat()
    facts = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": domain,
            "role_level": "ic",
            "langues_requises": list(langues),
        }
    )
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, ad_language, "
            "extracted_facts_json, filtered_out) "
            "VALUES ('actiris', ?, ?, 'Développeur Python', ?, ?, 'directhire', ?, "
            "?, ?, 'fr', ?, 0)",
            (
                f"id-{n}",
                f"fp-{n}",
                f"Acme {n}",
                location,
                f"https://annonce.test/{n}" if url == "auto" else url,
                fetched,
                description,
                facts,
            ),
        )
        return cur.lastrowid


def _parcours(
    offer_id: int,
    *,
    lieu_reel=None,
    code_postal=None,
    provinces=(),
    fin_forme="page",
    fin_adresse="https://employeur.test/poste",
    en_ligne_depuis=None,
    verifiee_le="2026-11-26T08:00:00+00:00",
) -> None:
    """Pose le parcours lu de l'offre, comme la vérification l'aurait écrit."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, "
            "fin_adresse, cle, lieu_reel, code_postal, provinces_json, "
            "en_ligne_depuis, ouverture, verifiee_le, fermeture_json) "
            "VALUES (?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, 'ouverte', ?, NULL)",
            (
                offer_id,
                "2026-11-26T08:00:00+00:00",
                fin_forme,
                fin_adresse,
                f"cle-{offer_id}",
                lieu_reel,
                code_postal,
                json.dumps(list(provinces), ensure_ascii=False),
                en_ligne_depuis,
                verifiee_le,
            ),
        )


def _avec(lieu_reel=None, code_postal=None, provinces=(), **offre) -> int:
    oid = _offre(**offre)
    _parcours(oid, lieu_reel=lieu_reel, code_postal=code_postal, provinces=provinces)
    return oid


def _lignes(client, file=None) -> list[dict]:
    params = {"file": file} if file else {}
    r = client.get("/a-postuler", params=params)
    assert r.status_code == 200, r.text
    return r.json()["lignes"]


def _ligne(client, offer_id, file=None) -> dict:
    for ligne in _lignes(client, file):
        if ligne["id"] == offer_id:
            return ligne
    raise AssertionError(f"offre {offer_id} absente de la file {file}")


def _dans_la_file(client, offer_id, file=None) -> bool:
    return any(li["id"] == offer_id for li in _lignes(client, file))


def _motif(client, offer_id) -> str | None:
    r = client.get(f"/offers/{offer_id}/a-postuler")
    assert r.status_code == 200, r.text
    return r.json()["motif"]


def _dehors(client, offer_id) -> None:
    assert not _dans_la_file(client, offer_id)
    assert not _dans_la_file(client, offer_id, "a_etudier")


def _dehors_lieu(client, offer_id) -> None:
    _dehors(client, offer_id)
    assert _motif(client, offer_id) == "lieu"


# --- Le lieu réel ------------------------------------------------------------


def test_critere_01_lieu_reel_affiche(client):
    oid = _avec("La Hulpe", "1310")
    assert _ligne(client, oid)["lieu"] == "La Hulpe"


def test_critere_02_pas_de_marque_lieu(client):
    oid = _avec("La Hulpe", "1310")
    assert "lieu non précisé" not in _ligne(client, oid)["marques"]


def test_critere_03_sans_parcours(client):
    ligne = _ligne(client, _offre())
    assert ligne["lieu"] == "Belgique"
    assert "lieu non précisé" in ligne["marques"]


def test_critere_04_parcours_sans_lieu(client):
    ligne = _ligne(client, _avec())
    assert ligne["lieu"] == "Belgique"
    assert "lieu non précisé" in ligne["marques"]


def test_critere_05_belgium_onze_provinces(client):
    oid = _avec("Belgium", None, ONZE_PROVINCES)
    ligne = _ligne(client, oid)
    assert ligne["lieu"] == "Belgique"
    assert "lieu non précisé" in ligne["marques"]


# --- La zone, quand le parcours donne un code postal -------------------------


@pytest.mark.parametrize(
    "lieu,code",
    [("Genappe", "1470"), ("Zaventem", "1930"), ("Leuven", "3000")],
    ids=["critere_06", "critere_07", "critere_08"],
)
def test_criteres_06_07_08_restent(client, lieu, code):
    assert _dans_la_file(client, _avec(lieu, code))


@pytest.mark.parametrize(
    "lieu,code",
    [
        ("Herstal", "4040"),
        ("Namur", "5000"),
        ("Charleroi", "6000"),
        ("Gembloux", "5030"),
        ("Acoz", " 6280"),
    ],
    ids=["critere_09", "critere_10", "critere_11", "critere_12", "critere_13"],
)
def test_criteres_09_a_13_sortent(client, lieu, code):
    _dehors_lieu(client, _avec(lieu, code))


def test_critere_14_charleroi_et_bruxelles(client):
    assert _dans_la_file(client, _avec("Charleroi et Bruxelles", "6000"))


def test_critere_15_antwerpen(client):
    _dehors(client, _avec("Antwerpen", "2600"))


def test_critere_16_berchem(client):
    assert _dans_la_file(client, _avec("Berchem", "2600"))


def test_critere_17_pommerloch(client):
    _dehors(client, _avec("Pommerloch, Luxembourg", "L-9638", ["Luxembourg"]))


# --- Sans code postal ----------------------------------------------------------


def test_critere_18_luxembourg(client):
    _dehors_lieu(client, _avec("Luxembourg", None, ["Luxembourg"]))


def test_critere_19_liege_et_luxembourg(client):
    _dehors(client, _avec("Plusieurs sites", None, ["Liège", "Luxembourg"]))


def test_critere_20_namur_et_liege(client):
    assert _dans_la_file(client, _avec("Plusieurs sites", None, ["Namur", "Liège"]))


def test_critere_21_hainaut(client):
    assert _dans_la_file(client, _avec("Hainaut", None, ["Hainaut"]))


def test_critere_22_flemish_brabant(client):
    assert _dans_la_file(client, _avec("Flemish Brabant", None, ["Flemish Brabant"]))


def test_critere_23_gent(client):
    _dehors_lieu(client, _avec("Gent", None, ["East Flanders"]))


# --- Le lieu réel l'emporte sur le lieu de l'annonce --------------------------


def test_critere_24_bruxelles_herstal(client):
    _dehors_lieu(client, _avec("Herstal", "4040", location="Bruxelles"))


def test_critere_25_gand_bruxelles(client):
    oid = _avec("Bruxelles", "1000", location="Gand, Belgique")
    assert _ligne(client, oid)["lieu"] == "Bruxelles"


def test_critere_26_strasbourg(client):
    sans = _offre(location="67 - Strasbourg")
    avec = _avec("Bruxelles", "1000", location="67 - Strasbourg")
    for oid in (sans, avec):
        _dehors_lieu(client, oid)


# --- Le lieu de l'annonce, pour une offre sans parcours lu --------------------


def test_critere_27_leuven(client):
    assert _dans_la_file(client, _offre(location="Leuven"))


def test_critere_28_mechelen_aalst(client):
    ids = [_offre(location=lieu) for lieu in ("Mechelen", "Aalst")]
    for oid in ids:
        assert _dans_la_file(client, oid)


def test_critere_29_quatre_lieux_sortent(client):
    ids = [
        _offre(location=lieu)
        for lieu in ("Charleroi", "Gosselies", "Namur", "Gembloux")
    ]
    for oid in ids:
        _dehors_lieu(client, oid)


def test_critere_30_louvain_la_neuve(client):
    assert _dans_la_file(client, _offre(location="Louvain-la-Neuve, Belgique"))


# --- Ce que dit chaque ligne -------------------------------------------------


def test_critere_31_fin_du_parcours(client):
    oid = _offre()
    _parcours(oid, fin_forme="page", fin_adresse=SANDER)
    ligne = _ligne(client, oid)
    assert ligne["fin_forme"] == "page"
    assert ligne["fin_adresse"] == SANDER


def test_critere_32_en_ligne_depuis(client):
    oid = _offre()
    _parcours(oid, en_ligne_depuis="2026-10-13")
    assert _ligne(client, oid)["en_ligne_depuis"] == "2026-10-13"


def test_critere_33_sans_date_de_mise_en_ligne(client):
    oid = _offre()
    _parcours(oid)
    ligne = _ligne(client, oid)
    assert "en_ligne_depuis" in ligne
    assert ligne["en_ligne_depuis"] is None


def test_critere_34_derniere_verification(client):
    oid = _offre()
    _parcours(oid, verifiee_le="2026-11-25T07:30:00+00:00")
    assert _ligne(client, oid)["verifiee_le"] == "2026-11-25T07:30:00+00:00"


def test_critere_35_tri_sur_le_lieu_affiche(client):
    waterloo = _avec("Waterloo", "1410")
    ixelles = _offre(location="Ixelles")
    r = client.get("/a-postuler", params={"tri": "lieu"})
    assert r.status_code == 200, r.text
    ids = [li["id"] for li in r.json()["lignes"]]
    assert ids.index(ixelles) < ids.index(waterloo)


# --- Les marques ---------------------------------------------------------------


def _jours_avant(jours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=jours)).date().isoformat()


def test_critere_36_sans_lien(client):
    oid = _offre(url=None)
    assert "sans lien" in _ligne(client, oid)["marques"]


def test_critere_37_page_d_accueil(client):
    oid = _offre()
    _parcours(oid, fin_forme="accueil", fin_adresse="https://employeur.test/")
    assert "page d'accueil de l'employeur" in _ligne(client, oid)["marques"]


def test_critere_38_plus_de_6_mois(client):
    oid = _offre()
    _parcours(oid, en_ligne_depuis=_jours_avant(184))
    assert "en ligne depuis plus de 6 mois" in _ligne(client, oid)["marques"]


def test_critere_39_183_jours(client):
    oid = _offre()
    _parcours(oid, en_ligne_depuis=_jours_avant(183))
    assert "en ligne depuis plus de 6 mois" not in _ligne(client, oid)["marques"]


def test_critere_40_jamais_verifiee(client):
    assert "jamais vérifiée" in _ligne(client, _offre())["marques"]


def test_critere_41_parcours_lu(client):
    oid = _offre()
    _parcours(oid)
    assert "jamais vérifiée" not in _ligne(client, oid)["marques"]


def test_critere_42_neerlandais_en_atout(client):
    oid = _offre(
        langues=("néerlandais",),
        description="La connaissance du néerlandais est un atout.",
    )
    assert "néerlandais en atout" in _ligne(client, oid)["marques"]


# --- La file à étudier ---------------------------------------------------------


def test_critere_43_file_a_etudier(client):
    la_hulpe = _avec("La Hulpe", "1310", domain="data_science")
    herstal = _avec("Herstal", "4040", domain="data_science")
    sans_lien = _offre(url=None, domain="data_science")
    assert _ligne(client, la_hulpe, "a_etudier")["lieu"] == "La Hulpe"
    _dehors_lieu(client, herstal)
    assert "sans lien" in _ligne(client, sans_lien, "a_etudier")["marques"]


# --- Après un run ----------------------------------------------------------------

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EDITX_API = "https://api.editx.eu/en/api/editx/job/{num}"
EDITX_20200 = "https://editx.eu/en/job/20200/laravel-developer"


def _rep(adresse: str, texte: str = "", code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(chaine=[(adresse, code)], texte=texte)


def _pages_liege() -> dict:
    consigne = f'<a href="{EDITX_20200}">Postuler</a>'
    eures = json.dumps({"jvProfiles": {"fr": {"applicationInstructions": [consigne]}}})
    editx = json.dumps(
        {
            "applicationType": "url",
            "applicationAction": SANDER,
            "locality": "Liège",
            "postalCode": "4000",
            "areas": [{"label": "Liège"}],
            "onlineDate": {"value": "2026-10-13 06:41:14"},
        }
    )
    return {
        EURES_API.format(id="AAA"): _rep(EURES_API.format(id="AAA"), eures),
        EDITX_API.format(num=20200): _rep(EDITX_API.format(num=20200), editx),
        SANDER: _rep(SANDER),
    }


def _pages_404() -> dict:
    return {EURES_API.format(id="AAA"): _rep(EURES_API.format(id="AAA"), "", 404)}


class Toile:
    def __init__(self, pages: dict) -> None:
        self.pages = pages

    def __call__(self, adresse: str):
        rep = self.pages.get(adresse)
        if rep is None:
            raise requests.exceptions.Timeout(adresse)
        return rep


def _offre_eures() -> int:
    oid = _offre(url="https://europa.eu/eures/portal/jv-se/jv-details/AAA?lang=fr")
    with _conn() as conn:
        conn.execute(
            "UPDATE offers SET source = 'eures', source_id = 'AAA', "
            "description = ? WHERE id = ?",
            ("Poste de développeur dans une équipe produit à pourvoir. " * 5, oid),
        )
    return oid


def _lancer_run(monkeypatch, tmp_path, toile: Toile) -> None:
    import orchestrator.job_search.sources.france_travail as ft

    reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    monkeypatch.setattr(reseau, "lire", toile)
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)
    monkeypatch.setattr(
        expiration_service,
        "check_url",
        lambda url: (None, datetime.now(timezone.utc).isoformat()),
    )
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda host, model: None)

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


def test_critere_44_liege_apres_un_run(client, monkeypatch, tmp_path):
    oid = _offre_eures()
    assert _dans_la_file(client, oid)
    _lancer_run(monkeypatch, tmp_path, Toile(_pages_liege()))
    _dehors_lieu(client, oid)


def test_critere_45_fermee_apres_un_run(client, monkeypatch, tmp_path):
    oid = _offre_eures()
    assert _dans_la_file(client, oid)
    _lancer_run(monkeypatch, tmp_path, Toile(_pages_404()))
    _dehors(client, oid)
    assert _motif(client, oid) == "annonce expirée"
