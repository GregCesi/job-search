"""Tests EXE-172 — le lien vers le site de l'entreprise (critères 1 à 3, preuve
machine).

Aucun test n'appelle un modèle : `query` du SDK Claude Agent (fiche) est remplacé
par une doublure. Aucun test ne lit ni n'écrit sous data/ : la base est un fichier
tmp_path.
"""

import asyncio
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi.testclient import TestClient

import api.db as api_db
import api.fiche as fiche_api
import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.storage.db import init_db


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire."""

    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _fiche_result(points, employeur_site=None, session_id="fiche-session"):
    employeur = {
        "nom": "ACME",
        "entite_precise": None,
        "type_source": "direct",
        "methode": "test",
        "confiance": "sur",
        "urls": [],
    }
    if employeur_site is not None:
        employeur["site"] = employeur_site
    structured = {
        "mode": "entreprise",
        "presentation": "Présentation ACME.",
        "employeur": employeur,
        "points": points,
        "manques": [],
        "alertes": [],
        "sources": [],
    }
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.1,
        result=None,
        structured_output=structured,
    )


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
def client(db_path):
    import api.main as api_main

    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _stub_cascade_employeur(monkeypatch):
    """La cascade d'identification employeur appelle Ollama : hors périmètre de ce
    ticket, et interdit en test. Doublure déterministe, jamais de réseau."""

    def _fake(offer_id, conn, model=None, host=None):
        return CascadeResult(
            nom="ACME",
            entite=None,
            confiance="sur",
            type_source="direct",
            methode="test",
            etape=1,
        )

    monkeypatch.setattr(fiche_service, "identify_employer", _fake)


@pytest.fixture(autouse=True)
def _repertoire_absent_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fiche_prompt, "REPERTOIRE_LETTRE_PATH", tmp_path / "absent" / "repertoire.yaml"
    )


def _insert_offer(db_path, offer_id, description_raw="Texte complet de l'offre."):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, description_raw) VALUES (?, 'test', ?, 'fp', 'Ingénieur H/F', "
            "'ACME', 'Strasbourg', ?)",
            (offer_id, str(offer_id), description_raw),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', '2026-10-01')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche_ancienne(db_path, offer_id):
    """Fiche produite avant EXE-172 (critère 3) : la colonne employeur_site
    n'est pas renseignée."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, 'done', 'Présentation ACME.', '[]', '2026-10-01')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


# --- critère 1 ----------------------------------------------------------------


class TestCritere1AdresseSauvegardeeEtRendue:
    def test_adresse_http_valide_persistee_et_relue_par_l_api(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                        employeur_site="https://acme.test",
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        assert fiche["employeur_site"] == "https://acme.test"


# --- critère 2 ----------------------------------------------------------------


class TestCritere2AdresseSansSchemeHttpEcartee:
    @pytest.mark.parametrize("site", ["ftp://acme.test", "acme.test", "www.acme.test"])
    def test_adresse_sans_http_ou_https_n_est_pas_gardee(
        self, db_path, monkeypatch, site
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                        employeur_site=site,
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        assert fiche["employeur_site"] is None


# --- critère 3 ----------------------------------------------------------------


class TestCritere3AbsenceDAdresseSansErreur:
    """`.get()` plutôt que l'indexation : une fiche d'avant EXE-172 n'a pas la
    clé `employeur_site` du tout, et c'est aussi « sans erreur » (critère 3)
    — pas seulement une fois la colonne ajoutée."""

    def test_reponse_sans_site_lue_sans_erreur(self, db_path, monkeypatch):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        assert fiche.get("employeur_site") is None

    def test_fiche_anterieure_sans_colonne_lue_sans_erreur(self, db_path):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)

        fiche = fiche_api.get_fiche(offer_id)

        assert fiche.get("employeur_site") is None
