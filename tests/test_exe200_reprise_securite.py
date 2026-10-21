"""Tests EXE-200 — critères 1-10 : la copie de sécurité vise le fichier
effectivement migré, la reprise est atomique et sûre entre démarrages
concurrents. Base de test reproduisant les faits de H1, jamais la base réelle
(H8 du ticket)."""

import sqlite3
import threading

import pytest

import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import reprise
from orchestrator.job_search.suivi import storage as suivi_storage


def _creer_base_avant_la_fiche(path):
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


def _verdict(conn, offer_id, status, created_at):
    conn.execute(
        "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
        (offer_id, status, created_at),
    )


def _backup_path(path):
    return path.with_name(path.stem + ".avant-tck311" + path.suffix)


class TestCritere1CopieViseLeFichierDeLaConnexion:
    def test_copie_prend_le_fichier_de_conn_pas_celui_de_db_path(
        self, tmp_path, monkeypatch
    ):
        """DB_PATH pointe vers un AUTRE fichier que celui migré par `conn` —
        reproduit H1 (`shutil.copy2(DB_PATH, ...)` copiait le mauvais fichier
        quand un test migre une base temporaire sans aligner DB_PATH)."""
        migree = tmp_path / "migree.sqlite"
        autre = tmp_path / "ailleurs" / "job_search.sqlite"
        autre.parent.mkdir()
        autre.write_text("pas une base sqlite, juste un leurre")
        monkeypatch.setattr(storage_db, "DB_PATH", autre)

        conn = _creer_base_avant_la_fiche(migree)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(migree)
        conn.row_factory = sqlite3.Row
        init_db(conn)

        assert _backup_path(migree).exists()
        assert not _backup_path(autre).exists()
        # Le leurre n'a jamais été touché.
        assert autre.read_text() == "pas une base sqlite, juste un leurre"


class TestCritere3CoherenteAvecUneAutreConnexionOuverte:
    def test_copie_correcte_malgre_une_lecture_concurrente(self, tmp_path):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()

        # Une autre connexion déjà ouverte sur le même fichier pendant la reprise.
        autre_conn = sqlite3.connect(path)
        autre_conn.execute("SELECT * FROM offers").fetchall()

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        init_db(conn2)

        backup_conn = sqlite3.connect(_backup_path(path))
        backup_conn.row_factory = sqlite3.Row
        rows = backup_conn.execute("SELECT * FROM verdicts").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "retenu"
        backup_conn.close()
        autre_conn.close()


class TestCritere4AucuneCopieHorsDuDossier:
    def test_base_en_memoire_ne_produit_aucune_copie(self, tmp_path):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        init_db(conn)
        # Aucun fichier de sauvegarde n'apparaît où que ce soit de surveillable.
        assert list(tmp_path.glob("*avant-tck311*")) == []

    def test_base_en_dossier_temporaire_copie_dans_son_propre_dossier(self, tmp_path):
        sous_dossier = tmp_path / "un_dossier_a_part"
        sous_dossier.mkdir()
        path = sous_dossier / "job_search.sqlite"
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        assert _backup_path(path).exists()
        assert _backup_path(path).parent == sous_dossier
        assert list(tmp_path.rglob("*avant-tck311*")) == [_backup_path(path)]


class TestCritere5CheminsIsolesSansPreparationDuTest:
    def test_get_connection_sans_setup_pointe_hors_de_data(self):
        """Aucun chemin préparé par CE test : seule la fixture autouse de
        conftest.py protège data/ du dépôt (critère 5)."""
        from orchestrator.job_search.paths import REPO_ROOT

        vrai_chemin = REPO_ROOT / "data" / "job_search.sqlite"
        existait_avant = vrai_chemin.exists()
        mtime_avant = vrai_chemin.stat().st_mtime_ns if existait_avant else None

        # `get_connection()` ne reçoit aucun chemin : il lit `storage_db.DB_PATH`
        # au moment de l'appel — la fixture autouse doit l'avoir déjà déplacé.
        assert storage_db.DB_PATH != vrai_chemin
        conn = storage_db.get_connection()
        init_db(conn)
        conn.close()

        # Le vrai fichier du dépôt n'a ni été créé, ni modifié par ce test.
        if existait_avant:
            assert vrai_chemin.stat().st_mtime_ns == mtime_avant
        else:
            assert not vrai_chemin.exists()


class TestCritere6CoupureNeLaisseAucuneTableNiLigne:
    def test_coupure_pendant_la_migration_ne_laisse_rien(self, tmp_path, monkeypatch):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()

        def _crash(_conn):
            raise RuntimeError("coupure simulée pendant migrer_verdicts")

        monkeypatch.setattr(reprise, "migrer_verdicts", _crash)

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="coupure simulée"):
            init_db(conn2)
        conn2.close()

        # Relecture par une connexion neuve : aucune table du suivi.
        conn3 = sqlite3.connect(path)
        for table in (
            "etats_offre",
            "historique_gestes",
            "revues_hors_perimetre",
            "reprise_suivi_candidatures",
        ):
            row = conn3.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            assert row is None, f"{table} n'aurait pas dû survivre à la coupure"
        conn3.close()

    def test_coupure_apres_les_tables_mais_avant_la_marque_ne_laisse_rien(
        self, tmp_path, monkeypatch
    ):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()

        vrai_migrer = reprise.migrer_verdicts

        def _migrer_puis_crash(c):
            vrai_migrer(c)
            raise RuntimeError("coupure simulée après migrer_verdicts")

        monkeypatch.setattr(reprise, "migrer_verdicts", _migrer_puis_crash)

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError, match="coupure simulée"):
            init_db(conn2)
        conn2.close()

        conn3 = sqlite3.connect(path)
        row = conn3.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'etats_offre'"
        ).fetchone()
        assert row is None
        conn3.close()


class TestCritere7ReessaiApresCoupureIdentiqueASansCoupure:
    def test_meme_historique_apres_une_coupure_puis_reessai(
        self, tmp_path, monkeypatch
    ):
        # Run témoin, sans coupure, deux offres retenues.
        temoin = tmp_path / "temoin.sqlite"
        conn = _creer_base_avant_la_fiche(temoin)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        _offer(conn, 2)
        _verdict(conn, 2, "retenu", "2026-10-02T08:00:00+00:00")
        conn.commit()
        conn_t = sqlite3.connect(temoin)
        conn_t.row_factory = sqlite3.Row
        init_db(conn_t)
        hist_temoin_1 = suivi_storage.historique(conn_t, 1)
        hist_temoin_2 = suivi_storage.historique(conn_t, 2)

        # Même données, mais la coupure frappe entre les deux offres : la
        # première a déjà été écrite (non commitée) quand le process meurt.
        coupe = tmp_path / "coupe.sqlite"
        conn = _creer_base_avant_la_fiche(coupe)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        _offer(conn, 2)
        _verdict(conn, 2, "retenu", "2026-10-02T08:00:00+00:00")
        conn.commit()

        vrai_ecrire = reprise._ecrire_evenement
        appels = {"n": 0}

        def _crash_au_second_evenement(*args, **kwargs):
            appels["n"] += 1
            if appels["n"] == 2:
                raise RuntimeError("coupure simulée entre les deux offres")
            return vrai_ecrire(*args, **kwargs)

        monkeypatch.setattr(reprise, "_ecrire_evenement", _crash_au_second_evenement)

        conn_c = sqlite3.connect(coupe)
        conn_c.row_factory = sqlite3.Row
        with pytest.raises(RuntimeError):
            init_db(conn_c)
        conn_c.close()  # coupure simulée : le process meurt, rien n'est commité

        # Réessai : nouvelle connexion, plus de coupure cette fois.
        monkeypatch.undo()
        conn_c2 = sqlite3.connect(coupe)
        conn_c2.row_factory = sqlite3.Row
        init_db(conn_c2)
        hist_coupe_1 = suivi_storage.historique(conn_c2, 1)
        hist_coupe_2 = suivi_storage.historique(conn_c2, 2)

        def _comparable(hist):
            return [(e.geste, e.etat_depart, e.etat_arrivee) for e in hist]

        assert _comparable(hist_coupe_1) == _comparable(hist_temoin_1)
        assert _comparable(hist_coupe_2) == _comparable(hist_temoin_2)


class TestCritere8DemarragesSimultanesUneSeuleReprise:
    def test_deux_threads_concurrents_une_seule_reprise_et_une_seule_copie(
        self, tmp_path
    ):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()
        conn.close()

        erreurs = []

        def _demarrer():
            try:
                c = sqlite3.connect(path, timeout=10)
                c.row_factory = sqlite3.Row
                init_db(c)
                c.close()
            except Exception as exc:  # noqa: BLE001 — capturé pour l'assertion
                erreurs.append(exc)

        t1 = threading.Thread(target=_demarrer)
        t2 = threading.Thread(target=_demarrer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert erreurs == []

        conn_f = sqlite3.connect(path)
        conn_f.row_factory = sqlite3.Row
        hist = suivi_storage.historique(conn_f, 1)
        assert len(hist) == 1  # une seule reprise, pas deux lignes RETENIR
        conn_f.close()

        backups = list(tmp_path.glob(_backup_path(path).name + "*"))
        assert len(backups) == 1


class TestCritere9LigneInutilisableArreteAvantToutEcriture:
    @pytest.mark.parametrize(
        "status,created_at",
        [
            (None, "2026-10-01T08:00:00+00:00"),
            ("", "2026-10-01T08:00:00+00:00"),
            ("statut_jamais_vu", "2026-10-01T08:00:00+00:00"),
            ("retenu", None),
            ("retenu", ""),
        ],
    )
    def test_ligne_inutilisable_leve_avant_toute_ecriture(
        self, tmp_path, status, created_at
    ):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, status, created_at)
        conn.commit()

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        with pytest.raises(reprise.VerdictInutilisable, match="1"):
            init_db(conn2)
        conn2.close()

        # Rien n'a été écrit : ni backup, ni table du suivi.
        assert not _backup_path(path).exists()
        conn3 = sqlite3.connect(path)
        row = conn3.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'etats_offre'"
        ).fetchone()
        assert row is None
        conn3.close()

    def test_message_nomme_loffre_et_la_valeur_fautive(self, tmp_path):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 4242)
        _verdict(conn, 4242, "valeur_inconnue", "2026-10-01T08:00:00+00:00")
        conn.commit()

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        with pytest.raises(reprise.VerdictInutilisable) as excinfo:
            init_db(conn2)
        message = str(excinfo.value)
        assert "4242" in message
        assert "valeur_inconnue" in message


class TestCritere10BaseDejaRepriseNEstNiRecopieeNiRetouchee:
    def test_second_demarrage_ne_touche_pas_le_fichier_de_sauvegarde(self, tmp_path):
        path = tmp_path / "job_search.sqlite"
        conn = _creer_base_avant_la_fiche(path)
        _offer(conn, 1)
        _verdict(conn, 1, "retenu", "2026-10-01T08:00:00+00:00")
        conn.commit()

        conn2 = sqlite3.connect(path)
        conn2.row_factory = sqlite3.Row
        init_db(conn2)

        backup = _backup_path(path)
        mtime_avant = backup.stat().st_mtime_ns
        contenu_avant = backup.read_bytes()

        init_db(conn2)  # second démarrage, marque déjà posée

        assert backup.stat().st_mtime_ns == mtime_avant
        assert backup.read_bytes() == contenu_avant
