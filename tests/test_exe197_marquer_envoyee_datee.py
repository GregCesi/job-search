"""Tests EXE-197 — « Marquer envoyée » date son geste (jour de Bruxelles,
refus des dates futures, pièce non prête devenue avertissement). DB sous
`tmp_path` (fixture `db_path`, même convention que les autres tickets du
suivi). Aucun appel modèle : la cascade de retenue est un no-op.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
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
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, 'Texte de l offre')",
            (offer_id, str(offer_id), title, company),
        )
        suivi_storage.appliquer_geste(
            conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
        )
        conn.commit()
    finally:
        conn.close()


def _insert_cv(db_path, offer_id, *, statut="done", pret=False):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, _now() if pret else None, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(
    db_path,
    offer_id,
    *,
    decision="a_decider",
    statut="aucune",
    pret=False,
    regeneration_en_cours=False,
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, "
            "regeneration_en_cours, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                offer_id,
                statut,
                decision,
                _now() if pret else None,
                regeneration_en_cours,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _figer_horloge(monkeypatch, iso_utc: str):
    """Remplace l'horloge du module `etats` (H5 du ticket : ni freezegun ni
    time-machine ne sont installés)."""
    fixe = datetime.fromisoformat(iso_utc)
    monkeypatch.setattr(suivi_etats, "maintenant", lambda: fixe)


# ---------------------------------------------------------------------------
# Critère 1 — permis quel que soit l'état du CV et de la lettre
# ---------------------------------------------------------------------------

CAS_PIECES_CRITERE_1 = [
    # (nom, cv_kwargs|None, lettre_kwargs|None)
    ("cv_jamais_genere_lettre_jamais_generee", None, None),
    ("cv_en_cours_lettre_a_decider", {"statut": "pending", "pret": False}, None),
    (
        "cv_genere_sans_marque_lettre_demandee_en_cours",
        {"statut": "done", "pret": False},
        {"decision": "demandee", "statut": "pending", "pret": False},
    ),
    (
        "cv_pret_lettre_sans_lettre",
        {"statut": "done", "pret": True},
        {"decision": "sans_lettre", "statut": "aucune", "pret": False},
    ),
    (
        "cv_pret_lettre_prete",
        {"statut": "done", "pret": True},
        {"decision": "demandee", "statut": "done", "pret": True},
    ),
]


class TestCritere1MarquerEnvoyeePermisQuelQueSoitLEtatDesPieces:
    @pytest.mark.parametrize("nom,cv_kwargs,lettre_kwargs", CAS_PIECES_CRITERE_1)
    def test_marquer_envoyee_dans_gestes_permis(
        self, client, db_path, nom, cv_kwargs, lettre_kwargs
    ):
        offer_id = abs(hash(nom)) % 100000 + 1
        _insert_offer(db_path, offer_id)
        if cv_kwargs is not None:
            _insert_cv(db_path, offer_id, **cv_kwargs)
        if lettre_kwargs is not None:
            _insert_lettre(db_path, offer_id, **lettre_kwargs)

        detail = client.get(f"/offers/{offer_id}").json()
        assert "marquer_envoyee" in detail["gestes_permis"], nom

        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        assert pieces["envoyee_le"] is None

        res = client.put(f"/offers/{offer_id}/envoyee", json={"envoyee": True})
        assert res.status_code == 200, (nom, res.json())
        assert res.json()["envoyee_le"]


# ---------------------------------------------------------------------------
# Critère 2 — date par défaut = jour de Bruxelles rendu par l'API
# ---------------------------------------------------------------------------


class TestCritere2DateParDefautJourDeBruxelles:
    def test_pieces_rend_le_jour_de_bruxelles(self, client, db_path, monkeypatch):
        offer_id = 50
        _insert_offer(db_path, offer_id)
        # 23h locale Bruxelles le 21/10 (CEST, +2) = 21h UTC le même jour.
        _figer_horloge(monkeypatch, "2026-10-21T21:00:00+00:00")

        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        assert pieces["aujourd_hui_bruxelles"] == "2026-10-21"


# ---------------------------------------------------------------------------
# Critère 3 — date passée acceptée
# ---------------------------------------------------------------------------


class TestCritere3DatePasseeAcceptee:
    def test_date_passee_enregistree_et_affichee(self, client, db_path, monkeypatch):
        offer_id = 51
        _insert_offer(db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        res = client.put(
            f"/offers/{offer_id}/envoyee",
            json={"envoyee": True, "effet_at": "2026-10-15"},
        )
        assert res.status_code == 200
        assert res.json()["envoyee_le"] is not None

        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etape"] == "candidature_envoyee"


# ---------------------------------------------------------------------------
# Critère 4 et mutant E1 — date future refusée
# ---------------------------------------------------------------------------


class TestCritere4DateFutureRefuseeEtMutantE1:
    def test_date_future_refusee_offre_ne_change_pas(
        self, client, db_path, monkeypatch
    ):
        offer_id = 52
        _insert_offer(db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        res = client.put(
            f"/offers/{offer_id}/envoyee",
            json={"envoyee": True, "effet_at": "2026-10-22"},
        )
        assert res.status_code == 409
        assert "postérieure" in res.json()["detail"]

        # L'offre n'a pas changé (mutant E1 : une date de demain acceptée).
        assert suivi_storage.date_envoyee(_connect(db_path), offer_id) is None
        assert suivi_storage.etat_stocke(_connect(db_path), offer_id) == "retenue"


# ---------------------------------------------------------------------------
# Critère 5 et mutant E2 — aujourd'hui accepté même après minuit à Bruxelles
# ---------------------------------------------------------------------------


class TestCritere5AujourdhuiAccepteApres00h30BruxellesEtMutantE2:
    def test_accepte_a_00h30_heure_de_bruxelles(self, client, db_path, monkeypatch):
        offer_id = 53
        _insert_offer(db_path, offer_id)
        # 00h30 heure de Bruxelles (CEST, +2) le 21/10 == 22h30 UTC le 20/10 :
        # un calcul du jour en UTC (mutant E2) donnerait « 2026-10-20 » et
        # refuserait la date du jour « 2026-10-21 ».
        _figer_horloge(monkeypatch, "2026-10-20T22:30:00+00:00")

        res = client.put(
            f"/offers/{offer_id}/envoyee",
            json={"envoyee": True, "effet_at": "2026-10-21"},
        )
        assert res.status_code == 200
        assert res.json()["envoyee_le"] is not None


# ---------------------------------------------------------------------------
# Critère 6 et mutant E5 — pendant la génération de la lettre
# ---------------------------------------------------------------------------


class TestCritere6MarquerPendantGenerationLettreEtMutantE5:
    def test_envoyee_pendant_generation_sans_erreur(self, client, db_path):
        offer_id = 54
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="pending", pret=False)
        _insert_lettre(
            db_path,
            offer_id,
            decision="demandee",
            statut="pending",
            pret=False,
            regeneration_en_cours=True,
        )

        res = client.put(f"/offers/{offer_id}/envoyee", json={"envoyee": True})
        assert res.status_code == 200
        assert res.json()["envoyee_le"] is not None

        # La génération continue : la ligne `lettres` n'est pas touchée par
        # `marquer_envoyee` (mutant E5 : refusé pendant la génération).
        row = (
            _connect(db_path)
            .execute(
                "SELECT regeneration_en_cours, statut FROM lettres WHERE offer_id = ?",
                (offer_id,),
            )
            .fetchone()
        )
        assert row["regeneration_en_cours"]
        assert row["statut"] == "pending"


# ---------------------------------------------------------------------------
# Critère 7 — date sans heure enregistrée à midi, heure de Bruxelles, en UTC
# ---------------------------------------------------------------------------


class TestCritere7DateSansHeureMidiBruxellesEnUTC:
    def test_date_seule_enregistree_a_midi_bruxelles(
        self, client, db_path, monkeypatch
    ):
        offer_id = 55
        _insert_offer(db_path, offer_id)
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        res = client.put(
            f"/offers/{offer_id}/envoyee",
            json={"envoyee": True, "effet_at": "2026-10-15"},
        )
        assert res.status_code == 200

        attendu = (
            datetime(2026, 10, 15, 12, tzinfo=FUSEAU_BRUXELLES)
            .astimezone(timezone.utc)
            .isoformat()
        )
        assert suivi_storage.date_envoyee(_connect(db_path), offer_id) == attendu


# ---------------------------------------------------------------------------
# Critère 10 et mutant E4 — la liste des pièces manquantes, et le texte nomme
# la lettre quand seule elle manque
# ---------------------------------------------------------------------------


class TestCritere10ListeDesPiecesNonPreteEtMutantE4:
    def test_liste_vide_quand_tout_est_pret(self, client, db_path):
        offer_id = 56
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", pret=True)
        _insert_lettre(db_path, offer_id, decision="demandee", statut="done", pret=True)

        detail = client.get(f"/offers/{offer_id}").json()
        marquer = next(g for g in detail["gestes"] if g["geste"] == "marquer_envoyee")
        assert marquer["permis"] is True
        assert marquer["pieces_non_pretes"] == []
        assert marquer["raison"] is None

    def test_liste_nomme_la_lettre_seule_quand_seule_elle_manque(self, client, db_path):
        offer_id = 57
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", pret=True)
        _insert_lettre(
            db_path, offer_id, decision="demandee", statut="done", pret=False
        )

        detail = client.get(f"/offers/{offer_id}").json()
        marquer = next(g for g in detail["gestes"] if g["geste"] == "marquer_envoyee")
        assert marquer["permis"] is True
        assert marquer["pieces_non_pretes"] == ["lettre"]
        # Mutant E4 : l'avertissement ne nomme pas la lettre quand seule elle manque.
        assert "lettre" in marquer["raison"]
        assert "CV" not in marquer["raison"]


# ---------------------------------------------------------------------------
# Critère 11 et mutant E3 — confirmer ne touche pas les marques Prête
# ---------------------------------------------------------------------------


class TestCritere11ConfirmerNeTouchePasLesMarquesPreteEtMutantE3:
    def test_marque_pret_inchangee_apres_envoyee(self, client, db_path):
        offer_id = 58
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", pret=False)
        _insert_lettre(
            db_path, offer_id, decision="demandee", statut="done", pret=False
        )

        res = client.put(f"/offers/{offer_id}/envoyee", json={"envoyee": True})
        assert res.status_code == 200

        conn = _connect(db_path)
        cv_row = conn.execute(
            "SELECT marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        lettre_row = conn.execute(
            "SELECT marque_pret_at FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        # Mutant E3 : « marquer envoyée » pose la marque Prête des pièces.
        assert cv_row["marque_pret_at"] is None
        assert lettre_row["marque_pret_at"] is None


# ---------------------------------------------------------------------------
# Critère 16 (déjà couvert) — pointeur, pas de nouveau test
# ---------------------------------------------------------------------------

# EXE-197, critère 16 : les dates d'envoi déjà en base (reprise) ne changent
# pas. `reprise.py::_ecrire_evenement` écrit en SQL direct, jamais par
# `storage.appliquer_geste` — la règle de date de ce ticket ne s'applique
# donc jamais à une ligne reprise. Déjà prouvé, toujours vert sans ce
# ticket : tests/test_exe193_reprise.py::TestCritere20DateDenvoiTelleQuelle.


# ---------------------------------------------------------------------------
# Critère 17 — le front ne décide plus le bouton depuis prete_a_l_envoi /
# tout_telecharger_raison / envoyee_le
# ---------------------------------------------------------------------------

OFFER_PAGE = (
    Path(__file__).resolve().parent.parent
    / "web"
    / "app"
    / "pages"
    / "offers"
    / "[id].vue"
)


class TestCritere17FrontNeDecidePlusLeBoutonCandidatureEnvoyee:
    def test_bouton_ne_lit_plus_prete_a_l_envoi_ni_tout_telecharger_raison(self):
        texte = OFFER_PAGE.read_text(encoding="utf-8")
        # Ancien calcul fautif (avant EXE-197) : bouton désactivé et
        # explication lus depuis `prete_a_l_envoi` / `tout_telecharger_raison`.
        assert "!pieces?.prete_a_l_envoi" not in texte
        assert (
            "envoyeeRaison = computed(() => offer.value?.tout_telecharger_raison"
            not in texte
        )
        # L'avertissement vient désormais du geste « marquer_envoyee » rendu
        # par l'API, jamais recalculé ici (critères 9-10).
        assert "marquer_envoyee" in texte
        assert "envoyeeAvertissement" in texte
