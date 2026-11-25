"""Tests EXE-212 — retenir une offre lance le CV seul ; la fiche entreprise ne
part que de « Préparer la fiche » ou de « Générer la lettre » quand elle manque.

Aucun test n'appelle un modèle (ticket, « Ce qui ne doit pas arriver ») : un
lancement se compte en remplaçant ce qui lance (H6) — `run_fiche`, `run_cv` et
`run_lettre` des routes de l'API sont des enregistreurs, et pour les critères
16-17 `query` du SDK est un faux générateur. Aucun test ne lit ni n'écrit sous
data/ : DB, CV de référence, profils et gabarits sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

import api.avancement as api_avancement
import api.cv as api_cv
import api.db as api_db
import api.fiche as api_fiche
import api.lettre as api_lettre
import api.offers as api_offers
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.storage.db as storage_db
import tests.test_exe184_cv_profil_claude as outillage_cv
from api.schemas import VerdictIn
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

cv_fixture_paths = outillage_cv.cv_fixture_paths


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
def appels(monkeypatch, db_path):
    """Compte chaque lancement de fiche, de CV et de lettre. La fausse fiche se
    termine (`statut = 'done'`) pour que sa suite — la lettre demandée — puisse
    partir (critère 10) ; le faux CV et la fausse lettre ne font rien d'autre
    que compter."""
    compte: dict[str, list[int]] = {"fiche": [], "cv": [], "lettre": []}

    async def _fiche(offer_id, *a, **k):
        compte["fiche"].append(offer_id)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE fiches_entreprise SET statut = 'done' WHERE offer_id = ?",
                (offer_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def _compteur(nom):
        async def _faux(offer_id, *a, **k):
            compte[nom].append(offer_id)

        return _faux

    monkeypatch.setattr(api_fiche, "run_fiche", _fiche)
    monkeypatch.setattr(api_cv, "run_cv", _compteur("cv"))
    monkeypatch.setattr(api_lettre, "run_lettre", _compteur("lettre"))
    return compte


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_offer(db_path, offer_id, *, retenue=False, techs=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, description_raw, extracted_facts_json) VALUES "
            "(?, 'test', ?, 'fp', 'Ingénieur H/F', 'ACME', 'Strasbourg', "
            "'Texte complet de l offre.', ?)",
            (offer_id, str(offer_id), json.dumps({"techs_required": techs or []})),
        )
        if retenue:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche_done(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, mode, presentation, "
            "employeur_nom, points_json, created_at) VALUES "
            "(?, 'done', 'entreprise', 'Présentation ACME.', 'ACME', ?, ?)",
            (
                offer_id,
                json.dumps([{"position": "Point A", "citation": "C", "url": None}]),
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _fiche_row(db_path, offer_id):
    conn = _connect(db_path)
    try:
        return conn.execute(
            "SELECT * FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _run(*coros_factories):
    async def _scenario():
        for factory in coros_factories:
            await factory()
            await _drain()

    asyncio.run(_scenario())


def _geste_retenir(offer_id):
    return lambda: api_offers.appliquer_geste_route(
        offer_id, api_offers.GesteIn(geste=suivi_etats.RETENIR)
    )


def _verdict_retenu(offer_id):
    return lambda: api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))


def _generer_lettre(offer_id):
    return lambda: api_lettre.create_lettre(offer_id, Response())


# ---------------------------------------------------------------------------
# Retenir — critères 1 à 5
# ---------------------------------------------------------------------------


class TestCriteres1Et2RetenirParGeste:
    def test_critere1_le_cv_est_lance_une_fois(self, db_path, appels):
        _insert_offer(db_path, 1)
        _run(_geste_retenir(1))
        assert appels["cv"] == [1]

    def test_critere2_aucune_fiche_lancee_ni_en_base(self, db_path, appels):
        _insert_offer(db_path, 2)
        _run(_geste_retenir(2))
        assert appels["fiche"] == []
        assert _fiche_row(db_path, 2) is None


class TestCriteres3Et4RetenirParVerdict:
    def test_critere3_le_cv_est_lance_une_fois(self, db_path, appels):
        _insert_offer(db_path, 3)
        _run(_verdict_retenu(3))
        assert appels["cv"] == [3]

    def test_critere4_aucune_fiche_lancee_ni_en_base(self, db_path, appels):
        _insert_offer(db_path, 4)
        _run(_verdict_retenu(4))
        assert appels["fiche"] == []
        assert _fiche_row(db_path, 4) is None


class TestCritere5AvancementSansFiche:
    def test_fiche_ni_en_cours_ni_en_erreur(self, db_path, appels):
        _insert_offer(db_path, 5)
        _run(_geste_retenir(5))
        fiche = api_avancement.get_avancement(5)["fiche"]
        assert fiche["etat"] not in {"en_cours", "en_erreur"}


# ---------------------------------------------------------------------------
# La fiche à la demande — critère 7 (le 6 est au navigateur)
# ---------------------------------------------------------------------------


class TestCritere7PreparerLaFiche:
    def test_la_fiche_est_lancee_une_fois(self, db_path, appels):
        _insert_offer(db_path, 7, retenue=True)
        _run(lambda: api_fiche.create_fiche(7))
        assert appels["fiche"] == [7]


# ---------------------------------------------------------------------------
# La lettre — critères 8, 10, 11, 12 (le 9 est au navigateur)
# ---------------------------------------------------------------------------


class TestCritere8GenererLaLettreLanceLaFiche:
    def test_la_fiche_est_lancee_une_fois(self, db_path, appels):
        _insert_offer(db_path, 8, retenue=True)
        _run(_generer_lettre(8))
        assert appels["fiche"] == [8]


class TestCritere10LaFicheFinitLaLettrePart:
    def test_la_lettre_est_lancee_sans_autre_clic(self, db_path, appels):
        _insert_offer(db_path, 10, retenue=True)
        _run(_generer_lettre(10))
        assert _fiche_row(db_path, 10)["statut"] == "done"
        assert appels["lettre"] == [10]


class TestCritere11FicheDejaTermineeNonRelancee:
    def test_aucun_lancement_de_fiche(self, db_path, appels):
        _insert_offer(db_path, 11, retenue=True)
        _insert_fiche_done(db_path, 11)
        _run(_generer_lettre(11))
        assert appels["fiche"] == []


class TestCritere12NePasFaireNeLanceRien:
    def test_ni_fiche_ni_lettre(self, db_path, appels):
        _insert_offer(db_path, 12, retenue=True)
        _run(lambda: api_lettre.ne_pas_faire_lettre(12))
        assert appels["fiche"] == []
        assert appels["lettre"] == []


# ---------------------------------------------------------------------------
# L'envoi sans fiche — critères 13, 14
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db_path, appels):
    import api.main as api_main

    return TestClient(api_main.app)


def _cv_pret(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, _now(), _now()),
        )
        conn.commit()
    finally:
        conn.close()


class TestCriteres13Et14EnvoiSansFiche:
    def _preparer(self, client, db_path, offer_id):
        _insert_offer(db_path, offer_id, retenue=True)
        _cv_pret(db_path, offer_id)
        res = client.post(f"/offers/{offer_id}/lettre/ne-pas-faire")
        assert res.status_code == 200
        assert _fiche_row(db_path, offer_id) is None

    def test_critere13_prete_a_l_envoi(self, client, db_path):
        self._preparer(client, db_path, 13)
        assert client.get("/offers/13").json()["etape"] == "prete_a_l_envoi"

    def test_critere14_marquee_envoyee(self, client, db_path):
        self._preparer(client, db_path, 14)
        res = client.put("/offers/14/envoyee", json={"envoyee": True})
        assert res.status_code == 200
        assert client.get("/offers/14").json()["etape"] == "candidature_envoyee"


# ---------------------------------------------------------------------------
# Ce qui existait déjà — critères 15 à 17
# ---------------------------------------------------------------------------


class TestCritere15FicheTermineeAvantCeTour:
    def test_la_fiche_se_lit_comme_avant(self, client, db_path):
        _insert_offer(db_path, 15, retenue=True)
        _insert_fiche_done(db_path, 15)
        fiche = client.get("/offers/15/fiche").json()
        assert fiche["statut"] == "done"
        assert fiche["presentation"] == "Présentation ACME."
        assert fiche["employeur_nom"] == "ACME"
        assert [p["position"] for p in fiche["points"]] == ["Point A"]


def _faux_sdk_cv(monkeypatch):
    def _behavior(prompt, options):
        return [outillage_cv._fake_result(structured_output={"groupes": []})]

    monkeypatch.setattr(cv_service, "query", outillage_cv._make_query(_behavior))

    async def _fiche_inerte(offer_id, *a, **k):
        return None

    monkeypatch.setattr(api_fiche, "run_fiche", _fiche_inerte)


class TestCriteres16Et17ProfilDuCvSansFiche:
    def _retenir(self, db_path, monkeypatch, offer_id, techs):
        _insert_offer(db_path, offer_id, techs=techs)
        _faux_sdk_cv(monkeypatch)
        _run(_geste_retenir(offer_id))
        assert _fiche_row(db_path, offer_id) is None
        conn = _connect(db_path)
        try:
            return conn.execute(
                "SELECT statut, profil, profil_motif FROM cvs WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
        finally:
            conn.close()

    def test_critere16_claude_dans_les_technos(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        row = self._retenir(
            db_path,
            monkeypatch,
            16,
            [{"name": "Claude Agent SDK", "importance": "required"}],
        )
        assert row["statut"] == "done"
        assert row["profil"] == "claude"

    def test_critere17_sans_claude_profil_base(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        row = self._retenir(
            db_path, monkeypatch, 17, [{"name": "Python", "importance": "required"}]
        )
        assert row["statut"] == "done"
        assert row["profil"] == "base"
