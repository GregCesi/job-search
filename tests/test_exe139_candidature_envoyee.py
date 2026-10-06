"""Tests EXE-139 — marque humaine « Candidature envoyée », distincte du statut
retenu/rejeté/candidaté et des statuts de pièce (CV / lettre).

Aucun test n'appelle un modèle ni le réseau : les statuts de pièce sont
simulés par insertion SQL directe, même convention que
test_exe101_statut_piece.py. Aucun test ne lit ni n'écrit sous data/ : DB sous
`tmp_path`.
"""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


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


class TestCritere1MarqueEnvoyeeSiLesDeuxPretes:
    def test_marque_envoyee_enregistre_et_rend_la_date(self, db_path):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)

        result = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        assert result["envoyee_le"]

        # L'API la rend aussi à la lecture agrégée des pièces
        assert api_pieces.get_pieces(offer_id)["envoyee_le"] == result["envoyee_le"]


class TestCritere2RefusSiPieceNonPrete:
    def test_refuse_si_cv_non_pret(self, db_path):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done")  # pas marqué prêt
        _insert_lettre(db_path, offer_id, statut="done", marque_pret_at=_now())

        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409
        assert "CV" in exc_info.value.detail

        row = (
            _connect(db_path)
            .execute("SELECT envoyee_at FROM verdicts WHERE offer_id = ?", (offer_id,))
            .fetchone()
        )
        assert row["envoyee_at"] is None

    def test_refuse_si_lettre_non_prete(self, db_path):
        offer_id = 20
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="done")  # pas marquée prête

        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409
        assert "lettre" in exc_info.value.detail

        row = (
            _connect(db_path)
            .execute("SELECT envoyee_at FROM verdicts WHERE offer_id = ?", (offer_id,))
            .fetchone()
        )
        assert row["envoyee_at"] is None

    def test_refuse_si_aucune_piece_prete(self, db_path):
        offer_id = 21
        _insert_offer(db_path, offer_id)

        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409
        assert "CV" in exc_info.value.detail
        assert "lettre" in exc_info.value.detail


class TestCritere3RefusOffreNonRetenueOuInexistante:
    def test_refuse_offre_non_retenue(self, db_path):
        offer_id = 3
        _insert_offer(db_path, offer_id, verdict="candidaté")
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail

    def test_refuse_offre_inexistante(self, db_path):
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_envoyee(9999, api_pieces.MarqueEnvoyeeIn(envoyee=True))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail


class TestCritere4LeMarquageSAnnule:
    def test_annuler_efface_la_date(self, db_path):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)
        api_pieces.set_envoyee(offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True))

        result = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=False)
        )
        assert result["envoyee_le"] is None
        assert api_pieces.get_pieces(offer_id)["envoyee_le"] is None


class TestCritere5RestePersisteeSiUnePieceNEstPlusPrete:
    def test_reste_envoyee_si_cv_demarque(self, db_path):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)
        marque = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )

        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=False))

        assert api_pieces.get_pieces(offer_id)["envoyee_le"] == marque["envoyee_le"]

    def test_reste_envoyee_si_lettre_regeneree(self, db_path):
        offer_id = 50
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)
        marque = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )

        # Une régénération efface la marque Prête de la lettre dès son lancement
        # (EXE-66/EXE-101) : simulée ici par le même effet SQL.
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE lettres SET marque_pret_at = NULL WHERE offer_id = ?",
                (offer_id,),
            )
            conn.commit()
        finally:
            conn.close()

        assert api_pieces.get_pieces(offer_id)["envoyee_le"] == marque["envoyee_le"]


class TestCritere6MarquerDeuxFoisGardeLaPremiereDate:
    def test_deuxieme_marquage_garde_la_date_initiale(self, db_path):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _pretes(db_path, offer_id)

        premiere = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        seconde = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        assert seconde["envoyee_le"] == premiere["envoyee_le"]


class TestCritere7BaseAnterieureOuvreSansPerte:
    def test_migration_idempotente_sans_marquer_les_offres_existantes(self, tmp_path):
        """Simule une base créée avant ce tour : table `verdicts` sans
        `envoyee_at`, une offre déjà retenue. `init_db` doit l'ouvrir sans
        erreur, garder la ligne, et ne marquer personne envoyée."""
        path = tmp_path / "ancienne.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE offers (
                id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
                fingerprint TEXT
            );
            CREATE TABLE verdicts (
                id INTEGER PRIMARY KEY, offer_id INTEGER, status TEXT,
                created_at TEXT
            );
            INSERT INTO offers (id, source, source_id, fingerprint)
                VALUES (1, 'test', '1', 'fp');
            INSERT INTO verdicts (offer_id, status, created_at)
                VALUES (1, 'retenu', '2026-01-01T00:00:00+00:00');
        """)
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)  # ne doit pas lever

        row = conn.execute(
            "SELECT status, envoyee_at FROM verdicts WHERE offer_id = 1"
        ).fetchone()
        assert row["status"] == "retenu"
        assert row["envoyee_at"] is None
        conn.close()
