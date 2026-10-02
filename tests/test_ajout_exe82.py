"""Tests EXE-82 — texte d'offre collé avec ou sans URL ni titre, appel d'identification.

Aucun test ne touche au réseau ni à Ollama : les pages sont des fixtures servies par un
faux `requests.get`, et `ollama.Client` est remplacé par un double qui rend des réponses
fixées et compte ses appels. Le double reconnaît l'extraction à son prompt système ;
tout autre appel est l'appel d'identification. Base, profil et traces sont en tmp_path.
"""

import asyncio
import json
import shutil
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi import Response

import api.ajouts as api_ajouts
import api.db as api_db
import orchestrator.job_search.ajout.service as ajout_service
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.sources.manual as manual
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.sources.fingerprint import fingerprint
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.offers import save_offer

REPO = Path(__file__).resolve().parent.parent
URL = "https://careers.exemple.test/offres/42"
TEXTE = (
    "Développeur Python backend chez Smals, à Strasbourg.\n"
    "Nous cherchons un développeur Python FastAPI. Kubernetes est un plus."
)
FAITS = json.dumps(
    {
        "seniority_required": "intermediate",
        "techs_required": [
            {"name": "python", "importance": "core"},
            {"name": "fastapi", "importance": "required"},
        ],
        "domain": "backend",
        "role_level": "ic",
        "langues_requises": [],
    }
)
IDENTIFIE = json.dumps(
    {"titre": "Développeur Python backend", "entreprise": "Smals", "lieu": "Strasbourg"}
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def profil(tmp_path, monkeypatch):
    path = tmp_path / "profil.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", path)
    monkeypatch.setattr(ajout_service, "PROFILE_PATH", path)
    return path


@pytest.fixture(autouse=True)
def traces(tmp_path, monkeypatch):
    """Aucune trace n'est écrite sous data/ : extraction et identification en tmp_path."""
    extraction = tmp_path / "traces" / "extract_facts.jsonl"
    monkeypatch.setattr(extractor, "TRACE_PATH", extraction)
    identification = tmp_path / "traces" / "identify_offer.jsonl"
    try:
        import orchestrator.job_search.ajout.identification as ident

        monkeypatch.setattr(ident, "TRACE_PATH", identification)
    except ImportError:
        pass
    return {"extraction": extraction, "identification": identification}


@pytest.fixture
def ollama_double(monkeypatch):
    """Double de `ollama.Client` : rend des réponses fixées, compte ses appels."""
    state: dict = {
        "identification": IDENTIFIE,
        "extraction": FAITS,
        "appels": [],
        "gate": None,
    }

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def chat(self, *, model, messages, **kwargs):
            system = messages[0]["content"]
            kind = (
                "extraction" if system == extractor._SYSTEM_PROMPT else "identification"
            )
            state["appels"].append((kind, messages))
            if kind == "extraction" and state["gate"] is not None:
                state["gate"].wait(timeout=5)
            return SimpleNamespace(message=SimpleNamespace(content=state[kind]))

    monkeypatch.setattr("ollama.Client", _Client)
    # EXE-99 : ce double n'implémente pas `.list()` — le contrôle de
    # disponibilité des modèles du /run est neutralisé, ces tests ne parlent
    # jamais à un Ollama réel.
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    return state


def _kinds(state) -> list[str]:
    return [kind for kind, _ in state["appels"]]


@pytest.fixture
def page(monkeypatch):
    state: dict = {"response": _FakeResponse(200, "<html></html>"), "urls": []}

    def _get(url, **kwargs):
        state["urls"].append(url)
        if "raise" in state:
            raise state["raise"]
        return state["response"]

    monkeypatch.setattr(manual.requests, "get", _get)
    return state


@pytest.fixture(autouse=True)
def _reset_running():
    api_ajouts._running.clear()
    yield
    api_ajouts._running.clear()


def _ajouter(body: dict) -> tuple[dict, dict]:
    async def _go():
        created = await api_ajouts.create_ajout(api_ajouts.AjoutIn(**body), Response())
        await asyncio.gather(*list(api_ajouts._tasks))
        return created

    created = asyncio.run(_go())
    return created, api_ajouts.get_ajout(created["id"])


def _offers(db_path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM offers ORDER BY id").fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# Critère 1 — texte sans URL ni titre : réponse avant la fin, état « en cours »
# ---------------------------------------------------------------------------


def test_texte_seul_reponse_avant_fin(db_path, profil, ollama_double, page):
    ollama_double["gate"] = threading.Event()

    async def _go():
        response = Response()
        created = await api_ajouts.create_ajout(
            api_ajouts.AjoutIn(texte=TEXTE), response
        )
        pendant = api_ajouts.get_ajout(created["id"])
        ollama_double["gate"].set()
        await asyncio.gather(*list(api_ajouts._tasks))
        return created, response, pendant

    created, response, pendant = asyncio.run(_go())
    assert response.status_code == 202
    assert created["statut"] == "en_cours"
    assert pendant["statut"] == "en_cours"
    assert api_ajouts.get_ajout(created["id"])["statut"] == "termine"


def test_ni_url_ni_texte_refuse():
    with pytest.raises(ValueError):
        api_ajouts.AjoutIn()
    with pytest.raises(ValueError):
        api_ajouts.AjoutIn(url="  ", texte="  ")


# ---------------------------------------------------------------------------
# Critère 2 — sans titre : une identification, avant l'extraction, champs repris
# ---------------------------------------------------------------------------


def test_identification_une_fois_avant_extraction(db_path, profil, ollama_double, page):
    _, final = _ajouter({"texte": TEXTE})
    assert _kinds(ollama_double) == ["identification", "extraction"]
    assert final["statut"] == "termine"
    [row] = _offers(db_path)
    assert (row["title"], row["company"], row["location"]) == (
        "Développeur Python backend",
        "Smals",
        "Strasbourg",
    )
    assert row["id"] == final["offer_id"]
    assert row["source"] == "manuel"
    assert page["urls"] == []


# ---------------------------------------------------------------------------
# Critère 3 — titre seul rendu : entreprise et lieu vides
# ---------------------------------------------------------------------------


def test_identification_titre_seul(db_path, profil, ollama_double, page):
    ollama_double["identification"] = json.dumps(
        {"titre": "Développeur Python backend", "entreprise": None, "lieu": ""}
    )
    _, final = _ajouter({"texte": TEXTE})
    [row] = _offers(db_path)
    assert row["id"] == final["offer_id"]
    assert row["title"] == "Développeur Python backend"
    assert row["company"] is None
    assert row["location"] is None


# ---------------------------------------------------------------------------
# Critère 4 — titre saisi : pas d'identification, champs saisis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "saisie",
    [
        {"titre": "Data engineer", "entreprise": "EDITX", "lieu": "Colmar"},
        {"titre": "Data engineer"},
    ],
    ids=["titre_entreprise_lieu", "titre_seul"],
)
def test_titre_saisi_sans_identification(db_path, profil, ollama_double, page, saisie):
    _, final = _ajouter({"texte": TEXTE, **saisie})
    assert "identification" not in _kinds(ollama_double)
    [row] = _offers(db_path)
    assert row["id"] == final["offer_id"]
    assert row["title"] == "Data engineer"
    assert row["company"] == saisie.get("entreprise")
    assert row["location"] == saisie.get("lieu")


# ---------------------------------------------------------------------------
# Critère 5 — pas de titre, ou réponse illisible : « échec », pas d'extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reponse",
    [
        json.dumps({"titre": "", "entreprise": "Smals", "lieu": "Strasbourg"}),
        json.dumps({"entreprise": "Smals"}),
        json.dumps({"titre": None}),
        "Je ne sais pas.",
        "",
    ],
    ids=["titre_vide", "sans_titre", "titre_null", "texte_libre", "vide"],
)
def test_identification_sans_titre_echec(db_path, profil, ollama_double, page, reponse):
    ollama_double["identification"] = reponse
    _, final = _ajouter({"texte": TEXTE})
    assert final["statut"] == "echec"
    assert "titre" in final["message"].lower()
    assert "saisi" in final["message"].lower()
    assert _kinds(ollama_double) == ["identification"]
    assert _offers(db_path) == []
    assert final["offer_id"] is None


# ---------------------------------------------------------------------------
# Critère 6 — empreinte après identification déjà en base : « déjà en base »
# ---------------------------------------------------------------------------


def test_empreinte_identifiee_deja_en_base(db_path, profil, ollama_double, page):
    conn = storage_db.get_connection()
    save_offer(
        conn,
        JobOffer(
            source="france_travail",
            source_id="FT-9",
            fingerprint=fingerprint(
                "Développeur Python backend", "Smals", "Strasbourg"
            ),
            title="Développeur Python backend",
            description="x",
            company="Smals",
            location="Strasbourg",
            remote=False,
            contract_type="CDI",
            url="https://francetravail.test/9",
            fetched_at=datetime.now(timezone.utc),
        ),
    )
    existing_id = conn.execute("SELECT id FROM offers").fetchone()[0]
    conn.close()

    _, final = _ajouter({"texte": TEXTE})
    assert final["statut"] == "deja_en_base"
    assert final["offer_id"] == existing_id
    assert _kinds(ollama_double) == ["identification"]
    assert len(_offers(db_path)) == 1


# ---------------------------------------------------------------------------
# Critère 7 — prompt d'extraction identique à celui d'une offre venue d'une source
# Critère 11 — un /run n'appelle jamais l'identification
# ---------------------------------------------------------------------------


class _UneOffreSource:
    offre: JobOffer | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return [self.offre]


def _run_main(monkeypatch, tmp_path, profil_path, offre: JobOffer) -> None:
    import orchestrator.job_search.run as run
    import orchestrator.job_search.sources.france_travail as ft

    _UneOffreSource.offre = offre
    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--profile",
            str(profil_path),
            "--no-remotive",
            "--no-indeed",
            "--no-eures",
        ],
    )
    run.main()


def _offre_de_source() -> JobOffer:
    return JobOffer(
        source="france_travail",
        source_id="FT-1",
        fingerprint="fp-run",
        title="Développeur Python backend",
        description=TEXTE,
        company="Smals",
        location="Strasbourg",
        remote=False,
        contract_type=None,
        url=URL,
        fetched_at=datetime.now(timezone.utc),
    )


def test_prompt_extraction_identique_a_une_source(
    monkeypatch, tmp_path, profil, ollama_double, page
):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "run.sqlite")
    _run_main(monkeypatch, tmp_path, profil, _offre_de_source())
    [(kind, run_messages)] = ollama_double["appels"]
    assert kind == "extraction"

    ollama_double["appels"].clear()
    ajout_db = tmp_path / "ajout.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", ajout_db)
    monkeypatch.setattr(api_db, "DB_PATH", ajout_db)
    conn = sqlite3.connect(ajout_db)
    init_db(conn)
    conn.close()
    _, final = _ajouter({"texte": TEXTE})
    assert final["statut"] == "termine"
    extractions = [m for k, m in ollama_double["appels"] if k == "extraction"]
    assert len(extractions) == 1
    assert json.dumps(extractions[0]).encode() == json.dumps(run_messages).encode()


def test_run_n_appelle_jamais_l_identification(
    monkeypatch, tmp_path, profil, ollama_double
):
    monkeypatch.setattr(storage_db, "DB_PATH", tmp_path / "run.sqlite")
    _run_main(monkeypatch, tmp_path, profil, _offre_de_source())
    assert _kinds(ollama_double) == ["extraction"]


# ---------------------------------------------------------------------------
# Critère 8 — URL en erreur HTTP ou injoignable : « texte à coller », cause dite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "panne, cause",
    [
        ({"response": _FakeResponse(403, "interdit")}, "403"),
        ({"response": _FakeResponse(404, "introuvable")}, "404"),
        ({"response": _FakeResponse(503, "indisponible")}, "503"),
        ({"raise": requests.ConnectionError("refusée")}, "ConnectionError"),
        ({"raise": requests.Timeout("délai")}, "Timeout"),
    ],
    ids=["403", "404", "503", "injoignable", "delai"],
)
def test_url_en_erreur_texte_a_coller(
    db_path, profil, ollama_double, page, panne, cause
):
    page.update(panne)
    _, final = _ajouter({"url": URL})
    assert final["statut"] == "texte_a_coller"
    assert cause in final["message"]
    assert final["offer_id"] is None
    assert _offers(db_path) == []
    assert ollama_double["appels"] == []


# ---------------------------------------------------------------------------
# Critère 9 — URL portée si envoyée, jamais inventée sinon
# ---------------------------------------------------------------------------


def test_texte_avec_url_porte_l_url(db_path, profil, ollama_double, page):
    _, final = _ajouter({"url": URL, "texte": TEXTE})
    assert final["statut"] == "termine"
    [row] = _offers(db_path)
    assert row["url"] == URL
    assert page["urls"] == []


def test_texte_sans_url_n_a_pas_d_url(db_path, profil, ollama_double, page):
    _, final = _ajouter({"texte": TEXTE})
    assert final["statut"] == "termine"
    [row] = _offers(db_path)
    assert row["url"] is None


# ---------------------------------------------------------------------------
# Critère 10 — l'état d'un ajout rend l'URL et le texte envoyés
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"url": URL},
        {"texte": TEXTE},
        {"url": URL, "texte": TEXTE, "titre": "Data engineer"},
    ],
    ids=["url", "texte", "url_texte"],
)
def test_etat_rend_url_et_texte(db_path, profil, ollama_double, page, body):
    page["response"] = _FakeResponse(403, "interdit")
    created, final = _ajouter(body)
    for etat in (final, api_ajouts.list_ajouts()[0]):
        assert etat["url"] == body.get("url")
        assert etat["texte"] == body.get("texte")


# ---------------------------------------------------------------------------
# Critère 12 — l'identification est tracée : prompt système, utilisateur, réponse
# ---------------------------------------------------------------------------


def test_identification_tracee(db_path, profil, ollama_double, page, traces):
    _ajouter({"texte": TEXTE})
    [(kind, messages), _] = ollama_double["appels"]
    assert kind == "identification"
    [ligne] = traces["identification"].read_text(encoding="utf-8").splitlines()
    trace = json.loads(ligne)
    assert trace["prompt_system"] == messages[0]["content"]
    assert trace["prompt_user"] == messages[1]["content"]
    assert TEXTE in trace["prompt_user"]
    assert trace["raw_response"] == IDENTIFIE


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — l'identification ne rend rien qui entre au scoring
# ---------------------------------------------------------------------------


def test_identification_ne_rend_que_titre_entreprise_lieu(
    db_path, profil, ollama_double, page
):
    ollama_double["identification"] = json.dumps(
        {
            "titre": "Développeur Python backend",
            "entreprise": "Smals",
            "lieu": "Strasbourg",
            "seniority_required": "senior",
            "techs_required": ["java"],
            "domain": "embedded",
            "langues_requises": ["allemand"],
        }
    )
    _ajouter({"texte": TEXTE})
    [row] = _offers(db_path)
    facts = json.loads(row["extracted_facts_json"])
    assert facts["seniority_required"] == "intermediate"
    assert [t["name"] for t in facts["techs_required"]] == ["python", "fastapi"]
    assert facts["domain"] == "backend"
    assert facts["langues_requises"] == []
