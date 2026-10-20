"""Tests EXE-193 — persistance du module d'états (critères 3, 4, 6, 8-11), sur
une base sqlite temporaire (jamais celle du dépôt, H8 du ticket)."""

import sqlite3

import pytest

import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats
from orchestrator.job_search.suivi import storage as suivi_storage


@pytest.fixture
def conn(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    init_db(c)
    c.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title) "
        "VALUES (1, 'test', '1', 'fp1', 'Titre')"
    )
    c.commit()
    yield c
    c.close()


class TestCritere8And9Historique:
    def test_geste_enregistre_une_ligne_avec_date_effet_et_enregistrement(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        hist = suivi_storage.historique(conn, 1)
        assert len(hist) == 1
        evt = hist[0]
        assert evt.geste == etats.RETENIR
        assert evt.effet_at
        assert evt.enregistre_at
        assert evt.annule_at is None

    def test_sans_date_deffet_donnee_la_date_deffet_est_lheure_du_geste(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        evt = suivi_storage.historique(conn, 1)[0]
        assert evt.effet_at == evt.enregistre_at

    def test_date_deffet_donnee_est_enregistree_telle_quelle(self, conn):
        suivi_storage.appliquer_geste(
            conn, 1, etats.RETENIR, effet_at="2020-01-01T00:00:00+00:00"
        )
        evt = suivi_storage.historique(conn, 1)[0]
        assert evt.effet_at == "2020-01-01T00:00:00+00:00"
        assert evt.enregistre_at != evt.effet_at


class TestCritere3And4Annuler:
    def test_annuler_remet_etat_avant_le_dernier_geste(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        assert suivi_storage.etat_stocke(conn, 1) == etats.RETENUE
        suivi_storage.annuler_dernier_geste(conn, 1)
        assert suivi_storage.etat_stocke(conn, 1) == etats.A_TRIER

    def test_deux_annulations_defont_les_deux_derniers_gestes_dans_lordre_inverse(
        self, conn
    ):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        suivi_storage.appliquer_geste(conn, 1, etats.ABANDONNER)
        assert suivi_storage.etat_stocke(conn, 1) == etats.ABANDONNEE

        suivi_storage.annuler_dernier_geste(conn, 1)
        assert suivi_storage.etat_stocke(conn, 1) == etats.RETENUE

        suivi_storage.annuler_dernier_geste(conn, 1)
        assert suivi_storage.etat_stocke(conn, 1) == etats.A_TRIER


class TestCritere10AnnulerNeSupprimeRien:
    def test_ligne_annulee_reste_en_base_marquee(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        suivi_storage.annuler_dernier_geste(conn, 1)
        hist = suivi_storage.historique(conn, 1)
        assert len(hist) == 1
        assert hist[0].annule_at is not None


class TestCritere5GestesPermisSansHistorique:
    def test_annuler_absent_sans_geste(self, conn):
        assert etats.ANNULER not in suivi_storage.gestes_permis(conn, 1)

    def test_annuler_absent_si_dernier_geste_deja_annule(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        suivi_storage.annuler_dernier_geste(conn, 1)
        assert etats.ANNULER not in suivi_storage.gestes_permis(conn, 1)

    def test_annuler_present_si_geste_non_annule(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        assert etats.ANNULER in suivi_storage.gestes_permis(conn, 1)


class TestCritere11SurvitAuRedemarrage:
    def test_etat_et_historique_identiques_apres_reouverture(self, conn, tmp_path):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        path = tmp_path / "job_search.sqlite"
        conn.close()

        reopened = sqlite3.connect(path)
        reopened.row_factory = sqlite3.Row
        assert suivi_storage.etat_stocke(reopened, 1) == etats.RETENUE
        assert len(suivi_storage.historique(reopened, 1)) == 1
        reopened.close()


class TestCritere6PreteALEnvoiNecritPasDhistorique:
    def test_marque_pret_ne_touche_pas_lhistorique(self, conn):
        suivi_storage.appliquer_geste(conn, 1, etats.RETENIR)
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, created_at) VALUES (1, 'done', '2026-01-01')"
        )
        conn.execute("UPDATE cvs SET marque_pret_at = '2026-01-01' WHERE offer_id = 1")
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, created_at) VALUES (1, 'done', '2026-01-01')"
        )
        conn.execute(
            "UPDATE lettres SET marque_pret_at = '2026-01-01' WHERE offer_id = 1"
        )
        conn.commit()

        assert suivi_storage.etape(conn, 1) == etats.PRETE_A_L_ENVOI
        assert len(suivi_storage.historique(conn, 1)) == 1  # toujours le seul retenir

        conn.execute("UPDATE cvs SET marque_pret_at = NULL WHERE offer_id = 1")
        conn.commit()
        assert suivi_storage.etape(conn, 1) == etats.RETENUE
        assert len(suivi_storage.historique(conn, 1)) == 1


class TestRevueHorsPerimetreAPart:
    def test_revue_hors_perimetre_ne_change_pas_le_tri(self, conn):
        suivi_storage.marquer_revue_hors_perimetre(conn, 1, "hors_perimetre_ok")
        assert suivi_storage.tri(conn, 1) == etats.A_TRIER
        assert suivi_storage.revue_hors_perimetre(conn, 1) == "hors_perimetre_ok"
