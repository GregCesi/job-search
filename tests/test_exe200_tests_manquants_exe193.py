"""Tests EXE-200 — critères 24-31 : les tests manquants d'EXE-193 (H1, jet
44). Comportement déjà correct dans le code hérité pour la plupart de ces
critères (vérifié par la relecture) — ces tests ferment le trou de couverture
qui empêchait une régression future de se voir."""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db
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


def _insert_offer(db_path, offer_id, title="Titre"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title) "
            "VALUES (?, 'test', ?, ?, ?)",
            (offer_id, str(offer_id), f"fp{offer_id}", title),
        )
        conn.commit()
    finally:
        conn.close()


class TestCritere24MotifEnregistreEtReluTelQuel:
    def test_motif_avec_ponctuation_et_accents_relu_identique(
        self, client, db_path, monkeypatch
    ):
        import api.cascade as cascade

        async def _noop(offer_id):
            return []

        monkeypatch.setattr(cascade, "launch_pieces", _noop)

        _insert_offer(db_path, 1)
        client.post("/offers/1/geste", json={"geste": "retenir"})
        motif = "Déjà pourvu — relancé « trop tard » ; cf. mail du 02/01."
        resp = client.post(
            "/offers/1/geste",
            json={"geste": "abandonner", "motif": motif},
        )
        assert resp.status_code == 200

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            hist = suivi_storage.historique(conn, 1)
        finally:
            conn.close()
        abandon = next(e for e in hist if e.geste == "abandonner")
        assert abandon.motif == motif


class TestCritere25RetenirSeulLanceLaGenerationParLaRouteGenerique:
    def test_retenir_lance_fiche_et_cv_aucun_autre_geste_ne_lance(
        self, client, db_path, monkeypatch
    ):
        import api.cascade as cascade

        appels: list[int] = []

        async def _spy(offer_id):
            appels.append(offer_id)
            return []

        monkeypatch.setattr(cascade, "launch_pieces", _spy)

        _insert_offer(db_path, 2)
        client.post("/offers/2/geste", json={"geste": "retenir"})
        assert appels == [2]

        client.post("/offers/2/geste", json={"geste": "abandonner"})
        assert appels == [2]  # toujours une seule entrée : abandonner n'a rien lancé


class TestCritere26SeptEtapesLecturesCommeOffreRetenue:
    @pytest.mark.parametrize(
        "offer_id,etat",
        [
            (100, suivi_etats.RETENUE),
            (101, suivi_etats.CANDIDATURE_ENVOYEE),
            (102, suivi_etats.ENTRETIEN),
            (103, suivi_etats.OFFRE_RECUE),
            (104, suivi_etats.REFUSEE),
            (105, suivi_etats.SANS_SUITE),
            (106, suivi_etats.ABANDONNEE),
        ],
    )
    def test_lecture_pieces_et_mail_repond_comme_retenue(
        self, client, db_path, offer_id, etat
    ):
        _insert_offer(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?)",
                (offer_id, etat),
            )
            conn.commit()
        finally:
            conn.close()

        pieces_resp = client.get(f"/offers/{offer_id}/pieces")
        assert pieces_resp.status_code == 200

        # Un mail déjà posé, pour que la lecture n'ait besoin d'aucun gabarit
        # de dépôt (hors de propos ici) : seule la permission d'accès compte.
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO mails (offer_id, objet, corps, origine, created_at) "
                "VALUES (?, 'Candidature', 'Bonjour.', 'moi', ?)",
                (offer_id, _now()),
            )
            conn.commit()
        finally:
            conn.close()

        mail_resp = client.get(f"/offers/{offer_id}/mail")
        assert mail_resp.status_code == 200


class TestCritere28RevuesEtEcarteesRepriseesVerifiees:
    def test_echantillon_ecartees_et_revues_portent_leur_valeur_et_date(self, tmp_path):
        path = tmp_path / "base.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE offers (
                id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
                fingerprint TEXT, title TEXT
            );
            CREATE TABLE verdicts (
                id INTEGER PRIMARY KEY, offer_id INTEGER, status TEXT,
                created_at TEXT, envoyee_at TEXT
            );
        """)
        echantillon = [
            (301, "rejeté", "2026-09-01T08:00:00+00:00"),
            (302, "rejeté", "2026-09-02T08:00:00+00:00"),
            (303, "masqué", "2026-09-03T08:00:00+00:00"),
            (304, "hors_perimetre_ok", "2026-09-04T08:00:00+00:00"),
            (305, "hors_perimetre_faux_pos", "2026-09-05T08:00:00+00:00"),
            (306, "hors_perimetre_ok", "2026-09-06T08:00:00+00:00"),
        ]
        for offer_id, status, created in echantillon:
            conn.execute(
                "INSERT INTO offers (id, source, source_id, fingerprint, title) "
                "VALUES (?, 'test', ?, ?, 'Titre')",
                (offer_id, str(offer_id), f"fp{offer_id}"),
            )
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, status, created),
            )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)

        for offer_id, status, created in echantillon:
            if status in ("rejeté", "masqué"):
                assert suivi_storage.etat_stocke(conn, offer_id) == suivi_etats.ECARTEE
                hist = suivi_storage.historique(conn, offer_id)
                assert len(hist) == 1
                assert hist[0].effet_at == created
            else:
                assert suivi_storage.revue_hors_perimetre(conn, offer_id) == status
                assert suivi_storage.tri(conn, offer_id) == suivi_etats.A_TRIER
        conn.close()


class TestCritere30TablesDesPiecesInchangeesParLaReprise:
    def test_fiches_cv_lettres_mails_identiques_avant_et_apres(self, tmp_path):
        path = tmp_path / "base.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE offers (
                id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
                fingerprint TEXT, title TEXT
            );
            CREATE TABLE verdicts (
                id INTEGER PRIMARY KEY, offer_id INTEGER, status TEXT,
                created_at TEXT, envoyee_at TEXT
            );
        """)
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title) "
            "VALUES (401, 'test', '401', 'fp401', 'Titre')"
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES "
            "(401, 'retenu', '2026-09-01T08:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        # init_db une première fois pour poser le schéma complet (fiches_entreprise,
        # cvs, lettres, mails...) sans encore migrer verdicts — on capture le
        # schéma seul, puis on insère les pièces, puis on migre.
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        # On ne peut pas appeler init_db ici : il migrerait immédiatement verdicts.
        # On pose donc le schéma des pièces à la main, minimal mais fidèle.
        conn.executescript("""
            CREATE TABLE fiches_entreprise (
                id INTEGER PRIMARY KEY, offer_id INTEGER, statut TEXT,
                presentation TEXT, points_json TEXT, created_at TEXT
            );
            CREATE TABLE cvs (
                id INTEGER PRIMARY KEY, offer_id INTEGER, statut TEXT,
                html TEXT, created_at TEXT
            );
            CREATE TABLE lettres (
                id INTEGER PRIMARY KEY, offer_id INTEGER, statut TEXT,
                texte TEXT, created_at TEXT, faits_ecartes_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE mails (
                id INTEGER PRIMARY KEY, offer_id INTEGER, objet TEXT,
                corps TEXT, origine TEXT, created_at TEXT
            );
        """)
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, created_at) "
            "VALUES (401, 'done', 'Une présentation.', '2026-09-01T09:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, created_at) "
            "VALUES (401, 'done', '<html>cv</html>', '2026-09-01T09:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, texte, created_at) "
            "VALUES (401, 'done', 'Texte de la lettre.', '2026-09-01T09:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO mails (offer_id, objet, corps, origine, created_at) "
            "VALUES (401, 'Candidature', 'Bonjour.', 'moi', '2026-09-01T09:00:00+00:00')"
        )
        conn.commit()

        # Colonnes posées à la main ci-dessus seulement — les migrations de
        # schéma (hors reprise) peuvent ajouter des colonnes sans rapport ;
        # seules CES valeurs doivent rester identiques après la reprise.
        colonnes = {
            "fiches_entreprise": "offer_id, statut, presentation, created_at",
            "cvs": "offer_id, statut, html, created_at",
            "lettres": "offer_id, statut, texte, created_at",
            "mails": "offer_id, objet, corps, origine, created_at",
        }
        avant = {
            table: conn.execute(f"SELECT {cols} FROM {table}").fetchall()
            for table, cols in colonnes.items()
        }

        init_db(conn)  # déclenche la reprise de verdicts

        apres = {
            table: conn.execute(f"SELECT {cols} FROM {table}").fetchall()
            for table, cols in colonnes.items()
        }
        conn.close()

        for table in avant:
            assert [dict(r) for r in avant[table]] == [dict(r) for r in apres[table]]


class TestCritere31GesteRefuseNeChangeRienDepuisChaqueEtat:
    @pytest.mark.parametrize("etat", sorted(suivi_etats.ETATS))
    def test_geste_hors_table_ne_change_pas_letat_ni_lhistorique(
        self, tmp_path, monkeypatch, etat
    ):
        path = tmp_path / "job_search.sqlite"
        monkeypatch.setattr(storage_db, "DB_PATH", path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title) "
            "VALUES (1, 'test', '1', 'fp1', 'Titre')"
        )
        conn.execute("INSERT INTO etats_offre (offer_id, etat) VALUES (1, ?)", (etat,))
        conn.commit()

        permis = set(suivi_etats.TRANSITIONS.get(etat, {}))
        geste_refuse = next(
            g for g in suivi_etats.TOUS_GESTES if g not in permis and g != "annuler"
        )

        with pytest.raises(suivi_etats.GesteRefuse):
            suivi_storage.appliquer_geste(conn, 1, geste_refuse)

        assert suivi_storage.etat_stocke(conn, 1) == etat
        assert suivi_storage.historique(conn, 1) == []
        conn.close()
