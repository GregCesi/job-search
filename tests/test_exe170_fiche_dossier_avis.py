"""Tests EXE-170 — la fiche entreprise devient un dossier : manques, alertes,
sources, et mon avis (critères 1 à 10).

Aucun test n'appelle un modèle : `query` du SDK Claude Agent (fiche) est remplacé
par une doublure. Aucun test ne lit ni n'écrit sous data/ : DB est un fichier
tmp_path.
"""

import asyncio
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi.testclient import TestClient

import api.db as api_db
import api.fiche as fiche_api
import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire."""

    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _fiche_result(
    points,
    manques=None,
    alertes=None,
    sources=None,
    session_id="fiche-session",
    extra_structured=None,
):
    structured = {
        "mode": "entreprise",
        "presentation": "Présentation ACME.",
        "employeur": {
            "nom": "ACME",
            "entite_precise": None,
            "type_source": "direct",
            "methode": "test",
            "confiance": "sur",
            "urls": [],
        },
        "points": points,
    }
    if manques is not None:
        structured["manques"] = manques
    if alertes is not None:
        structured["alertes"] = alertes
    if sources is not None:
        structured["sources"] = sources
    if extra_structured:
        structured.update(extra_structured)
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.1,
        result=None,
        structured_output=structured,
    )


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
def _stub_cascade_employeur(monkeypatch):
    """La cascade d'identification employeur appelle Ollama : hors périmètre de ce
    ticket, et interdit en test. Doublure déterministe, jamais de réseau."""

    def _fake(offer_id, conn, model=None, host=None):
        return CascadeResult(
            nom="ACME",
            entite=None,
            confiance="sur",
            type_source="direct",
            methode="test",
            etape=1,
        )

    monkeypatch.setattr(fiche_service, "identify_employer", _fake)


@pytest.fixture(autouse=True)
def _repertoire_absent_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setattr(
        fiche_prompt, "REPERTOIRE_LETTRE_PATH", tmp_path / "absent" / "repertoire.yaml"
    )


def _insert_offer(db_path, offer_id, description_raw="Texte complet de l'offre."):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, description_raw) VALUES (?, 'test', ?, 'fp', 'Ingénieur H/F', "
            "'ACME', 'Strasbourg', ?)",
            (offer_id, str(offer_id), description_raw),
        )
        conn.commit()
        suivi_storage.appliquer_geste(
            conn, offer_id, suivi_etats.RETENIR, effet_at="2026-10-01"
        )
    finally:
        conn.close()


def _fiche_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def _insert_fiche_ancienne(db_path, offer_id):
    """Fiche produite avant EXE-170 (critère 4) : aucune des trois colonnes
    manques_json/alertes_json/sources_json n'est renseignée."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, 'done', 'Présentation ACME.', '[]', '2026-10-01')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


# --- critères 1, 2 ---------------------------------------------------------


class TestCriteres1et2TroisListesRenduesEtRelues:
    def test_manques_alertes_sources_persistes_et_relus_par_l_api(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                        manques=["Pas trouvé le CA", "Pas d'avis Glassdoor"],
                        alertes=["Aucune mention de l'évaluation des workflows IA"],
                        sources=[
                            {"titre": "Site ACME", "url": "https://acme.test"},
                        ],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        # « redémarrage » : nouvel appel de lecture, nouvelle connexion
        fiche = fiche_api.get_fiche(offer_id)
        assert fiche["manques"] == ["Pas trouvé le CA", "Pas d'avis Glassdoor"]
        assert fiche["alertes"] == ["Aucune mention de l'évaluation des workflows IA"]
        assert fiche["sources"] == [{"titre": "Site ACME", "url": "https://acme.test"}]


# --- critère 3 --------------------------------------------------------------


class TestCritere3ListeManquanteDevientVide:
    @pytest.mark.parametrize("champ_absent", ["manques", "alertes", "sources"])
    def test_champ_absent_de_la_reponse_devient_liste_vide_sans_erreur(
        self, db_path, monkeypatch, champ_absent
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        valeurs = {
            "manques": ["un manque"],
            "alertes": ["une alerte"],
            "sources": [{"titre": "Site", "url": "https://exemple.test"}],
        }
        valeurs.pop(champ_absent)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                        **valeurs,
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        row = _fiche_row(db_path, offer_id)
        assert row["statut"] == "done"
        fiche = fiche_api.get_fiche(offer_id)
        assert fiche[champ_absent] == []


# --- critère 4 ---------------------------------------------------------------


class TestCritere4FicheAncienneTroisListesVides:
    def test_fiche_anterieure_sans_colonnes_renseignees_lue_sans_erreur(self, db_path):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)

        fiche = fiche_api.get_fiche(offer_id)

        assert fiche["manques"] == []
        assert fiche["alertes"] == []
        assert fiche["sources"] == []


# --- critère 5 ---------------------------------------------------------------


class TestCritere5SourceSansLienHttpEcartee:
    def test_source_sans_lien_http_ou_https_n_est_pas_gardee(
        self, db_path, monkeypatch
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[{"position": "Point A", "citation": "c", "url": None}],
                        sources=[
                            {"titre": "Site ACME", "url": "https://acme.test"},
                            {"titre": "Fichier local", "url": "file:///etc/passwd"},
                            {"titre": "Sans lien", "url": None},
                            {"titre": "FTP", "url": "ftp://exemple.test"},
                        ],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        assert fiche["sources"] == [{"titre": "Site ACME", "url": "https://acme.test"}]


# --- critère 6 ---------------------------------------------------------------


class TestCritere6PointsInchanges:
    def test_points_famille_et_sujet_inchanges_par_les_trois_listes(
        self, db_path, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        points=[
                            {
                                "position": "Point A",
                                "citation": "c",
                                "url": "https://exemple.test",
                                "famille": "preuve_ia",
                                "date": "2026",
                            }
                        ],
                        manques=["m"],
                        alertes=["a"],
                        sources=[{"titre": "t", "url": "https://exemple.test"}],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        assert len(fiche["points"]) == 1
        point = fiche["points"][0]
        assert point["position"] == "Point A"
        assert point["famille"] == "preuve_ia"
        assert point["date"] == "2026"


# --- critères 7, 8 -----------------------------------------------------------


class TestCriteres7et8MonAvisEnregistreEtEffacable:
    def test_avis_enregistre_et_relu_apres_rechargement(self, db_path, client):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)

        resp = client.put(
            f"/offers/{offer_id}/fiche/avis",
            json={"avis": "Je trouve cette entreprise prometteuse."},
        )
        assert resp.status_code == 204

        fiche = client.get(f"/offers/{offer_id}/fiche").json()
        assert fiche["avis"] == "Je trouve cette entreprise prometteuse."

    def test_avis_vide_apres_effacement(self, db_path, client):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)
        client.put(f"/offers/{offer_id}/fiche/avis", json={"avis": "Un avis."})

        resp = client.put(f"/offers/{offer_id}/fiche/avis", json={"avis": ""})
        assert resp.status_code == 204

        fiche = client.get(f"/offers/{offer_id}/fiche").json()
        assert fiche["avis"] in (None, "")


# --- critère 9 ----------------------------------------------------------------


class TestCritere9AvisTropLongRefuse:
    def test_avis_de_plus_de_4000_caracteres_refuse_avec_la_limite(
        self, db_path, client
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)

        resp = client.put(f"/offers/{offer_id}/fiche/avis", json={"avis": "x" * 4001})

        assert resp.status_code == 422
        assert "4000" in resp.json()["detail"]
        fiche = client.get(f"/offers/{offer_id}/fiche").json()
        assert fiche["avis"] is None


# --- critère 10 ---------------------------------------------------------------


class TestCritere10AvisNAtteintAucunModele:
    def test_enregistrer_un_avis_n_appelle_aucun_modele(
        self, db_path, client, monkeypatch
    ):
        offer_id = 10
        _insert_offer(db_path, offer_id)
        _insert_fiche_ancienne(db_path, offer_id)

        def _interdit(*args, **kwargs):
            raise AssertionError("aucun appel de modèle ne doit partir de l'avis")

        monkeypatch.setattr(fiche_service, "query", _interdit)

        resp = client.put(
            f"/offers/{offer_id}/fiche/avis", json={"avis": "Mon avis sur ACME."}
        )

        assert resp.status_code == 204
