"""Tests EXE-78 — vérification d'expiration étendue aux offres désignées,
sur tout onglet de la vue candidat (pas seulement les retenues).

Mêmes garanties que test_expiration_exe76.py : aucun test n'appelle le réseau
(`requests.get` monkeypatché) ni ne lit/écrit sous data/ (DB_PATH monkeypatché
sur un fichier tmp_path). Avant ce ticket, `check_expirations()` ne prenait
aucun paramètre : chaque test ci-dessous appelle la route avec un `body`
explicite, ce qui lève TypeError contre le code d'avant le ticket (rouge),
et exerce la désignation contre le code d'après (vert).
"""

import sqlite3

import pytest
import requests
from fastapi import HTTPException

import api.db as api_db
import api.expiration as api_expiration
import api.offers as api_offers
import orchestrator.job_search.expiration.service as expiration_service
import orchestrator.job_search.storage.db as storage_db
from api.schemas import CheckExpirationsIn
from orchestrator.job_search.storage.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


def _insert_offer(db_path, offer_id, url="https://o.example", verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, url) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', 'Strasbourg', ?)",
            (offer_id, str(offer_id), url),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-29')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _fake_get(mapping, calls=None):
    def fake_get(url, allow_redirects=True, timeout=None):
        if calls is not None:
            calls.append(url)
        outcome = mapping[url]
        if outcome == "error":
            raise requests.exceptions.ConnectionError("boom")
        if outcome == "timeout":
            raise requests.exceptions.Timeout("boom")
        return _FakeResponse(outcome)

    return fake_get


def _list_offers(verdict=None):
    """Appel direct de la route : hors requête HTTP, les paramètres `Query(...)`
    non fournis restent des objets `Query`, pas leurs valeurs par défaut — il
    faut donc tous les préciser explicitement (cf. test_expiration_exe76.py)."""
    return api_offers.list_offers(
        remote=None,
        source=None,
        verdict=verdict,
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


class TestCritere1DesignationNonRetenuesSeulesLeursUrlInterrogees:
    def test_trois_non_retenues_designees_et_aucune_autre_interrogee(
        self, db_path, monkeypatch
    ):
        _insert_offer(db_path, 1, url="https://n1.example", verdict="rejeté")
        _insert_offer(db_path, 2, url="https://n2.example", verdict=None)
        _insert_offer(db_path, 3, url="https://n3.example", verdict="candidaté")
        _insert_offer(db_path, 4, url="https://r4.example", verdict="retenu")

        calls: list[str] = []
        mapping = {
            "https://n1.example": 200,
            "https://n2.example": 200,
            "https://n3.example": 200,
            "https://r4.example": 200,
        }
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get(mapping, calls)
        )

        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1, 2, 3]))

        assert set(calls) == {
            "https://n1.example",
            "https://n2.example",
            "https://n3.example",
        }


class TestCritere2DesignationMixteRetenueEtNonRetenueExpireLesDeux:
    def test_designation_410_expire_retenue_et_non_retenue(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://r.example", verdict="retenu")
        _insert_offer(db_path, 2, url="https://n.example", verdict="rejeté")

        mapping = {"https://r.example": 410, "https://n.example": 410}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))

        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1, 2]))

        assert api_offers.get_offer(1).expired is True
        assert api_offers.get_offer(2).expired is True


class TestCritere3NonRetenueDesigneeSeuleSonUrlDeBaseInterrogee:
    def test_non_retenue_designee_une_seule_url_interrogee(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example", verdict="rejeté")

        calls: list[str] = []
        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://o.example": 200}, calls),
        )

        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))

        assert calls == ["https://o.example"]


class TestCritere4SansDesignationSeulesLesRetenuesVerifieesCommeAvant:
    def test_sans_designation_seules_les_retenues_interrogees(
        self, db_path, monkeypatch
    ):
        _insert_offer(db_path, 1, url="https://r1.example", verdict="retenu")
        _insert_offer(db_path, 2, url="https://n2.example", verdict="rejeté")
        _insert_offer(db_path, 3, url="https://n3.example", verdict=None)

        calls: list[str] = []
        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://r1.example": 200}, calls),
        )

        api_expiration.check_expirations(body=CheckExpirationsIn())

        assert calls == ["https://r1.example"]


class TestCritere5DesignationAvecOffreInexistanteRefusee:
    def test_offre_inexistante_parmi_dautres_refusee_et_rien_interroge(
        self, db_path, monkeypatch
    ):
        _insert_offer(db_path, 1, url="https://n1.example", verdict="rejeté")

        calls: list[str] = []
        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://n1.example": 200}, calls),
        )

        with pytest.raises(HTTPException) as exc:
            api_expiration.check_expirations(
                body=CheckExpirationsIn(offer_ids=[1, 999])
            )
        assert exc.value.status_code == 404

        assert calls == []


class TestCritere6NonRetenueExpireeGardeVerdictEtResteListee:
    def test_non_retenue_expiree_garde_verdict_et_reste_listee(
        self, db_path, monkeypatch
    ):
        _insert_offer(db_path, 1, url="https://n.example", verdict="rejeté")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://n.example": 410})
        )

        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))

        rows = {r.id: r for r in _list_offers()}
        assert rows[1].verdict == "rejeté"
        assert rows[1].expired is True


class TestCritere7DetailNonRetenueExpireeExposeEtatDateEtCode:
    def test_detail_non_retenue_expose_etat_date_et_code(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://n.example", verdict="rejeté")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://n.example": 404})
        )

        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))

        detail = api_offers.get_offer(1)
        assert detail.expired is True
        assert detail.last_checked_at is not None
        assert len(detail.expiration_checks) == 1
        assert detail.expiration_checks[0].status_code == 404


class TestCritere8ReglesExpirationIdentiquesPourOffreDesignee:
    def test_410_expire_500_conserve_200_desexpire(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://n.example", verdict="rejeté")

        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://n.example": 410})
        )
        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))
        assert api_offers.get_offer(1).expired is True

        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://n.example": 500})
        )
        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))
        assert api_offers.get_offer(1).expired is True

        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://n.example": 200})
        )
        api_expiration.check_expirations(body=CheckExpirationsIn(offer_ids=[1]))
        assert api_offers.get_offer(1).expired is False
