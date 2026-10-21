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
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage


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
        if verdict == "retenu":
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        elif verdict is not None:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.ECARTER, effet_at=_now()
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


def _marquer_envoyee_geste(db_path, offer_id):
    return next(
        g
        for g in suivi_storage.gestes_avec_etat(_connect(db_path), offer_id)
        if g.geste == "marquer_envoyee"
    )


class TestCritere2EnvoyeeMalgrePieceNonPreteAvecAvertissement:
    """EXE-197, critères 1, 6, 10 : depuis ce ticket, une pièce non prête
    n'est plus un refus de `marquer_envoyee` — seulement un avertissement
    (`pieces_non_pretes`) porté par le geste, lu avant confirmation."""

    def test_envoyee_si_cv_non_pret_avec_avertissement(self, db_path):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done")  # pas marqué prêt
        _insert_lettre(db_path, offer_id, statut="done", marque_pret_at=_now())

        avant = _marquer_envoyee_geste(db_path, offer_id)
        assert avant.permis is True
        assert avant.pieces_non_pretes == ["cv"]

        result = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        assert result["envoyee_le"]
        assert suivi_storage.date_envoyee(_connect(db_path), offer_id) is not None

    def test_envoyee_si_lettre_non_prete_avec_avertissement(self, db_path):
        offer_id = 20
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="done")  # pas marquée prête

        avant = _marquer_envoyee_geste(db_path, offer_id)
        assert avant.permis is True
        assert avant.pieces_non_pretes == ["lettre"]

        result = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        assert result["envoyee_le"]

    def test_envoyee_si_aucune_piece_prete_avertissement_nomme_les_deux(self, db_path):
        offer_id = 21
        _insert_offer(db_path, offer_id)

        avant = _marquer_envoyee_geste(db_path, offer_id)
        assert avant.permis is True
        assert avant.pieces_non_pretes == ["cv", "lettre"]
        assert "CV" in avant.raison
        assert "lettre" in avant.raison

        result = api_pieces.set_envoyee(
            offer_id, api_pieces.MarqueEnvoyeeIn(envoyee=True)
        )
        assert result["envoyee_le"]


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
