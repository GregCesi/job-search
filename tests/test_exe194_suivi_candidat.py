"""Tests EXE-194 — j'écarte une offre depuis la vue candidat, Cibles/Gaps/Filet
ne montrent plus que les offres à trier, je retrouve mes écartées, et chaque
bouton du suivi affiche ce que l'API décide (critères 2-3, 7, 9-11, 13, 15-17,
19-22, et les mutants N2-N6 de H7). DB sous `tmp_path`, aucun appel modèle."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
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


@pytest.fixture
def client(db_path):
    import api.main as api_main

    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _no_real_cascade(monkeypatch):
    """Aucun test ne doit appeler le modèle : la cascade de retenue (fiche +
    CV) est un no-op (même convention que test_exe193_api_suivi.py)."""
    import api.cascade as cascade

    async def _noop(offer_id):
        return []

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _insert_offer(db_path, offer_id, title="Titre", category="parfait"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "category, filtered_out) VALUES (?, 'test', ?, ?, ?, ?, 0)",
            (offer_id, str(offer_id), f"fp{offer_id}", title, category),
        )
        conn.commit()
    finally:
        conn.close()


def _marquer_pieces_pretes(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00') "
            "ON CONFLICT(offer_id) DO UPDATE SET statut='done', "
            "marque_pret_at='2026-10-01T00:00:00+00:00'",
            (offer_id,),
        )
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, created_at, marque_pret_at) "
            "VALUES (?, 'done', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00') "
            "ON CONFLICT(offer_id) DO UPDATE SET statut='done', "
            "marque_pret_at='2026-10-01T00:00:00+00:00'",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


class TestCriteres2et3EcarterAvecOuSansMotif:
    def test_ecarter_sans_motif_necrit_aucun_motif(self, client, db_path):
        _insert_offer(db_path, 1)
        resp = client.put("/offers/1/verdict", json={"status": "ecartee"})
        assert resp.status_code == 204

        detail = client.get("/offers/1").json()
        assert detail["tri"] == "ecartee"
        assert detail["motif_ecart"] is None

    def test_ecarter_avec_motif_enregistre_le_motif_tel_quel(self, client, db_path):
        _insert_offer(db_path, 2)
        resp = client.put(
            "/offers/2/verdict",
            json={"status": "ecartee", "motif": "Pas assez de remote"},
        )
        assert resp.status_code == 204

        detail = client.get("/offers/2").json()
        assert detail["motif_ecart"] == "Pas assez de remote"


class TestCritere7CiblesExcluentRetenueEtEcartee:
    def test_filtre_verdict_a_trier_necarte_que_les_a_trier(self, client, db_path):
        _insert_offer(db_path, 10, category="parfait")  # reste à trier
        _insert_offer(db_path, 11, category="parfait")
        _insert_offer(db_path, 12, category="parfait")
        client.put("/offers/11/verdict", json={"status": "retenu"})
        client.put("/offers/12/verdict", json={"status": "ecartee"})

        resp = client.get(
            "/offers", params={"category": "parfait", "verdict": "a_trier"}
        )
        ids = {row["id"] for row in resp.json()}
        assert ids == {10}


class TestCritere9VueEcarteesTrieeAvecDateEtMotif:
    def test_plus_recente_ecartee_dabord_avec_date_et_motif(self, client, db_path):
        _insert_offer(db_path, 20)
        _insert_offer(db_path, 21)
        client.post(
            "/offers/20/geste",
            json={
                "geste": "ecarter",
                "motif": "Trop loin",
                "effet_at": "2026-10-05T09:00:00+00:00",
            },
        )
        client.post(
            "/offers/21/geste",
            json={
                "geste": "ecarter",
                "motif": "Salaire trop bas",
                "effet_at": "2026-10-18T09:00:00+00:00",
            },
        )

        resp = client.get(
            "/offers",
            params={"verdict": "ecartee", "sort": "ecartee_le", "order": "desc"},
        )
        rows = resp.json()
        ids = [r["id"] for r in rows]
        assert ids.index(21) < ids.index(20)
        par_id = {r["id"]: r for r in rows}
        assert par_id[21]["motif_ecart"] == "Salaire trop bas"
        assert par_id[21]["ecartee_le"] == "2026-10-18T09:00:00+00:00"
        assert par_id[20]["motif_ecart"] == "Trop loin"


class TestCritere10RemettreATrierRevientDansLaVue:
    def test_remettre_a_trier_revient_dans_la_vue_a_trier(self, client, db_path):
        _insert_offer(db_path, 30, category="reve")
        client.put("/offers/30/verdict", json={"status": "ecartee"})

        avant = client.get(
            "/offers", params={"category": "reve", "verdict": "a_trier"}
        ).json()
        assert avant == []

        resp = client.post("/offers/30/geste", json={"geste": "remettre_a_trier"})
        assert resp.status_code == 200

        apres = client.get(
            "/offers", params={"category": "reve", "verdict": "a_trier"}
        ).json()
        assert {r["id"] for r in apres} == {30}


class TestCritere11OffreRepriseSansMotifADateDeLAncienVerdict:
    def test_offre_ecartee_par_la_reprise_garde_sa_date_sans_motif(
        self, client, db_path
    ):
        _insert_offer(db_path, 40)
        # Reflet exact de ce qu'écrit `reprise.migrer_verdicts` pour un ancien
        # statut "rejeté"/"masqué" (orchestrator/job_search/suivi/reprise.py) :
        # un geste `ecarter` sans motif, à la date de l'ancien verdict.
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO historique_gestes (offer_id, geste, etat_depart, "
            "etat_arrivee, motif, effet_at, enregistre_at, annule_at) "
            "VALUES (40, 'ecarter', 'a_trier', 'ecartee', NULL, "
            "'2026-08-12T10:00:00+00:00', '2026-10-21T00:00:00+00:00', NULL)"
        )
        conn.execute("INSERT INTO etats_offre (offer_id, etat) VALUES (40, 'ecartee')")
        conn.commit()
        conn.close()

        detail = client.get("/offers/40").json()
        assert detail["tri"] == "ecartee"
        assert detail["ecartee_le"] == "2026-08-12T10:00:00+00:00"
        assert detail["motif_ecart"] is None


class TestCritere13VueOperateurGardeTout:
    def test_aucun_filtre_rend_toutes_les_offres_quel_que_soit_leur_tri(
        self, client, db_path
    ):
        _insert_offer(db_path, 50)
        _insert_offer(db_path, 51)
        _insert_offer(db_path, 52)
        client.put("/offers/51/verdict", json={"status": "retenu"})
        client.put("/offers/52/verdict", json={"status": "ecartee"})

        resp = client.get("/offers")
        ids = {row["id"] for row in resp.json()}
        assert {50, 51, 52} <= ids


class TestCritere15LibelleAnnulerDitQuoiEtQuand:
    def test_libelle_nomme_le_dernier_geste_et_sa_date(self, client, db_path):
        _insert_offer(db_path, 60)
        client.post(
            "/offers/60/geste",
            json={"geste": "retenir", "effet_at": "2026-10-19T08:00:00+00:00"},
        )
        _marquer_pieces_pretes(db_path, 60)
        client.post(
            "/offers/60/geste",
            json={
                "geste": "marquer_envoyee",
                "effet_at": "2026-10-19T08:00:00+00:00",
            },
        )

        detail = client.get("/offers/60").json()
        annuler = next(g for g in detail["gestes"] if g["geste"] == "annuler")
        assert annuler["libelle"] == "Annuler Marquer envoyée du 19 octobre"


class TestMutantN5LibelleNommeLeDernierPasLePremier:
    def test_libelle_annuler_utilise_le_dernier_geste_non_le_premier(
        self, client, db_path
    ):
        _insert_offer(db_path, 61)
        client.post(
            "/offers/61/geste",
            json={"geste": "retenir", "effet_at": "2026-09-01T08:00:00+00:00"},
        )
        _marquer_pieces_pretes(db_path, 61)
        client.post(
            "/offers/61/geste",
            json={
                "geste": "marquer_envoyee",
                "effet_at": "2026-09-15T08:00:00+00:00",
            },
        )

        detail = client.get("/offers/61").json()
        annuler = next(g for g in detail["gestes"] if g["geste"] == "annuler")
        assert "Marquer envoyée" in annuler["libelle"]
        assert "Retenir" not in annuler["libelle"]


class TestCritere16AnnulerNeTouchePasLaRevue:
    def test_annulation_remet_letape_davant_et_garde_la_revue(self, client, db_path):
        _insert_offer(db_path, 70)
        client.post("/offers/70/geste", json={"geste": "retenir"})
        client.put("/offers/70/verdict", json={"status": "hors_perimetre_ok"})

        resp = client.delete("/offers/70/verdict")
        assert resp.status_code == 204

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            assert (
                suivi_storage.etat_stocke(conn, 70) == suivi_etats.A_TRIER
            )  # remet l'étape d'avant
            assert (
                suivi_storage.revue_hors_perimetre(conn, 70) == "hors_perimetre_ok"
            )  # la revue reste
        finally:
            conn.close()


class TestMutantN2AnnulerNEffacePlusLaRevue:
    def test_annuler_le_dernier_geste_ne_reproduit_pas_lancien_effacement(
        self, client, db_path
    ):
        """Même scénario que le critère 16, formulé comme regression du bug
        du 21 octobre (H7, N2) : l'ancien DELETE /verdict effaçait la revue
        au lieu d'annuler un geste."""
        _insert_offer(db_path, 71)
        client.post("/offers/71/geste", json={"geste": "retenir"})
        client.put("/offers/71/verdict", json={"status": "hors_perimetre_faux_pos"})

        client.delete("/offers/71/verdict")

        detail = client.get("/offers/71").json()
        assert detail["revue_hors_perimetre"] == "hors_perimetre_faux_pos"


class TestCritere17RetirerLaRevue:
    def test_retirer_la_revue_ne_change_ni_tri_ni_historique(self, client, db_path):
        _insert_offer(db_path, 80)
        client.post("/offers/80/geste", json={"geste": "retenir"})
        client.put("/offers/80/verdict", json={"status": "hors_perimetre_ok"})

        resp = client.delete("/offers/80/revue")
        assert resp.status_code == 204

        detail = client.get("/offers/80").json()
        assert detail["revue_hors_perimetre"] is None
        assert detail["tri"] == "retenue"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            hist = suivi_storage.historique(conn, 80)
        finally:
            conn.close()
        assert len(hist) == 1
        assert hist[0].geste == "retenir"
        assert hist[0].annule_at is None

    def test_retirer_la_revue_409_si_aucune_revue(self, client, db_path):
        _insert_offer(db_path, 81)
        resp = client.delete("/offers/81/revue")
        assert resp.status_code == 409


class TestCritere19GesteRefuseNeChangeRienEtRendUnMessage:
    def test_message_non_vide_et_etat_inchange(self, client, db_path):
        _insert_offer(db_path, 90)
        resp = client.post("/offers/90/geste", json={"geste": "marquer_envoyee"})
        assert resp.status_code == 409
        assert resp.json()["detail"]  # message non vide, affichable à l'écran

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            assert suivi_storage.etat_stocke(conn, 90) == suivi_etats.A_TRIER
            assert suivi_storage.historique(conn, 90) == []
        finally:
            conn.close()


class TestCritere20MessageDeRefusEcarterNommeLesLibelles:
    def test_ecarter_une_retenue_refuse_avec_libelles(self, client, db_path):
        _insert_offer(db_path, 91)
        client.post("/offers/91/geste", json={"geste": "retenir"})
        resp = client.post("/offers/91/geste", json={"geste": "ecarter"})
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "Écarter" in detail
        assert "retenue" in detail
        assert "ecarter" not in detail  # jamais le code interne


class TestCritere21TriEtapeEtRevueRendusIndependamment:
    def test_offre_retenue_avec_revue_expose_les_trois_axes(self, client, db_path):
        _insert_offer(db_path, 100)
        client.post("/offers/100/geste", json={"geste": "retenir"})
        client.put("/offers/100/verdict", json={"status": "hors_perimetre_ok"})

        detail = client.get("/offers/100").json()
        assert detail["tri"] == "retenue"
        assert detail["etape"] is not None
        assert detail["revue_hors_perimetre"] == "hors_perimetre_ok"

    def test_offre_ecartee_avec_revue_expose_les_deux_axes(self, client, db_path):
        _insert_offer(db_path, 101)
        client.put("/offers/101/verdict", json={"status": "ecartee"})
        client.put("/offers/101/verdict", json={"status": "hors_perimetre_faux_pos"})

        detail = client.get("/offers/101").json()
        assert detail["tri"] == "ecartee"
        assert detail["revue_hors_perimetre"] == "hors_perimetre_faux_pos"


class TestCritere22EtEtMutantN6EtapesAcquises:
    def test_abandon_depuis_retenue_nacquiert_que_retenue(self, client, db_path):
        _insert_offer(db_path, 110)
        client.post("/offers/110/geste", json={"geste": "retenir"})
        client.post("/offers/110/geste", json={"geste": "abandonner"})

        detail = client.get("/offers/110").json()
        assert detail["etape"] == "abandonnee"
        # EXE-201, critère 13 : l'étape de fin est elle-même montrée acquise.
        assert detail["etapes_acquises"] == ["retenue", "abandonnee"]
        assert "candidature_envoyee" not in detail["etapes_acquises"]
        assert "entretien" not in detail["etapes_acquises"]

    def test_abandon_depuis_candidature_envoyee_nacquiert_pas_entretien(
        self, client, db_path
    ):
        _insert_offer(db_path, 111)
        client.post("/offers/111/geste", json={"geste": "retenir"})
        _marquer_pieces_pretes(db_path, 111)
        client.post("/offers/111/geste", json={"geste": "marquer_envoyee"})
        client.post("/offers/111/geste", json={"geste": "abandonner"})

        detail = client.get("/offers/111").json()
        # EXE-201, critère 13 : l'étape de fin est elle-même montrée acquise.
        assert detail["etapes_acquises"] == [
            "retenue",
            "prete_a_l_envoi",
            "candidature_envoyee",
            "abandonnee",
        ]
        assert "entretien" not in detail["etapes_acquises"]
