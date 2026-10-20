"""Tests EXE-193 — reprise de `verdicts` (d'avant la fiche) vers le module
d'états, critères 18-26. Base de test reproduisant les faits datés de H1 du
ticket, jamais la base réelle (H8)."""

import sqlite3

import pytest

import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats
from orchestrator.job_search.suivi import storage as suivi_storage


def _creer_base_avant_la_fiche(path):
    """Schéma minimal d'une base d'avant TCK-311 : juste `offers` + `verdicts`,
    sans les tables du module d'états (elles n'existent pas encore)."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE offers (
            id        INTEGER PRIMARY KEY,
            source    TEXT NOT NULL,
            source_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            title     TEXT
        );
        CREATE TABLE verdicts (
            id         INTEGER PRIMARY KEY,
            offer_id   INTEGER REFERENCES offers(id),
            status     TEXT,
            created_at TEXT,
            envoyee_at TEXT
        );
    """)
    conn.commit()
    return conn


def _offer(conn, offer_id, title="Titre"):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title) "
        "VALUES (?, 'test', ?, ?, ?)",
        (offer_id, str(offer_id), f"fp{offer_id}", title),
    )


def _verdict(conn, offer_id, status, created_at, envoyee_at=None):
    conn.execute(
        "INSERT INTO verdicts (offer_id, status, created_at, envoyee_at) "
        "VALUES (?, ?, ?, ?)",
        (offer_id, status, created_at, envoyee_at),
    )


@pytest.fixture
def base_avant_la_fiche(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    conn = _creer_base_avant_la_fiche(path)

    # 2043 : retenu, jamais envoyée.
    _offer(conn, 2043)
    _verdict(conn, 2043, "retenu", "2026-10-14T10:00:00+00:00")

    # 3974, 3962, 3981, 3982 : retenues, envoyées à des dates distinctes.
    for offer_id, created, envoyee in [
        (3974, "2026-10-10T08:00:00+00:00", "2026-10-15T16:25:14+00:00"),
        (3962, "2026-10-12T08:00:00+00:00", "2026-10-19T11:54:39.019219+00:00"),
        (3981, "2026-10-13T08:00:00+00:00", "2026-10-19T12:11:38+00:00"),
        (3982, "2026-10-13T09:00:00+00:00", "2026-10-19T13:26:51.739144+00:00"),
    ]:
        _offer(conn, offer_id)
        _verdict(conn, offer_id, "retenu", created, envoyee_at=envoyee)

    # 11 rejetées (échantillon représentatif à 2).
    _offer(conn, 101)
    _verdict(conn, 101, "rejeté", "2026-10-01T08:00:00+00:00")
    _offer(conn, 102)
    _verdict(conn, 102, "rejeté", "2026-10-02T08:00:00+00:00")

    # Revues hors périmètre (échantillon à 2, 1 ok + 1 faux positif).
    _offer(conn, 201)
    _verdict(conn, 201, "hors_perimetre_ok", "2026-10-03T08:00:00+00:00")
    _offer(conn, 202)
    _verdict(conn, 202, "hors_perimetre_faux_pos", "2026-10-04T08:00:00+00:00")

    # Offres avec fiche/CV/lettre mais sans verdict (3975, 3945 — critère 26).
    _offer(conn, 3975)
    _offer(conn, 3945)

    conn.commit()
    conn.close()
    return path


class TestCritere19And21RetenuesRepriseParEtape:
    def test_2043_reste_a_letape_retenue(self, base_avant_la_fiche):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.etat_stocke(conn, 2043) == etats.RETENUE
        hist = suivi_storage.historique(conn, 2043)
        assert len(hist) == 1
        assert hist[0].geste == etats.RETENIR
        assert hist[0].effet_at == "2026-10-14T10:00:00+00:00"

    @pytest.mark.parametrize("offer_id", [3974, 3962, 3981, 3982])
    def test_les_quatre_sont_a_candidature_envoyee(self, base_avant_la_fiche, offer_id):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.etat_stocke(conn, offer_id) == etats.CANDIDATURE_ENVOYEE


class TestCritere20DateDenvoiTelleQuelle:
    @pytest.mark.parametrize(
        "offer_id,date_envoi",
        [
            (3974, "2026-10-15T16:25:14+00:00"),
            (3962, "2026-10-19T11:54:39.019219+00:00"),
            (3981, "2026-10-19T12:11:38+00:00"),
            (3982, "2026-10-19T13:26:51.739144+00:00"),
        ],
    )
    def test_ligne_marquer_envoyee_datee_exactement(
        self, base_avant_la_fiche, offer_id, date_envoi
    ):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        hist = suivi_storage.historique(conn, offer_id)
        marquer = [e for e in hist if e.geste == etats.MARQUER_ENVOYEE]
        assert len(marquer) == 1
        assert marquer[0].effet_at == date_envoi


class TestCritere22RejeteesEcarteesSansMotif:
    @pytest.mark.parametrize(
        "offer_id,created",
        [(101, "2026-10-01T08:00:00+00:00"), (102, "2026-10-02T08:00:00+00:00")],
    )
    def test_offre_rejetee_devient_ecartee(
        self, base_avant_la_fiche, offer_id, created
    ):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.etat_stocke(conn, offer_id) == etats.ECARTEE
        hist = suivi_storage.historique(conn, offer_id)
        assert len(hist) == 1
        assert hist[0].geste == etats.ECARTER
        assert hist[0].motif is None
        assert hist[0].effet_at == created


class TestCritere23RevuesHorsPerimetreGardeesHorsDuTri:
    def test_revue_ok_gardee_offre_a_trier(self, base_avant_la_fiche):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.revue_hors_perimetre(conn, 201) == "hors_perimetre_ok"
        assert suivi_storage.tri(conn, 201) == etats.A_TRIER

    def test_revue_faux_positif_gardee_offre_a_trier(self, base_avant_la_fiche):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert (
            suivi_storage.revue_hors_perimetre(conn, 202) == "hors_perimetre_faux_pos"
        )
        assert suivi_storage.tri(conn, 202) == etats.A_TRIER


class TestCritere24CandidateEtMasqueRepris:
    def test_candidate_devient_candidature_envoyee(self, tmp_path, monkeypatch):
        path = tmp_path / "job_search.sqlite"
        monkeypatch.setattr(storage_db, "DB_PATH", path)
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 5001)
        _verdict(conn, 5001, "candidaté", "2026-09-01T08:00:00+00:00")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.etat_stocke(conn, 5001) == etats.CANDIDATURE_ENVOYEE
        hist = suivi_storage.historique(conn, 5001)
        assert [e.geste for e in hist] == [etats.RETENIR, etats.MARQUER_ENVOYEE]
        assert hist[1].effet_at == "2026-09-01T08:00:00+00:00"

    def test_masque_devient_ecartee(self, tmp_path, monkeypatch):
        path = tmp_path / "job_search.sqlite"
        monkeypatch.setattr(storage_db, "DB_PATH", path)
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 5002)
        _verdict(conn, 5002, "masqué", "2026-09-02T08:00:00+00:00")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.etat_stocke(conn, 5002) == etats.ECARTEE


class TestCritere18CopieAvantToutEcriture:
    def test_copie_posee_avant_les_ecritures_de_la_reprise(self, base_avant_la_fiche):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)

        backup_path = base_avant_la_fiche.with_name(
            base_avant_la_fiche.stem + ".avant-tck311" + base_avant_la_fiche.suffix
        )
        assert backup_path.exists()

        backup_conn = sqlite3.connect(backup_path)
        backup_conn.row_factory = sqlite3.Row
        # La copie a été prise avant que la reprise n'écrive ses lignes.
        rows = backup_conn.execute("SELECT COUNT(*) AS n FROM etats_offre").fetchone()
        assert rows["n"] == 0
        backup_conn.close()


class TestCritere25SecondDemarrageNeReprendRien:
    def test_deuxieme_init_db_najoute_rien_et_ne_copie_pas_deux_fois(
        self, base_avant_la_fiche
    ):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        hist_avant = suivi_storage.historique(conn, 2043)

        init_db(conn)
        hist_apres = suivi_storage.historique(conn, 2043)
        assert len(hist_apres) == len(hist_avant)

        backup_path = base_avant_la_fiche.with_name(
            base_avant_la_fiche.stem + ".avant-tck311" + base_avant_la_fiche.suffix
        )
        backups = list(base_avant_la_fiche.parent.glob(f"{backup_path.name}*"))
        assert len(backups) == 1


class TestCritere26PiecesInchangeesOffresSansVerdictRestentATrier:
    @pytest.mark.parametrize("offer_id", [3975, 3945])
    def test_offre_sans_verdict_reste_a_trier(self, base_avant_la_fiche, offer_id):
        conn = sqlite3.connect(base_avant_la_fiche)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert suivi_storage.tri(conn, offer_id) == etats.A_TRIER
        assert suivi_storage.historique(conn, offer_id) == []
