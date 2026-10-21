"""Tests EXE-193 — l'API du module d'états du suivi des candidatures
(critères 12-17). DB sous `tmp_path`, aucun appel modèle ni réseau."""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.db as api_db
import api.pieces as api_pieces
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.expiration.service import run_expiration_check
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
def _no_real_cascade(monkeypatch):
    """Aucun test ne doit appeler le modèle : la cascade de retenue (fiche +
    CV) est un no-op par défaut ; les tests du critère 14 la remplacent par
    leur propre espion."""
    import api.cascade as cascade

    async def _noop(offer_id):
        return []

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _insert_offer(db_path, offer_id, url=None, title="Titre"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, url) "
            "VALUES (?, 'test', ?, ?, ?, ?)",
            (offer_id, str(offer_id), f"fp{offer_id}", title, url),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_pieces_pretes(db_path, offer_id):
    # La cascade réelle du geste "retenir" peut déjà avoir posé une ligne
    # `cvs`/`lettres` (pending) en tâche de fond : upsert, jamais un INSERT nu.
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?) ON CONFLICT(offer_id) DO UPDATE SET "
            "statut = 'done', marque_pret_at = excluded.marque_pret_at",
            (offer_id, _now(), _now()),
        )
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?) ON CONFLICT(offer_id) DO UPDATE SET "
            "statut = 'done', marque_pret_at = excluded.marque_pret_at",
            (offer_id, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()


class TestCritere12ListeEtDetailRendentTriEtapeEtGestes:
    def test_liste_rend_etape_et_gestes_permis(self, client, db_path):
        _insert_offer(db_path, 1)
        client.put("/offers/1/verdict", json={"status": "retenu"})

        rows = client.get("/offers", params={"verdict": "retenu"}).json()
        offer = next(r for r in rows if r["id"] == 1)
        assert offer["verdict"] == "retenu"
        assert offer["etape"] == "retenue"
        assert "abandonner" in offer["gestes_permis"]
        # EXE-197, critère 1 : permis même pièces pas prêtes, avertissement seul.
        assert "marquer_envoyee" in offer["gestes_permis"]

    def test_detail_rend_etape_et_gestes_permis(self, client, db_path):
        _insert_offer(db_path, 2)
        client.put("/offers/2/verdict", json={"status": "retenu"})
        _mark_pieces_pretes(db_path, 2)

        detail = client.get("/offers/2").json()
        assert detail["verdict"] == "retenu"
        assert detail["etape"] == "prete_a_l_envoi"
        assert "marquer_envoyee" in detail["gestes_permis"]

    def test_offre_a_trier_rend_retenir_et_ecarter(self, client, db_path):
        _insert_offer(db_path, 3)
        detail = client.get("/offers/3").json()
        assert detail["verdict"] is None
        assert detail["etape"] is None
        assert set(detail["gestes_permis"]) == {"retenir", "ecarter"}


class TestCritere13GesteRefuseRepond409:
    def test_geste_refuse_au_niveau_module(self, db_path):
        _insert_offer(db_path, 4)
        conn = api_db.get_conn()
        try:
            with pytest.raises(suivi_etats.GesteRefuse) as exc_info:
                suivi_storage.appliquer_geste(conn, 4, suivi_etats.MARQUER_ENVOYEE)
        finally:
            conn.close()
        # EXE-194, critère 20 : libellé, jamais code interne (H4 du ticket).
        assert "à trier" in str(exc_info.value)
        assert "Marquer envoyée" in str(exc_info.value)

    def test_marquer_envoyee_409_si_offre_pas_retenue(self, db_path):
        _insert_offer(db_path, 5)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(5, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409

    def test_route_geste_repond_409_avec_message_etat_et_geste(self, client, db_path):
        _insert_offer(db_path, 41)  # à trier : "marquer_envoyee" hors table

        resp = client.post(
            "/offers/41/geste", json={"geste": suivi_etats.MARQUER_ENVOYEE}
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        # EXE-194, critère 20 : libellé, jamais code interne (H4 du ticket).
        assert suivi_etats.LIBELLES_ETATS[suivi_etats.A_TRIER] in detail
        assert suivi_etats.LIBELLES_GESTES[suivi_etats.MARQUER_ENVOYEE] in detail


class TestCritere13ChaqueGesteDeLaTableSappliqueParLApi:
    def test_parcours_complet_de_la_table_jusquau_terminal(self, client, db_path):
        _insert_offer(db_path, 42)

        def _poser_pieces_pretes():
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
                    "VALUES (42, 'done', ?, ?) ON CONFLICT(offer_id) DO UPDATE SET "
                    "statut='done', marque_pret_at=excluded.marque_pret_at",
                    (_now(), _now()),
                )
                conn.execute(
                    "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
                    "VALUES (42, 'done', ?, ?) ON CONFLICT(offer_id) DO UPDATE SET "
                    "statut='done', marque_pret_at=excluded.marque_pret_at",
                    (_now(), _now()),
                )
                conn.commit()
            finally:
                conn.close()

        def _geste(g):
            resp = client.post("/offers/42/geste", json={"geste": g})
            assert resp.status_code == 200, resp.text
            return resp.json()["etat"]

        assert _geste(suivi_etats.RETENIR) == suivi_etats.RETENUE
        _poser_pieces_pretes()
        assert _geste(suivi_etats.MARQUER_ENVOYEE) == suivi_etats.CANDIDATURE_ENVOYEE
        assert _geste(suivi_etats.RELANCER) == suivi_etats.CANDIDATURE_ENVOYEE
        assert _geste(suivi_etats.ENTRETIEN_GESTE) == suivi_etats.ENTRETIEN
        assert _geste(suivi_etats.RELANCER) == suivi_etats.ENTRETIEN
        assert _geste(suivi_etats.OFFRE_RECUE_GESTE) == suivi_etats.OFFRE_RECUE

        # Terminal : plus aucun geste de la table (sauf "annuler").
        resp = client.post("/offers/42/geste", json={"geste": suivi_etats.RELANCER})
        assert resp.status_code == 409

    def test_annuler_par_la_route(self, client, db_path):
        _insert_offer(db_path, 43)
        assert (
            client.post("/offers/43/geste", json={"geste": suivi_etats.RETENIR}).json()[
                "etat"
            ]
            == suivi_etats.RETENUE
        )

        resp = client.post("/offers/43/geste", json={"geste": suivi_etats.ANNULER})
        assert resp.status_code == 200
        assert resp.json()["etat"] == suivi_etats.A_TRIER

    def test_ecarter_puis_remettre_a_trier(self, client, db_path):
        _insert_offer(db_path, 44)
        assert (
            client.post("/offers/44/geste", json={"geste": suivi_etats.ECARTER}).json()[
                "etat"
            ]
            == suivi_etats.ECARTEE
        )
        resp = client.post(
            "/offers/44/geste", json={"geste": suivi_etats.REMETTRE_A_TRIER}
        )
        assert resp.json()["etat"] == suivi_etats.A_TRIER

    def test_sans_suite_et_refuser_et_abandonner(self, client, db_path):
        _insert_offer(db_path, 45)
        client.post("/offers/45/geste", json={"geste": suivi_etats.RETENIR})
        assert (
            client.post(
                "/offers/45/geste", json={"geste": suivi_etats.ABANDONNER}
            ).json()["etat"]
            == suivi_etats.ABANDONNEE
        )

        _insert_offer(db_path, 46)
        client.post("/offers/46/geste", json={"geste": suivi_etats.RETENIR})
        _poser = sqlite3.connect(db_path)
        _poser.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (46, 'done', ?, ?)",
            (_now(), _now()),
        )
        _poser.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (46, 'done', ?, ?)",
            (_now(), _now()),
        )
        _poser.commit()
        _poser.close()
        client.post("/offers/46/geste", json={"geste": suivi_etats.MARQUER_ENVOYEE})
        assert (
            client.post(
                "/offers/46/geste", json={"geste": suivi_etats.SANS_SUITE_GESTE}
            ).json()["etat"]
            == suivi_etats.SANS_SUITE
        )

        _insert_offer(db_path, 47)
        client.post("/offers/47/geste", json={"geste": suivi_etats.RETENIR})
        _poser = sqlite3.connect(db_path)
        _poser.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (47, 'done', ?, ?)",
            (_now(), _now()),
        )
        _poser.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (47, 'done', ?, ?)",
            (_now(), _now()),
        )
        _poser.commit()
        _poser.close()
        client.post("/offers/47/geste", json={"geste": suivi_etats.MARQUER_ENVOYEE})
        assert (
            client.post("/offers/47/geste", json={"geste": suivi_etats.REFUSER}).json()[
                "etat"
            ]
            == suivi_etats.REFUSEE
        )


class TestCritere14RetenirLanceLaCascade:
    def test_retenir_lance_fiche_et_cv(self, client, db_path, monkeypatch):
        import api.cascade as cascade

        appeles = []

        async def _fake_launch_pieces(offer_id):
            appeles.append(offer_id)
            return []

        monkeypatch.setattr(cascade, "launch_pieces", _fake_launch_pieces)
        _insert_offer(db_path, 6)

        client.put("/offers/6/verdict", json={"status": "retenu"})
        assert appeles == [6]

    def test_ecarter_ne_lance_rien(self, client, db_path, monkeypatch):
        import api.cascade as cascade

        appeles = []

        async def _fake_launch_pieces(offer_id):
            appeles.append(offer_id)
            return []

        monkeypatch.setattr(cascade, "launch_pieces", _fake_launch_pieces)
        _insert_offer(db_path, 7)

        client.put("/offers/7/verdict", json={"status": "ecartee"})
        assert appeles == []


class TestCritere15OffreRetenueGardeSesPiecesAToutesLesEtapes:
    def test_pieces_accessibles_apres_candidature_envoyee(self, db_path):
        _insert_offer(db_path, 8)
        conn = api_db.get_conn()
        try:
            suivi_storage.appliquer_geste(conn, 8, suivi_etats.RETENIR)
        finally:
            conn.close()
        _mark_pieces_pretes(db_path, 8)
        api_pieces.set_envoyee(8, api_pieces.MarqueEnvoyeeIn(envoyee=True))

        # Toujours accessible une fois la candidature envoyée (critère 15).
        pieces = api_pieces.get_pieces(8)
        assert pieces["envoyee_le"] is not None


class TestCritere16OffreNonRetenueRefuseSesPieces:
    def test_offre_a_trier_refuse_les_pieces(self, db_path):
        _insert_offer(db_path, 9)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.get_pieces(9)
        assert exc_info.value.status_code == 409

    def test_offre_ecartee_refuse_les_pieces(self, db_path):
        _insert_offer(db_path, 10)
        conn = api_db.get_conn()
        try:
            suivi_storage.appliquer_geste(conn, 10, suivi_etats.ECARTER)
        finally:
            conn.close()
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.get_pieces(10)
        assert exc_info.value.status_code == 409


class TestCritere17ExpirationPorteSurRetenuesATouteEtape:
    def test_verification_couvre_une_offre_a_candidature_envoyee(
        self, db_path, monkeypatch
    ):
        import orchestrator.job_search.expiration.service as expiration_service

        _insert_offer(db_path, 11, url="https://retenue.example")
        _insert_offer(db_path, 12, url="https://a-trier.example")
        conn = api_db.get_conn()
        try:
            suivi_storage.appliquer_geste(conn, 11, suivi_etats.RETENIR)
            _mark_pieces_pretes(db_path, 11)
            suivi_storage.appliquer_geste(conn, 11, suivi_etats.MARQUER_ENVOYEE)
        finally:
            conn.close()

        appelees = []

        def _fake_check_url(url):
            appelees.append(url)
            return 200, _now()

        monkeypatch.setattr(expiration_service, "check_url", _fake_check_url)

        conn = api_db.get_conn()
        try:
            run_expiration_check(conn, offer_ids=None)
        finally:
            conn.close()

        assert appelees == ["https://retenue.example"]
