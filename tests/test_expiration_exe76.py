"""Tests EXE-76 — vérification d'expiration des offres retenues.

Aucun test n'appelle le réseau : `requests.get` est monkeypatché dans
`orchestrator.job_search.expiration.service`. Aucun test ne lit ni n'écrit
sous data/ : la DB est un fichier tmp_path (DB_PATH monkeypatché dans les deux
modules qui le lisent, comme test_cv_exe63.py).
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
from api.schemas import EmployerUrlIn
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
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-28')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _list_offers(verdict=None):
    """Appel direct de la route : hors requête HTTP, les paramètres `Query(...)`
    non fournis restent des objets `Query`, pas leurs valeurs par défaut — il
    faut donc tous les préciser explicitement."""
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


class TestCritere1UrlEnregistreeEtRelue:
    def test_url_https_relue(self, db_path):
        _insert_offer(db_path, 1)
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example/offre")
        )
        assert api_offers.get_offer(1).employer_url == "https://employeur.example/offre"


class TestCritere2UrlInvalideRefusee:
    def test_url_sans_schema_refusee_et_ancienne_inchangee(self, db_path):
        _insert_offer(db_path, 1)
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example/offre")
        )

        with pytest.raises(HTTPException) as exc:
            api_expiration.set_employer_url(
                1, EmployerUrlIn(url="ftp://pas-http.example")
            )
        assert exc.value.status_code == 422

        assert api_offers.get_offer(1).employer_url == "https://employeur.example/offre"


class TestCritere3UrlVideEfface:
    def test_url_vide_efface(self, db_path):
        _insert_offer(db_path, 1)
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example/offre")
        )
        api_expiration.set_employer_url(1, EmployerUrlIn(url=""))
        assert api_offers.get_offer(1).employer_url is None


class TestCritere4OffreNonRetenueRefusee:
    def test_offre_non_retenue_refusee_et_rien_enregistre(self, db_path):
        _insert_offer(db_path, 1, verdict="rejeté")

        with pytest.raises(HTTPException) as exc:
            api_expiration.set_employer_url(
                1, EmployerUrlIn(url="https://employeur.example/offre")
            )
        assert exc.value.status_code == 409

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT * FROM expirations WHERE offer_id = 1").fetchone()
        conn.close()
        assert row is None


class TestCritere5VerificationLimiteeAuxRetenues:
    def test_verification_interroge_seulement_les_retenues(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://r1.example", verdict="retenu")
        _insert_offer(db_path, 2, url="https://r2.example", verdict="retenu")
        _insert_offer(db_path, 3, url="https://r3.example", verdict="retenu")
        _insert_offer(db_path, 4, url="https://n4.example", verdict="rejeté")
        _insert_offer(db_path, 5, url="https://n5.example", verdict=None)

        calls: list[str] = []
        mapping = {
            "https://r1.example": 200,
            "https://r2.example": 200,
            "https://r3.example": 200,
        }
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get(mapping, calls)
        )

        api_expiration.check_expirations()

        assert set(calls) == {
            "https://r1.example",
            "https://r2.example",
            "https://r3.example",
        }


class TestCritere6Base404Expire:
    def test_base_404_expire(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 404})
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True


class TestCritere7Base410Expire:
    def test_base_410_expire(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 410})
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True


class TestCritere8EmployeurFermeMalgreBaseOuverte:
    def test_employeur_410_expire_malgre_base_200(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://base.example")
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example")
        )
        mapping = {"https://base.example": 200, "https://employeur.example": 410}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True


class TestCritere9RedirectionSuivieJusquauCodeFinal:
    def test_redirection_suivie(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        received: dict = {}

        def fake_get(url, allow_redirects=True, timeout=None):
            received["allow_redirects"] = allow_redirects
            return _FakeResponse(
                404
            )  # code final après redirection, résolu par requests

        monkeypatch.setattr(expiration_service.requests, "get", fake_get)
        api_expiration.check_expirations()
        assert received["allow_redirects"] is True
        assert api_offers.get_offer(1).expired is True


class TestCritere10DeuxUrlOuvertesNonExpiree:
    def test_deux_200_non_expiree(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://base.example")
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example")
        )
        mapping = {"https://base.example": 200, "https://employeur.example": 200}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is False


class TestCritere11CodeInconclusifNeChangePasEtatNonExpire:
    def test_403_ne_change_pas_etat(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 403})
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is False


class TestCritere12CodeInconclusifNeChangePasEtatExpire:
    def test_500_ne_change_pas_etat_deja_expiree(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")

        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 410})
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True

        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 500})
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True


class TestCritere13TimeoutNeChangePasEtat:
    def test_timeout_ne_change_pas_etat(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://o.example": "timeout"}),
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is False


class TestCritere14IsolationEntreOffres:
    def test_erreur_connexion_sur_une_offre_isole_lautre(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://a.example")
        _insert_offer(db_path, 2, url="https://b.example")
        mapping = {"https://a.example": "error", "https://b.example": 410}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))
        api_expiration.check_expirations()
        assert api_offers.get_offer(2).expired is True


class TestCritere15ReouvertureRecalculee:
    def test_deux_200_desexpire(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://base.example")
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example")
        )

        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://base.example": 410, "https://employeur.example": 410}),
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is True

        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://base.example": 200, "https://employeur.example": 200}),
        )
        api_expiration.check_expirations()
        assert api_offers.get_offer(1).expired is False


class TestCritere16AucuneUrlNeCrashePas:
    def test_offre_sans_url_ne_leve_pas_et_etat_inchange(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url=None)
        calls: list[str] = []
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get({}, calls))

        api_expiration.check_expirations()  # ne doit pas lever

        assert calls == []
        assert api_offers.get_offer(1).expired is False


class TestCritere17DetailDesVerificationsExposees:
    def test_detail_expose_code_et_absence_et_date(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://base.example")
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example")
        )
        mapping = {"https://base.example": 404, "https://employeur.example": "error"}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))
        api_expiration.check_expirations()

        detail = api_offers.get_offer(1)
        by_url = {c.url: c for c in detail.expiration_checks}
        assert by_url["https://base.example"].status_code == 404
        assert by_url["https://employeur.example"].status_code is None
        assert all(c.checked_at for c in detail.expiration_checks)


class TestCritere18ListeExposeExpired:
    def test_liste_retenues_expose_expired(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o1.example")
        _insert_offer(db_path, 2, url="https://o2.example")
        monkeypatch.setattr(
            expiration_service.requests,
            "get",
            _fake_get({"https://o1.example": 410, "https://o2.example": 200}),
        )
        api_expiration.check_expirations()

        rows = {r.id: r for r in _list_offers(verdict="retenu")}
        assert rows[1].expired is True
        assert rows[2].expired is False


class TestCritere19OffreExpireeResteRetenue:
    def test_offre_expiree_reste_dans_liste_et_verdict_retenu(
        self, db_path, monkeypatch
    ):
        _insert_offer(db_path, 1, url="https://o.example")
        monkeypatch.setattr(
            expiration_service.requests, "get", _fake_get({"https://o.example": 410})
        )
        api_expiration.check_expirations()

        rows = _list_offers(verdict="retenu")
        assert len(rows) == 1
        assert rows[0].verdict == "retenu"
        assert rows[0].expired is True


class TestCritere20DetailExposeEtatUrlEtDate:
    def test_detail_expose_etat_url_et_date(self, db_path, monkeypatch):
        _insert_offer(db_path, 1, url="https://o.example")
        api_expiration.set_employer_url(
            1, EmployerUrlIn(url="https://employeur.example")
        )
        mapping = {"https://o.example": 200, "https://employeur.example": 200}
        monkeypatch.setattr(expiration_service.requests, "get", _fake_get(mapping))
        api_expiration.check_expirations()

        detail = api_offers.get_offer(1)
        assert detail.expired is False
        assert detail.employer_url == "https://employeur.example"
        assert detail.last_checked_at is not None
