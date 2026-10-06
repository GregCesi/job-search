"""Tests EXE-132 — la fiche désigne elle-même les points de la lettre, quatre au
plus ; la lettre lancée au geste de retenir n'est écrite que sur ceux-là, jamais
sur tous les points de la fiche (TCK-281).

Aucun test n'appelle un modèle : `query` du SDK Claude Agent (fiche, lettre) est
remplacé par une doublure. Aucun test ne lit ni n'écrit sous data/ : DB,
préférences de ton, tournures interdites et CV de référence sont des fichiers
tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage

import api.avancement as api_avancement
import api.db as api_db
import api.lettre as lettre_api
import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.lettre.redaction import RAISON_FICHE_AUCUNE_DESIGNATION
from orchestrator.job_search.storage.db import init_db

PREFERENCES_TON = "# Préférences de ton\n- Direct, sans emphase\n"
TOURNURES_INTERDITES = "je veux\n"


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire."""

    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _fiche_result(points, points_pour_lettre, session_id="fiche-session"):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.1,
        result=None,
        structured_output={
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
            "points_pour_lettre": points_pour_lettre,
        },
    )


def _lettre_result(texte="Voici ma lettre de motivation.", session_id="lettre-session"):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.03,
        result=texte,
        structured_output=None,
    )


def _jamais_appele(nom):
    def behavior(prompt, options):
        raise AssertionError(
            f"le modèle {nom} a été rappelé alors qu'il ne devait pas l'être"
        )

    return behavior


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
def lettre_fixture_paths(tmp_path, monkeypatch):
    prefs = tmp_path / "preferences_ton.md"
    prefs.write_text(PREFERENCES_TON, encoding="utf-8")
    tournures = tmp_path / "tournures_interdites.txt"
    tournures.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    cv_ref = tmp_path / "cv_reference.html"
    cv_ref.write_text("<p>Contenu CV de test</p>", encoding="utf-8")
    monkeypatch.setattr(lettre_service, "LETTRE_PREFERENCES_PATH", prefs)
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    monkeypatch.setattr(lettre_service, "CV_REFERENCE_PATH", cv_ref)
    return prefs, tournures, cv_ref


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
    finally:
        conn.close()


def _points(n: int, pour_lettre_indices: set[int] | None = None) -> list[dict]:
    pour_lettre_indices = pour_lettre_indices or set()
    return [
        {
            "position": f"Point {i}",
            "citation": f"Citation {i}",
            "url": None,
            "tas": None,
            "explication": None,
            "pour_lettre": i in pour_lettre_indices,
        }
        for i in range(n)
    ]


def _insert_fiche(db_path, offer_id, points, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, ?, 'Présentation ACME.', ?, '2026-10-06')",
            (offer_id, statut, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre_choix_moi(db_path, offer_id, indices):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, points_choisis_json, "
            "points_choisis_origine, created_at) VALUES (?, 'aucune', ?, 'moi', '2026-10-06')",
            (offer_id, json.dumps(sorted(indices))),
        )
        conn.commit()
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


def _lettre_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def _points_pour_lettre(db_path, offer_id) -> list[int]:
    points = json.loads(_fiche_row(db_path, offer_id)["points_json"])
    return [i for i, p in enumerate(points) if p.get("pour_lettre")]


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


class TestCritere1PromptDemandeLaDesignation:
    def test_le_prompt_demande_de_designer_quatre_points_au_plus(self, db_path):
        _insert_offer(db_path, 1)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        offer = conn.execute(
            "SELECT title, company, location, url, description, description_raw "
            "FROM offers WHERE id = ?",
            (1,),
        ).fetchone()
        conn.close()
        cascade = CascadeResult(
            nom="ACME",
            entite=None,
            confiance="sur",
            type_source="direct",
            methode="test",
            etape=1,
        )
        prompt = fiche_prompt.build_prompt(offer, cascade)
        assert "points_pour_lettre" in prompt
        assert "quatre" in prompt.lower()


class TestCritere2Et3LettreEcriteSurLesPointsDesignes:
    def test_trois_points_designes_lettre_ecrite_dessus_seulement(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        designes = {0, 2, 4}
        _insert_fiche(db_path, offer_id, _points(8, designes))
        monkeypatch.setattr(
            lettre_service, "query", _make_query(lambda p, o: [_lettre_result()])
        )

        asyncio.run(_scenario_launch(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"
        chosen = set(json.loads(row["points_choisis_json"]))
        assert chosen == designes


async def _scenario_launch(offer_id):
    task = await lettre_api.launch_lettre_if_ready(offer_id)
    if task is not None:
        await task
    await _drain()


class TestCritere4PlafondQuatrePremiersDesignes:
    def test_six_designes_les_quatre_premiers_gardes(self, db_path, monkeypatch):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [{"position": f"Point {i}"} for i in range(8)],
                        points_pour_lettre=[0, 1, 2, 3, 4, 5],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        assert _points_pour_lettre(db_path, offer_id) == [0, 1, 2, 3]


class TestCritere5DesignationInexistanteIgnoree:
    def test_index_hors_liste_ignore_les_autres_gardes(self, db_path, monkeypatch):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [{"position": f"Point {i}"} for i in range(3)],
                        points_pour_lettre=[0, 99, 2],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        assert _points_pour_lettre(db_path, offer_id) == [0, 2]


class TestCritere6Et7FicheSansDesignationPasDeLettre:
    def test_aucun_point_designe_lettre_non_lancee_phrase_dediee(
        self, db_path, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points(5, set()))
        monkeypatch.setattr(
            lettre_service, "query", _make_query(_jamais_appele("lettre"))
        )

        asyncio.run(_scenario_launch(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row is not None
        assert row["statut"] == "aucune"
        assert not lettre_api.is_running(offer_id)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            avancement = api_avancement._compute_avancement(conn, offer_id)
        finally:
            conn.close()
        assert avancement["lettre"]["etat"] == "en_attente"
        assert avancement["lettre"]["raison"] == RAISON_FICHE_AUCUNE_DESIGNATION


class TestCritere8OrigineSysteme:
    def test_choix_designe_par_la_fiche_dit_systeme(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points(4, {1}))
        monkeypatch.setattr(
            lettre_service, "query", _make_query(lambda p, o: [_lettre_result()])
        )

        asyncio.run(_scenario_launch(offer_id))

        assert lettre_api.get_lettre(offer_id)["points_choisis_origine"] == "systeme"


class TestCritere9ChoixDejaFaitNonRemplace:
    def test_choix_pose_avant_la_fin_de_la_fiche_n_est_pas_remplace(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points(5, {1, 2, 3}))
        _insert_lettre_choix_moi(db_path, offer_id, [0])
        monkeypatch.setattr(
            lettre_service, "query", _make_query(lambda p, o: [_lettre_result()])
        )

        asyncio.run(_scenario_launch(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["points_choisis_origine"] == "moi"
        assert json.loads(row["points_choisis_json"]) == [0]
