"""Tests EXE-144 — l'étape de candidature d'une offre retenue (retenue,
prête à l'envoi, candidature envoyée) rendue par l'API des listes d'offres.

Le calcul réutilise `cv_statut` / `lettre_statut` / `prete_a_l_envoi`
(orchestrator.job_search.pieces), celui qui sert déjà à la page de l'offre —
jamais une seconde règle. Le verdict enregistré ne change pas : l'étape est
dérivée à la lecture, jamais persistée. Aucun test n'appelle un modèle ni le
réseau : les statuts de pièce sont simulés par insertion SQL directe, même
convention que test_exe139_candidature_envoyee.py. DB sous `tmp_path`, même
précaution d'import tardif de `api.main` que test_exe123_reference_api.py.
"""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import api.pieces as api_pieces
import orchestrator.job_search.storage.db as storage_db
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


@pytest.fixture
def client(db_path):
    import api.main as api_main

    return TestClient(api_main.app)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, verdict, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_cv(db_path, offer_id, statut, marque_pret_at=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, marque_pret_at, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(db_path, offer_id, statut, marque_pret_at=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, marque_pret_at, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _pretes(db_path, offer_id):
    _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
    _insert_lettre(db_path, offer_id, statut="done", marque_pret_at=_now())


def _offer(rows, offer_id):
    for r in rows:
        if r["id"] == offer_id:
            return r
    raise AssertionError(f"offer {offer_id} absente du rendu")


class TestCritere1EtapeRendueSurOffreRetenue:
    def test_offre_retenue_rend_une_etape(self, client, db_path):
        offer_id = 1
        _insert_offer(db_path, offer_id)

        rows = client.get("/offers", params={"filtered_out": "false"}).json()

        assert _offer(rows, offer_id)["etape"] is not None


class TestCritere2PreteALEnvoiQuandLesDeuxPiecesSontPretesEtPasEnvoyee:
    def test_cv_et_lettre_prets_sans_envoi(self, client, db_path):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)

        rows = client.get("/offers").json()

        assert _offer(rows, offer_id)["etape"] == "prete_a_l_envoi"


class TestCritere3CandidatureEnvoyeeMemeSiUnePieceNEstPlusPrete:
    def test_reste_candidature_envoyee_apres_demarque_cv(self, client, db_path):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)
        api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=False))

        rows = client.get("/offers").json()

        assert _offer(rows, offer_id)["etape"] == "candidature_envoyee"


class TestCritere4RetenueSansPieceOuAvecUneSeulePiecePrete:
    def test_sans_cv_ni_lettre(self, client, db_path):
        offer_id = 4
        _insert_offer(db_path, offer_id)

        rows = client.get("/offers").json()

        assert _offer(rows, offer_id)["etape"] == "retenue"

    def test_une_seule_piece_prete(self, client, db_path):
        offer_id = 40
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="done")  # lettre pas marquée prête

        rows = client.get("/offers").json()

        assert _offer(rows, offer_id)["etape"] == "retenue"


class TestCritere5OffreNonRetenueSansEtape:
    def test_offre_candidatee_sans_etape_verdict_inchange(self, client, db_path):
        offer_id = 5
        _insert_offer(db_path, offer_id, verdict="candidaté")

        rows = client.get("/offers").json()

        offer = _offer(rows, offer_id)
        assert offer["etape"] is None
        assert offer["verdict"] == "candidaté"

    def test_offre_sans_verdict_sans_etape(self, client, db_path):
        offer_id = 50
        _insert_offer(db_path, offer_id, verdict=None)

        rows = client.get("/offers").json()

        offer = _offer(rows, offer_id)
        assert offer["etape"] is None
        assert offer["verdict"] is None


class TestCritere6FiltreRetenuRendLesMemesOffresQuelleQueSoitLEtape:
    def test_filtre_verdict_retenu_inchange_par_les_etapes(self, client, db_path):
        _insert_offer(db_path, 6)  # retenue, sans pièce
        _insert_offer(db_path, 60)
        _pretes(db_path, 60)  # prête à l'envoi
        _insert_offer(db_path, 61, verdict="rejeté")  # pas retenue

        rows = client.get("/offers", params={"verdict": "retenu"}).json()

        ids = {r["id"] for r in rows}
        assert ids == {6, 60}
