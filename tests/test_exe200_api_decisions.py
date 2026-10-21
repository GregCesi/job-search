"""Tests EXE-200 — critères 11-23 : le tri et la revue hors périmètre dans
deux champs séparés, l'API rend chaque geste avec sa raison, les étapes et
« Tout télécharger », les messages de refus par libellé, le tri composite
avec verdict, la validation d'effet_at, le jeu du banc et la CLI verdict."""

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


@pytest.fixture(autouse=True)
def _no_real_cascade(monkeypatch):
    import api.cascade as cascade

    async def _noop(offer_id):
        return []

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _insert_offer(db_path, offer_id, title="Titre", company=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company) "
            "VALUES (?, 'test', ?, ?, ?, ?)",
            (offer_id, str(offer_id), f"fp{offer_id}", title, company),
        )
        conn.commit()
    finally:
        conn.close()


def _marquer_pieces_pretes(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, _now(), _now()),
        )
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _retenir(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        suivi_storage.appliquer_geste(conn, offer_id, suivi_etats.RETENIR)
    finally:
        conn.close()


def _marquer_revue(db_path, offer_id, valeur):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        suivi_storage.marquer_revue_hors_perimetre(conn, offer_id, valeur)
    finally:
        conn.close()


class TestCritere11TriEtRevueDansDeuxChampsSepares:
    def test_liste_rend_tri_et_revue_separement(self, client, db_path):
        _insert_offer(db_path, 1)
        _retenir(db_path, 1)
        _marquer_revue(db_path, 1, "hors_perimetre_ok")

        resp = client.get("/offers")
        offer = next(o for o in resp.json() if o["id"] == 1)
        assert offer["tri"] == "retenue"
        assert offer["revue_hors_perimetre"] == "hors_perimetre_ok"

    def test_detail_rend_tri_et_revue_separement(self, client, db_path):
        _insert_offer(db_path, 2)
        _marquer_revue(db_path, 2, "hors_perimetre_faux_pos")

        resp = client.get("/offers/2")
        detail = resp.json()
        assert detail["tri"] == "a_trier"
        assert detail["revue_hors_perimetre"] == "hors_perimetre_faux_pos"

    def test_export_rend_tri_et_revue_separement(self, client, db_path):
        _insert_offer(db_path, 3)
        _retenir(db_path, 3)
        _marquer_revue(db_path, 3, "hors_perimetre_ok")

        resp = client.get("/export/offers", params={"include": "verdict"})
        texte = resp.text
        assert "- Tri : retenue" in texte
        assert "- Revue hors périmètre : hors_perimetre_ok" in texte


class TestCritere12RetenueMalgreRevueVisiblePartout:
    def test_filtre_retenu_trouve_loffre_malgre_la_revue(self, client, db_path):
        _insert_offer(db_path, 10)
        _retenir(db_path, 10)
        _marquer_revue(db_path, 10, "hors_perimetre_ok")

        resp = client.get("/offers", params={"verdict": "retenu"})
        ids = [o["id"] for o in resp.json()]
        assert 10 in ids

    def test_detail_dit_retenue_malgre_la_revue(self, client, db_path):
        _insert_offer(db_path, 11)
        _retenir(db_path, 11)
        _marquer_revue(db_path, 11, "hors_perimetre_faux_pos")

        resp = client.get("/offers/11")
        assert resp.json()["tri"] == "retenue"

    def test_filtre_hors_perimetre_ok_trouve_aussi_loffre(self, client, db_path):
        _insert_offer(db_path, 12)
        _retenir(db_path, 12)
        _marquer_revue(db_path, 12, "hors_perimetre_ok")

        resp = client.get("/offers", params={"verdict": "hors_perimetre_ok"})
        ids = [o["id"] for o in resp.json()]
        assert 12 in ids


class TestCritere13AxesIndependants:
    def test_poser_la_revue_ne_change_pas_le_tri(self, client, db_path):
        _insert_offer(db_path, 20)
        _retenir(db_path, 20)
        avant = client.get("/offers/20").json()["tri"]

        _marquer_revue(db_path, 20, "hors_perimetre_ok")
        apres = client.get("/offers/20").json()["tri"]
        assert avant == apres == "retenue"

    def test_annuler_ne_change_pas_la_revue(self, client, db_path):
        _insert_offer(db_path, 21)
        _marquer_revue(db_path, 21, "hors_perimetre_ok")
        _retenir(db_path, 21)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.annuler_dernier_geste(conn, 21)
        finally:
            conn.close()

        detail = client.get("/offers/21").json()
        assert detail["tri"] == "a_trier"
        assert detail["revue_hors_perimetre"] == "hors_perimetre_ok"


class TestCritere14GestesAvecEtatEtRaison:
    def test_geste_permis_na_pas_de_raison(self, client, db_path):
        _insert_offer(db_path, 30)
        detail = client.get("/offers/30").json()
        retenir = next(g for g in detail["gestes"] if g["geste"] == "retenir")
        assert retenir["permis"] is True
        assert retenir["raison"] is None

    def test_geste_hors_table_porte_une_raison_en_clair(self, client, db_path):
        _insert_offer(db_path, 31)
        detail = client.get("/offers/31").json()
        marquer = next(g for g in detail["gestes"] if g["geste"] == "marquer_envoyee")
        assert marquer["permis"] is False
        assert marquer["raison"]
        assert "marquer_envoyee" not in marquer["raison"]

    def test_marquer_envoyee_nomme_la_piece_manquante(self, client, db_path):
        # EXE-197, critères 1, 9, 10 : depuis ce ticket, pièce non prête n'est
        # plus un refus — seulement un avertissement, geste toujours permis.
        _insert_offer(db_path, 32)
        _retenir(db_path, 32)
        detail = client.get("/offers/32").json()
        marquer = next(g for g in detail["gestes"] if g["geste"] == "marquer_envoyee")
        assert marquer["permis"] is True
        assert "CV" in marquer["raison"] or "lettre" in marquer["raison"]
        assert marquer["pieces_non_pretes"] == ["cv", "lettre"]


class TestCritere15EtapesAffichees:
    def test_offre_non_retenue_na_aucune_etape_affichee(self, client, db_path):
        _insert_offer(db_path, 40)
        detail = client.get("/offers/40").json()
        assert detail["etapes_affichees"] == []

    def test_offre_retenue_rend_la_sequence_et_sa_position(self, client, db_path):
        _insert_offer(db_path, 41)
        _retenir(db_path, 41)
        detail = client.get("/offers/41").json()
        assert detail["etapes_affichees"] == [
            "retenue",
            "prete_a_l_envoi",
            "candidature_envoyee",
            "entretien",
        ]
        assert detail["etape"] == "retenue"


class TestCritere16ToutTelecharger:
    def test_impossible_sans_pieces_pretes_nomme_la_raison(self, client, db_path):
        _insert_offer(db_path, 50)
        _retenir(db_path, 50)
        detail = client.get("/offers/50").json()
        assert detail["tout_telecharger_possible"] is False
        assert detail["tout_telecharger_raison"]

    def test_possible_quand_les_deux_pieces_sont_pretes(self, client, db_path):
        _insert_offer(db_path, 51)
        _retenir(db_path, 51)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?)",
            (51, _now(), _now()),
        )
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', ?, ?)",
            (51, _now(), _now()),
        )
        conn.commit()
        conn.close()

        detail = client.get("/offers/51").json()
        assert detail["tout_telecharger_possible"] is True
        assert detail["tout_telecharger_raison"] is None


class TestCritere17MessagesParLibelle:
    def test_message_ecarter_refuse_nomme_le_libelle_pas_le_code_interne(
        self, client, db_path
    ):
        _insert_offer(db_path, 60)
        _retenir(db_path, 60)
        _marquer_pieces_pretes(db_path, 60)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.appliquer_geste(conn, 60, suivi_etats.MARQUER_ENVOYEE)
        finally:
            conn.close()

        resp = client.put("/offers/60/verdict", json={"status": "ecartee"})
        assert resp.status_code == 409
        message = resp.json()["detail"]
        assert "candidature envoyée" in message  # libellé de l'état
        assert "candidature_envoyee" not in message  # jamais le code interne


class TestCritere18EcarterRetenueRefuseAvecGestesPermis:
    def test_message_nomme_les_gestes_reellement_possibles_depuis_cette_etape(
        self, client, db_path
    ):
        """Depuis `candidature_envoyee`, « Abandonner » n'est que l'un des
        gestes possibles — le message doit refléter la liste réelle de
        l'étape, pas un conseil figé à « Abandonner, puis Remettre à trier »
        (qui n'était même valide que depuis `écartée`, H1)."""
        _insert_offer(db_path, 70)
        _retenir(db_path, 70)
        _marquer_pieces_pretes(db_path, 70)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.appliquer_geste(conn, 70, suivi_etats.MARQUER_ENVOYEE)
        finally:
            conn.close()

        resp = client.put("/offers/70/verdict", json={"status": "ecartee"})
        assert resp.status_code == 409
        message = resp.json()["detail"]
        assert "Relancer" in message
        assert "Entretien" in message
        assert "Remettre à trier" not in message


class TestCritere19MarqueEnvoieRefuseProprement:
    def test_annuler_un_envoi_qui_nest_plus_le_dernier_geste_refuse(
        self, client, db_path
    ):
        _insert_offer(db_path, 80)
        _retenir(db_path, 80)
        _marquer_pieces_pretes(db_path, 80)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.appliquer_geste(conn, 80, suivi_etats.MARQUER_ENVOYEE)
            suivi_storage.appliquer_geste(conn, 80, suivi_etats.ENTRETIEN_GESTE)
        finally:
            conn.close()

        resp = client.put("/offers/80/envoyee", json={"envoyee": False})
        assert resp.status_code == 409
        assert "dernier geste" in resp.json()["detail"]

    def test_marquer_envoyee_une_offre_abandonnee_refuse(self, client, db_path):
        _insert_offer(db_path, 81)
        _retenir(db_path, 81)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.appliquer_geste(conn, 81, suivi_etats.ABANDONNER)
        finally:
            conn.close()

        resp = client.put("/offers/81/envoyee", json={"envoyee": True})
        assert resp.status_code == 409
        assert "abandonnée" in resp.json()["detail"]


class TestCritere20TriCompositeRespecteLOrdreDesColonnes:
    def test_sort_company_puis_verdict_la_company_domine(self, client, db_path):
        """offre 90 : company « A » (alphabétiquement avant), à trier (rang
        verdict le PIRE, 5). offre 91 : company « B », retenue (rang verdict
        le MEILLEUR, 1). sort=company,verdict (company PRIMAIRE) doit garder
        90 avant 91 malgré son verdict moins bon — un tri qui laisse le
        verdict écraser la company après coup (H1) inverserait l'ordre."""
        _insert_offer(db_path, 90, company="A")
        _insert_offer(db_path, 91, company="B")
        _retenir(db_path, 91)

        resp = client.get(
            "/offers", params={"sort": "company,verdict", "order": "asc,asc"}
        )
        ids = [o["id"] for o in resp.json() if o["id"] in (90, 91)]
        assert ids == [90, 91]

    def test_sort_verdict_puis_company_le_verdict_domine(self, client, db_path):
        _insert_offer(db_path, 92, company="Z")
        _insert_offer(db_path, 93, company="A")
        _retenir(db_path, 92)  # verdict=retenu, company Z
        # 93 reste à trier, company A : alphabétiquement avant, mais le
        # verdict est ici la clé primaire — 92 doit rester devant.

        resp = client.get(
            "/offers", params={"sort": "verdict,company", "order": "asc,asc"}
        )
        ids = [o["id"] for o in resp.json() if o["id"] in (92, 93)]
        assert ids == [92, 93]


class TestCritere21EffetAtValide:
    def test_effet_at_invalide_refuse_en_422_avant_toute_ecriture(
        self, client, db_path
    ):
        _insert_offer(db_path, 100)
        resp = client.post(
            "/offers/100/geste",
            json={"geste": "retenir", "effet_at": "pas-une-date"},
        )
        assert resp.status_code == 422

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            assert suivi_storage.etat_stocke(conn, 100) == suivi_etats.A_TRIER
            assert suivi_storage.historique(conn, 100) == []
        finally:
            conn.close()

    def test_effet_at_valide_est_accepte(self, client, db_path):
        _insert_offer(db_path, 101)
        resp = client.post(
            "/offers/101/geste",
            json={"geste": "retenir", "effet_at": "2026-01-01T00:00:00+00:00"},
        )
        assert resp.status_code == 200


class TestCritere22JeuBancSurBaseNonReprise:
    def test_preparation_du_jeu_fonctionne_sans_table_manquante(self, tmp_path):
        from orchestrator.job_search.lettre import jeu as lettre_jeu

        path = tmp_path / "base_jamais_init.sqlite"
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE offers (
                id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
                fingerprint TEXT, title TEXT, company TEXT, location TEXT,
                url TEXT, description TEXT, description_raw TEXT
            );
        """)
        # Une offre réelle, pour que la résolution dépasse le simple « offre
        # introuvable » et atteigne suivi_storage.est_retenue — qui lit
        # `etats_offre`, absente d'une base jamais initialisée (H1).
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description) VALUES (999, 'test', '999', 'fp999', "
            "'Titre', 'Entreprise', 'Un texte assez long pour ne pas être "
            "considéré comme manquant par resolve_offer_text.')"
        )
        conn.commit()
        conn.close()

        code = lettre_jeu.main(
            ["--nom", "essai_sans_table", "--offres", "999"],
            jeux_dir=tmp_path,
            db_path=path,
        )
        assert code == 0
        assert (tmp_path / "essai_sans_table.json").exists()


class TestCritere23VerdictCliMessagePropre:
    def test_geste_refuse_affiche_le_message_sans_lever(self, db_path, capsys):
        from orchestrator.job_search import verdict as verdict_cli

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                "INSERT INTO offers (id, source, source_id, fingerprint, title) "
                "VALUES (110, 'test', '110', 'fp110', 'Titre')"
            )
            conn.commit()
            # « écarter » refusé depuis a_trier n'est pas le cas ici ; on
            # simule un geste hors table : marquer_envoyee depuis a_trier.
            verdict_cli._record_verdict(conn, 110, "marquer_envoyee")
        finally:
            conn.close()

        sortie = capsys.readouterr().out
        assert "✗" in sortie
        assert "Traceback" not in sortie
