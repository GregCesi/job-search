"""Tests EXE-198 — après l'envoi, je trace la suite (relance, entretiens,
refus, offre, sans suite), j'abandonne avant la fin, j'annule mon dernier
geste, et l'historique daté se lit sur la page de l'offre.

Les critères 1 à 4 (gestes permis par bloc d'étape) et 17 (badge par étape de
fin) sont déjà vrais avant cette fiche (H2 du ticket) : couverts par
`tests/test_exe193_suivi_etats.py::TestCritere1TableDesTransitions` /
`TestCritere2GesteAbsentRefuse`, déjà verts. Les critères 8, 9, 10, 13 sont
aussi déjà vrais (table et route déjà posées) ; les tests ci-dessous les
déclarent verts avant la fiche (H9, critère 19). DB sous `tmp_path`, aucun
appel modèle (H5 du ticket)."""

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import reprise as suivi_reprise
from orchestrator.job_search.suivi import storage as suivi_storage

FUSEAU_BRUXELLES = ZoneInfo("Europe/Brussels")


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_offer(db_path, offer_id, title="Titre", company="Acme"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company) "
            "VALUES (?, 'test', ?, 'fp', ?, ?)",
            (offer_id, str(offer_id), title, company),
        )
        conn.commit()
    finally:
        conn.close()


def _poser_pieces_pretes(db_path, offer_id):
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


def _figer_horloge(monkeypatch, iso_utc: str):
    fixe = datetime.fromisoformat(iso_utc)
    monkeypatch.setattr(suivi_etats, "maintenant", lambda: fixe)


def _geste(client, offer_id, geste, **kwargs):
    body = {"geste": geste, **kwargs}
    return client.post(f"/offers/{offer_id}/geste", json=body)


def _en_candidature_envoyee(client, db_path, offer_id):
    _insert_offer(db_path, offer_id)
    assert _geste(client, offer_id, "retenir").status_code == 200
    assert _geste(client, offer_id, "marquer_envoyee").status_code == 200


def _en_entretien(client, db_path, offer_id):
    _en_candidature_envoyee(client, db_path, offer_id)
    assert _geste(client, offer_id, "entretien").status_code == 200


# ---------------------------------------------------------------------------
# Critère 5 — le bouton de refus dit « Refusée », jamais « Refuser »
# ---------------------------------------------------------------------------


class TestCritere5LibelleRefusee:
    def test_libelle_refuser_est_refusee(self):
        assert suivi_etats.LIBELLES_GESTES[suivi_etats.REFUSER] == "Refusée"

    def test_api_rend_le_libelle_refusee(self, client, db_path):
        offer_id = 100
        _en_candidature_envoyee(client, db_path, offer_id)
        detail = client.get(f"/offers/{offer_id}").json()
        refuser = next(g for g in detail["gestes"] if g["geste"] == "refuser")
        assert refuser["libelle"] == "Refusée"


# ---------------------------------------------------------------------------
# Critère 7 — Entretien accepte une date passée ou future ; les autres gestes
# du bloc refusent une date postérieure à aujourd'hui (jour de Bruxelles).
# ---------------------------------------------------------------------------


class TestCritere7DateFutureInterditeSaufEntretien:
    @pytest.mark.parametrize(
        "geste,setup",
        [
            ("relancer", "candidature_envoyee"),
            ("sans_suite", "candidature_envoyee"),
            ("refuser", "candidature_envoyee"),
            ("abandonner", "candidature_envoyee"),
            ("offre_recue", "entretien"),
        ],
    )
    def test_date_future_refusee_avec_message(
        self, client, db_path, monkeypatch, geste, setup
    ):
        offer_id = abs(hash((geste, setup))) % 100000 + 1000
        if setup == "candidature_envoyee":
            _en_candidature_envoyee(client, db_path, offer_id)
        else:
            _en_entretien(client, db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        resp = _geste(client, offer_id, geste, effet_at="2026-10-22")
        assert resp.status_code == 409, (geste, resp.text)
        assert "postérieure" in resp.json()["detail"]

    def test_entretien_accepte_une_date_future(self, client, db_path, monkeypatch):
        offer_id = 1100
        _en_candidature_envoyee(client, db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        resp = _geste(client, offer_id, "entretien", effet_at="2026-10-28")
        assert resp.status_code == 200
        assert resp.json()["etat"] == "entretien"

    def test_entretien_accepte_une_date_passee(self, client, db_path, monkeypatch):
        offer_id = 1101
        _en_candidature_envoyee(client, db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        resp = _geste(client, offer_id, "entretien", effet_at="2026-10-10")
        assert resp.status_code == 200
        assert resp.json()["etat"] == "entretien"

    def test_relancer_date_seule_enregistree_a_midi_bruxelles(
        self, client, db_path, monkeypatch
    ):
        offer_id = 1102
        _en_candidature_envoyee(client, db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        resp = _geste(client, offer_id, "relancer", effet_at="2026-10-15")
        assert resp.status_code == 200

        attendu = (
            datetime(2026, 10, 15, 12, tzinfo=FUSEAU_BRUXELLES)
            .astimezone(timezone.utc)
            .isoformat()
        )
        hist = suivi_storage.historique(_connect(db_path), offer_id)
        relance = next(e for e in hist if e.geste == "relancer")
        assert relance.effet_at == attendu


# ---------------------------------------------------------------------------
# Critère 8 — un second Entretien ajoute une ligne, l'étape reste « entretien »
# (déjà vrai avant la fiche : la table le permet déjà — H2 du ticket)
# ---------------------------------------------------------------------------


class TestCritere8SecondEntretienAjouteUneLigne:
    def test_deux_entretiens_de_suite_restent_a_entretien(self, client, db_path):
        offer_id = 1200
        _en_entretien(client, db_path, offer_id)
        resp2 = _geste(client, offer_id, "entretien")
        assert resp2.status_code == 200
        assert resp2.json()["etat"] == "entretien"

        hist = suivi_storage.historique(_connect(db_path), offer_id)
        assert sum(1 for e in hist if e.geste == "entretien") == 2


# ---------------------------------------------------------------------------
# Critère 9 — Relancer ajoute une ligne sans changer l'étape (déjà vrai)
# ---------------------------------------------------------------------------


class TestCritere9RelancerAjouteUneLigneSansChangerLetape:
    def test_relancer_garde_letape_et_ajoute_une_ligne(self, client, db_path):
        offer_id = 1300
        _en_candidature_envoyee(client, db_path, offer_id)

        resp = _geste(client, offer_id, "relancer")
        assert resp.status_code == 200
        assert resp.json()["etat"] == "candidature_envoyee"

        hist = suivi_storage.historique(_connect(db_path), offer_id)
        assert sum(1 for e in hist if e.geste == "relancer") == 1


# ---------------------------------------------------------------------------
# Critère 10 — Abandonner, Refusée, Sans suite, Offre reçue gardent les
# pièces telles qu'elles sont (déjà vrai)
# ---------------------------------------------------------------------------


class TestCritere10PiecesInchangeesApresGesteDeFin:
    @pytest.mark.parametrize("geste", ["abandonner", "sans_suite", "refuser"])
    def test_pieces_inchangees_depuis_candidature_envoyee(self, client, db_path, geste):
        offer_id = abs(hash(geste)) % 100000 + 4000
        _insert_offer(db_path, offer_id)
        assert _geste(client, offer_id, "retenir").status_code == 200
        _poser_pieces_pretes(db_path, offer_id)
        assert _geste(client, offer_id, "marquer_envoyee").status_code == 200

        avant = client.get(f"/offers/{offer_id}/pieces").json()
        resp = _geste(client, offer_id, geste)
        assert resp.status_code == 200
        apres = client.get(f"/offers/{offer_id}/pieces").json()
        assert apres["cv"] == avant["cv"]
        assert apres["lettre"] == avant["lettre"]

    def test_pieces_inchangees_apres_offre_recue(self, client, db_path):
        offer_id = 4100
        _insert_offer(db_path, offer_id)
        assert _geste(client, offer_id, "retenir").status_code == 200
        _poser_pieces_pretes(db_path, offer_id)
        assert _geste(client, offer_id, "marquer_envoyee").status_code == 200
        assert _geste(client, offer_id, "entretien").status_code == 200

        avant = client.get(f"/offers/{offer_id}/pieces").json()
        resp = _geste(client, offer_id, "offre_recue")
        assert resp.status_code == 200
        apres = client.get(f"/offers/{offer_id}/pieces").json()
        assert apres["cv"] == avant["cv"]
        assert apres["lettre"] == avant["lettre"]


# ---------------------------------------------------------------------------
# Critère 12 — annuler remet l'étape d'avant et retire la ligne de
# l'historique affiché ; en base la ligne reste, marquée annulée.
# ---------------------------------------------------------------------------


class TestCritere12AnnulerRetireLaLigneAfficheeMaisPasEnBase:
    def test_annuler_retire_de_lhistorique_affiche_et_remet_letape(
        self, client, db_path
    ):
        offer_id = 5001
        _en_candidature_envoyee(client, db_path, offer_id)
        assert _geste(client, offer_id, "relancer", motif="note").status_code == 200

        avant = client.get(f"/offers/{offer_id}").json()
        assert any(h["geste"] == "relancer" for h in avant.get("historique", []))

        resp = _geste(client, offer_id, "annuler")
        assert resp.status_code == 200
        assert resp.json()["etat"] == "candidature_envoyee"

        apres = client.get(f"/offers/{offer_id}").json()
        assert all(h["geste"] != "relancer" for h in apres.get("historique", []))

        hist_brut = suivi_storage.historique(_connect(db_path), offer_id)
        relances = [e for e in hist_brut if e.geste == "relancer"]
        assert len(relances) == 1
        assert relances[0].annule_at is not None


# ---------------------------------------------------------------------------
# Critère 13 — annuler jusqu'à Retenir redevient à trier, pièces gardées
# (déjà vrai)
# ---------------------------------------------------------------------------


class TestCritere13AnnulerJusquaRetenirRedevientATrier:
    def test_annuler_jusqu_a_retenir_remet_a_trier_et_garde_les_pieces(
        self, client, db_path
    ):
        offer_id = 9001
        _insert_offer(db_path, offer_id)
        _poser_pieces_pretes(db_path, offer_id)
        assert _geste(client, offer_id, "retenir").status_code == 200
        assert _geste(client, offer_id, "marquer_envoyee").status_code == 200

        assert _geste(client, offer_id, "annuler").status_code == 200
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["tri"] == "retenue"

        assert _geste(client, offer_id, "annuler").status_code == 200
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["tri"] == "a_trier"

        conn = _connect(db_path)
        cv_row = conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        assert cv_row is not None


# ---------------------------------------------------------------------------
# Critère 15 — l'API rend l'historique déjà trié, sans les lignes annulées
# ---------------------------------------------------------------------------


class TestCritere15ApiRendHistoriqueTrieSansAnnulees:
    def test_historique_exclut_la_ligne_annulee(self, client, db_path):
        offer_id = 6001
        _insert_offer(db_path, offer_id)
        assert (
            _geste(
                client, offer_id, "retenir", effet_at="2026-10-18T09:00:00+00:00"
            ).status_code
            == 200
        )
        assert (
            _geste(
                client,
                offer_id,
                "marquer_envoyee",
                effet_at="2026-10-19T09:00:00+00:00",
            ).status_code
            == 200
        )
        assert (
            _geste(
                client,
                offer_id,
                "relancer",
                effet_at="2026-10-20T09:00:00+00:00",
                motif="premier rappel",
            ).status_code
            == 200
        )
        assert (
            _geste(
                client,
                offer_id,
                "relancer",
                effet_at="2026-10-20T09:00:00+00:00",
                motif="a_annuler",
            ).status_code
            == 200
        )
        assert _geste(client, offer_id, "annuler").status_code == 200

        detail = client.get(f"/offers/{offer_id}").json()
        hist = detail.get("historique", [])
        motifs = [h.get("motif") for h in hist]
        assert "a_annuler" not in motifs
        gestes = [h["geste"] for h in hist]
        assert gestes == ["relancer", "marquer_envoyee", "retenir"]
        assert hist[0]["motif"] == "premier rappel"
        assert hist[0]["libelle"] == "Relancer"

    def test_a_date_deffet_egale_le_plus_recemment_enregistre_en_premier(
        self, client, db_path
    ):
        offer_id = 6002
        _en_candidature_envoyee(client, db_path, offer_id)
        meme_date = "2026-10-20T09:00:00+00:00"
        assert (
            _geste(
                client, offer_id, "relancer", effet_at=meme_date, motif="premier"
            ).status_code
            == 200
        )
        assert (
            _geste(
                client, offer_id, "relancer", effet_at=meme_date, motif="second"
            ).status_code
            == 200
        )

        detail = client.get(f"/offers/{offer_id}").json()
        hist = detail.get("historique", [])
        relances = [h for h in hist if h["geste"] == "relancer"]
        assert [h["motif"] for h in relances] == ["second", "premier"]


# ---------------------------------------------------------------------------
# Critère 16 — une offre reprise par EXE-193 montre ses lignes Retenir et
# Marquer envoyée aux dates reprises
# ---------------------------------------------------------------------------


class TestCritere16RepriseMontreSesLignesAuxDatesReprises:
    def test_offre_reprise_candidate_montre_retenir_et_marquer_envoyee(
        self, client, db_path
    ):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title) "
            "VALUES (2, 'test', '2', 'fp2', 'Titre2')"
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at, envoyee_at) "
            "VALUES (2, 'candidaté', '2026-01-10T10:00:00+00:00', NULL)"
        )
        conn.commit()
        suivi_reprise.migrer_verdicts(conn)
        conn.commit()
        conn.close()

        detail = client.get("/offers/2").json()
        hist = detail.get("historique", [])
        gestes = {h["geste"] for h in hist}
        assert gestes == {"retenir", "marquer_envoyee"}
        marquer = next(h for h in hist if h["geste"] == "marquer_envoyee")
        assert marquer["effet_at"] == "2026-01-10T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Critère 17 — un badge pour chacune des étapes de fin, rendu par l'API
# (déjà vrai : `etape_affichee` rend déjà ces valeurs)
# ---------------------------------------------------------------------------


class TestCritere17BadgeApiPourChaqueEtapeDeFin:
    @pytest.mark.parametrize(
        "sequence,etape_attendue",
        [
            (["retenir", "marquer_envoyee", "entretien"], "entretien"),
            (
                ["retenir", "marquer_envoyee", "entretien", "offre_recue"],
                "offre_recue",
            ),
            (["retenir", "marquer_envoyee", "refuser"], "refusee"),
            (["retenir", "marquer_envoyee", "sans_suite"], "sans_suite"),
            (["retenir", "abandonner"], "abandonnee"),
        ],
    )
    def test_etape_rendue_par_lapi(self, client, db_path, sequence, etape_attendue):
        offer_id = abs(hash(tuple(sequence))) % 100000 + 7000
        _insert_offer(db_path, offer_id)
        for g in sequence:
            resp = _geste(client, offer_id, g)
            assert resp.status_code == 200, (g, resp.text)
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etape"] == etape_attendue


# ---------------------------------------------------------------------------
# Critère 18 — la frise montre acquises les étapes réellement franchies, et
# l'étape de fin à sa place
# ---------------------------------------------------------------------------


class TestCritere18FriseMontreLetapeDeFinASaPlace:
    def test_refusee_apres_entretien_garde_candidature_envoyee_et_entretien_acquis(
        self, client, db_path
    ):
        offer_id = 8001
        _insert_offer(db_path, offer_id)
        for g in ["retenir", "marquer_envoyee", "entretien", "refuser"]:
            assert _geste(client, offer_id, g).status_code == 200
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etapes_affichees"] == [
            "retenue",
            "candidature_envoyee",
            "entretien",
            "refusee",
        ]
        # EXE-201, critère 13 : l'étape de fin est elle-même montrée acquise.
        assert detail["etapes_acquises"] == [
            "retenue",
            "prete_a_l_envoi",
            "candidature_envoyee",
            "entretien",
            "refusee",
        ]

    def test_abandonnee_avant_envoi_ne_montre_pas_candidature_envoyee_acquise(
        self, client, db_path
    ):
        offer_id = 8002
        _insert_offer(db_path, offer_id)
        for g in ["retenir", "abandonner"]:
            assert _geste(client, offer_id, g).status_code == 200
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etapes_affichees"] == ["retenue", "abandonnee"]
        assert "candidature_envoyee" not in detail["etapes_acquises"]
