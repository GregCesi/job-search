"""Tests EXE-79 — ajout à la main d'une offre par son URL, traité en tâche de fond.

Aucun test ne touche au réseau ni à Ollama : les pages lues sont des fixtures servies
par un faux `requests.get`, et l'extraction est remplacée par un double qui rend des
faits fixés. Aucun test ne lit ni n'écrit sous data/ : base et profil sont en tmp_path.
"""

import asyncio
import json
import shutil
import sqlite3
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from fastapi import HTTPException, Response

import api.ajouts as api_ajouts
import api.db as api_db
import orchestrator.job_search.ajout.service as ajout_service
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.sources.manual as manual
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    RoleLevel,
    SeniorityLevel,
    TechRequirement,
)
from orchestrator.job_search.storage.db import init_db

REPO = Path(__file__).resolve().parent.parent
URL = "https://careers.exemple.test/offres/42"

FACTS_DANS_PERIMETRE = ExtractedFacts(
    seniority_required=SeniorityLevel.intermediate,
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="fastapi", importance="required"),
        TechRequirement(name="kubernetes", importance="nice_to_have"),
    ],
    domain="backend",
)
FACTS_MANAGER = FACTS_DANS_PERIMETRE.model_copy(
    update={"role_level": RoleLevel.manager}
)


def _page(job_posting: dict | None, extra: str = "") -> str:
    bloc = (
        f'<script type="application/ld+json">{json.dumps(job_posting)}</script>'
        if job_posting is not None
        else ""
    )
    return f"<html><head><title>Offre</title>{bloc}</head><body>{extra}</body></html>"


def _job_posting(**overrides) -> dict:
    jp = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Développeur Python backend",
        "description": "<p>Nous cherchons un <b>développeur Python</b> FastAPI.</p>",
        "hiringOrganization": {"@type": "Organization", "name": "Smals"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "Strasbourg",
                "addressCountry": "FR",
            },
        },
        "employmentType": "FULL_TIME",
    }
    jp.update(overrides)
    return jp


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


@pytest.fixture
def extraction(monkeypatch):
    """Double de l'extraction : rend des faits fixés, compte ses appels."""
    appels: list[JobOffer] = []
    state = {"facts": FACTS_DANS_PERIMETRE, "gate": None}

    def _extract(offer, model, host):
        appels.append(offer)
        if state["gate"] is not None:
            state["gate"].wait(timeout=5)
        return state["facts"]

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    return appels, state


@pytest.fixture
def page(monkeypatch):
    """Faux `requests.get` : sert `state['response']`, ou lève `state['raise']`."""
    state: dict = {"response": _FakeResponse(200, _page(_job_posting())), "urls": []}

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


def _ajouter(body: dict) -> tuple[dict, dict, Response]:
    """POST puis attente de la tâche de fond ; rend (réponse POST, état final)."""

    async def _go():
        response = Response()
        created = await api_ajouts.create_ajout(api_ajouts.AjoutIn(**body), response)
        await asyncio.gather(*list(api_ajouts._tasks))
        return created, response

    created, response = asyncio.run(_go())
    return created, api_ajouts.get_ajout(created["id"]), response


def _offer(db_path, offer_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def _count_offers(db_path) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    conn.close()
    return n


# ---------------------------------------------------------------------------
# Critères 1 et 2 — réponse immédiate « en cours », puis « terminé » avec offre et catégorie
# ---------------------------------------------------------------------------


def test_reponse_avant_fin_du_traitement_puis_termine(
    db_path, profil, extraction, page
):
    _, state = extraction
    state["gate"] = threading.Event()

    async def _go():
        response = Response()
        created = await api_ajouts.create_ajout(api_ajouts.AjoutIn(url=URL), response)
        pendant = api_ajouts.get_ajout(created["id"])
        state["gate"].set()
        await asyncio.gather(*list(api_ajouts._tasks))
        return created, response, pendant

    created, response, pendant = asyncio.run(_go())

    assert response.status_code == 202
    assert isinstance(created["id"], int)
    assert created["statut"] == "en_cours"
    assert pendant["statut"] == "en_cours"

    final = api_ajouts.get_ajout(created["id"])
    assert final["statut"] == "termine"
    assert isinstance(final["offer_id"], int)
    row = _offer(db_path, final["offer_id"])
    assert final["categorie"] == row["category"]
    assert final["categorie"] in {"parfait", "reve", "atteignable", "hors"}


# ---------------------------------------------------------------------------
# Critère 3 — titre, entreprise, lieu, description lus dans le bloc, et l'URL envoyée
# ---------------------------------------------------------------------------


def test_offre_porte_les_champs_du_bloc_jobposting(db_path, profil, extraction, page):
    _, final, _ = _ajouter({"url": URL})
    row = _offer(db_path, final["offer_id"])
    assert row["title"] == "Développeur Python backend"
    assert row["company"] == "Smals"
    assert row["location"] == "Strasbourg, FR"
    assert "développeur Python" in row["description"]
    assert "<p>" not in row["description"]
    assert row["url"] == URL
    assert page["urls"] == [URL]


def test_rien_ne_s_invente_entreprise_et_lieu_absents(
    db_path, profil, extraction, page
):
    jp = _job_posting(jobLocationType="TELECOMMUTE")
    del jp["hiringOrganization"]
    del jp["jobLocation"]
    page["response"] = _FakeResponse(200, _page(jp, extra="<h1>Smals Strasbourg</h1>"))
    _, final, _ = _ajouter({"url": URL})
    row = _offer(db_path, final["offer_id"])
    assert row["company"] is None
    assert row["location"] is None


def test_titre_entreprise_lieu_jamais_demandes_au_modele(
    db_path, profil, extraction, page
):
    appels, _ = extraction
    _ajouter({"url": URL})
    assert len(appels) == 1
    assert appels[0].title == "Développeur Python backend"
    assert appels[0].extracted_facts is None


# ---------------------------------------------------------------------------
# Critère 4 — source « manuel », filtrable comme les autres sources
# ---------------------------------------------------------------------------


def test_source_manuel_filtrable(db_path, profil, extraction, page):
    import api.offers as api_offers

    _, final, _ = _ajouter({"url": URL})
    row = _offer(db_path, final["offer_id"])
    assert row["source"] == "manuel"

    kwargs = dict(
        remote=None,
        verdict=None,
        seen_candidat=None,
        filtered_out=None,
        category=None,
        exclude_category=None,
        hors_perimetre=None,
        hp_cause=None,
        exclude_ad_language=None,
        etat_review=None,
        q=None,
        view_profile=None,
        include_remote=None,
        sort="category",
        order="desc",
    )
    manuels = api_offers.list_offers(source="manuel", **kwargs)
    assert [o.id for o in manuels] == [final["offer_id"]]
    assert api_offers.list_offers(source="france_travail", **kwargs) == []


# ---------------------------------------------------------------------------
# Critère 5 — même classement que le /run pour une offre et des faits donnés
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


def _classement(db_path) -> tuple:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT category, techs_matched_json, techs_missing_json, perimetre_causes "
        "FROM offers"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    r = rows[0]
    return (
        r["category"],
        r["techs_matched_json"],
        r["techs_missing_json"],
        r["perimetre_causes"],
    )


@pytest.mark.parametrize("facts", [FACTS_DANS_PERIMETRE, FACTS_MANAGER])
def test_meme_classement_que_le_run(monkeypatch, tmp_path, profil, extraction, facts):
    _, state = extraction
    state["facts"] = facts
    titre, entreprise, lieu = "Développeur Python backend", "Smals", "Strasbourg"
    texte = "Nous cherchons un développeur Python FastAPI."

    run_db = tmp_path / "run.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", run_db)
    offre_run = JobOffer(
        source="france_travail",
        source_id="FT-1",
        fingerprint="fp-run",
        title=titre,
        description=texte,
        company=entreprise,
        location=lieu,
        remote=False,
        contract_type=None,
        url=URL,
        fetched_at=datetime.now(timezone.utc),
    )
    _run_main(monkeypatch, tmp_path, profil, offre_run)

    ajout_db = tmp_path / "ajout.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", ajout_db)
    monkeypatch.setattr(api_db, "DB_PATH", ajout_db)
    conn = sqlite3.connect(ajout_db)
    init_db(conn)
    conn.close()
    _, final, _ = _ajouter(
        {
            "url": URL,
            "texte": texte,
            "titre": titre,
            "entreprise": entreprise,
            "lieu": lieu,
        }
    )
    assert final["statut"] in {"termine", "hors_perimetre"}

    assert _classement(ajout_db) == _classement(run_db)
    if facts is FACTS_MANAGER:
        assert final["statut"] == "hors_perimetre"
        assert final["causes"] == ["mgmt_role"]


# ---------------------------------------------------------------------------
# Critère 6 — stage : « filtrée » avec la raison, offre en base sans catégorie
# ---------------------------------------------------------------------------


def test_stage_filtree(db_path, profil, extraction, page):
    appels, _ = extraction
    page["response"] = _FakeResponse(200, _page(_job_posting(employmentType="INTERN")))
    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "filtree"
    assert final["raison"] == "contract:stage"
    row = _offer(db_path, final["offer_id"])
    assert row["filtered_out"] == 1
    assert row["filter_reason"] == "contract:stage"
    assert row["category"] is None
    assert appels == []


# ---------------------------------------------------------------------------
# Critère 7 — porte hors périmètre : « hors périmètre » avec ses causes
# ---------------------------------------------------------------------------


def test_hors_perimetre_avec_causes(db_path, profil, extraction, page):
    _, state = extraction
    state["facts"] = FACTS_MANAGER.model_copy(update={"techs_required": []})
    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "hors_perimetre"
    assert final["causes"] == ["no_tech", "mgmt_role"]
    row = _offer(db_path, final["offer_id"])
    assert row["category"] is None
    assert json.loads(row["perimetre_causes"]) == ["no_tech", "mgmt_role"]


# ---------------------------------------------------------------------------
# Critère 8 — pas de bloc JobPosting, ou bloc sans titre : « texte à coller »
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "html",
    [
        _page(None, extra="<h1>Développeur Python</h1>"),
        _page({"@context": "https://schema.org", "@type": "Organization"}),
        _page(_job_posting(title="")),
        _page({k: v for k, v in _job_posting().items() if k != "title"}),
    ],
    ids=["sans_bloc", "autre_type", "titre_vide", "sans_titre"],
)
def test_sans_jobposting_texte_a_coller(db_path, profil, extraction, page, html):
    appels, _ = extraction
    page["response"] = _FakeResponse(200, html)
    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "texte_a_coller"
    assert final["offer_id"] is None
    assert _count_offers(db_path) == 0
    assert appels == []


def test_jobposting_dans_un_graph_est_lu(db_path, profil, extraction, page):
    graph = {
        "@context": "https://schema.org",
        "@graph": [{"@type": "WebPage"}, _job_posting()],
    }
    page["response"] = _FakeResponse(200, _page(graph))
    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "termine"


# ---------------------------------------------------------------------------
# Critère 9 — texte collé : offre créée et traitée sans lire la page
# ---------------------------------------------------------------------------


def test_texte_colle_sans_lire_la_page(db_path, profil, extraction, page):
    appels, _ = extraction
    _, final, _ = _ajouter(
        {
            "url": URL,
            "texte": "Nous cherchons un développeur Python FastAPI.",
            "titre": "Développeur Python",
            "entreprise": "EDITX",
            "lieu": "Strasbourg",
        }
    )
    assert page["urls"] == []
    assert final["statut"] == "termine"
    row = _offer(db_path, final["offer_id"])
    assert (row["title"], row["company"], row["location"], row["url"]) == (
        "Développeur Python",
        "EDITX",
        "Strasbourg",
        URL,
    )
    assert row["source"] == "manuel"
    assert row["description"] == "Nous cherchons un développeur Python FastAPI."
    assert row["category"] is not None
    assert len(appels) == 1


# ---------------------------------------------------------------------------
# Critère 10 — URL injoignable ou code HTTP d'erreur : message lisible.
# Remplacé par EXE-82 (critère 8) : l'état final vaut « texte à coller », plus « échec ».
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "panne",
    [
        {"raise": requests.ConnectionError("connexion refusée")},
        {"raise": requests.Timeout("délai")},
        {"response": _FakeResponse(404, "introuvable")},
        {"response": _FakeResponse(503, "indisponible")},
    ],
    ids=["injoignable", "delai", "404", "503"],
)
def test_url_en_echec(db_path, profil, extraction, page, panne):
    page.update(panne)
    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "texte_a_coller"
    assert final["message"]
    assert URL in final["message"]
    assert final["offer_id"] is None
    assert _count_offers(db_path) == 0


def test_echec_http_cite_le_code(db_path, profil, extraction, page):
    page["response"] = _FakeResponse(404, "introuvable")
    _, final, _ = _ajouter({"url": URL})
    assert "404" in final["message"]


# ---------------------------------------------------------------------------
# Critère 11 — empreinte déjà en base : « déjà en base », sans extraction
# ---------------------------------------------------------------------------


def test_deja_en_base(db_path, profil, extraction, page):
    appels, _ = extraction
    _, premier, _ = _ajouter({"url": URL})
    assert premier["statut"] == "termine"
    avant = _count_offers(db_path)
    appels.clear()

    # Même empreinte (titre, entreprise, lieu), autre URL : le recoupement cross-source joue.
    _, second, _ = _ajouter({"url": URL + "?utm=mail"})
    assert second["statut"] == "deja_en_base"
    assert second["offer_id"] == premier["offer_id"]
    assert appels == []
    assert _count_offers(db_path) == avant


def test_deja_en_base_depuis_une_autre_source(db_path, profil, extraction, page):
    from orchestrator.job_search.sources.fingerprint import fingerprint
    from orchestrator.job_search.storage.offers import save_offer

    appels, _ = extraction
    conn = storage_db.get_connection()
    save_offer(
        conn,
        JobOffer(
            source="france_travail",
            source_id="FT-9",
            fingerprint=fingerprint(
                "Développeur Python backend", "Smals", "Strasbourg, FR"
            ),
            title="Développeur Python backend",
            description="x",
            company="Smals",
            location="Strasbourg, FR",
            remote=False,
            contract_type="CDI",
            url="https://francetravail.test/9",
            fetched_at=datetime.now(timezone.utc),
        ),
    )
    existing_id = conn.execute("SELECT id FROM offers").fetchone()[0]
    conn.close()

    _, final, _ = _ajouter({"url": URL})
    assert final["statut"] == "deja_en_base"
    assert final["offer_id"] == existing_id
    assert appels == []
    assert _count_offers(db_path) == 1


# ---------------------------------------------------------------------------
# Critère 12 — ajout orphelin après redémarrage : « échec », jamais « en cours »
# ---------------------------------------------------------------------------


def _insert_ajout(db_path, statut: str, created_at: str, **cols) -> int:
    conn = sqlite3.connect(db_path)
    fields = {"url": URL, "statut": statut, "created_at": created_at, **cols}
    cur = conn.execute(
        f"INSERT INTO ajouts ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
        tuple(fields.values()),
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def test_ajout_orphelin_se_lit_echec(db_path):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ajout_id = _insert_ajout(db_path, "en_cours", now)
    lu = api_ajouts.get_ajout(ajout_id)
    assert lu["statut"] == "echec"
    assert "redémarr" in lu["message"]
    liste = api_ajouts.list_ajouts()
    assert [a["statut"] for a in liste] == ["echec"]


def test_ajout_inconnu_404(db_path):
    with pytest.raises(HTTPException) as exc:
        api_ajouts.get_ajout(999)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Critère 13 — une requête rend les ajouts des dernières 24 heures
# ---------------------------------------------------------------------------


def test_liste_des_ajouts_des_24_dernieres_heures(db_path, profil, extraction, page):
    vieux = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(
        timespec="seconds"
    )
    _insert_ajout(db_path, "termine", vieux)
    _, ok, _ = _ajouter({"url": URL})
    page["response"] = _FakeResponse(404, "introuvable")
    _, ko, _ = _ajouter({"url": "https://careers.exemple.test/offres/43"})

    liste = api_ajouts.list_ajouts()
    assert {a["id"] for a in liste} == {ok["id"], ko["id"]}
    par_id = {a["id"]: a for a in liste}
    for a in liste:
        assert {"id", "statut", "url", "offer_id", "message"} <= a.keys()
    assert par_id[ok["id"]]["statut"] == "termine"
    assert par_id[ok["id"]]["offer_id"] == ok["offer_id"]
    assert par_id[ok["id"]]["url"] == URL
    assert par_id[ko["id"]]["statut"] == "texte_a_coller"
    assert par_id[ko["id"]]["offer_id"] is None
    assert "404" in par_id[ko["id"]]["message"]
