"""Tests EXE-84 — la lettre est écrite sur l'offre : le modèle reçoit son intitulé et
son texte, même quand le texte brut de l'annonce manque.

Couvre : priorité texte brut / texte nettoyé (critères 1-3), intitulé présent et placé
avant le texte de l'offre (critères 4-5), refus quand les deux textes sont vides
(critère 6).

Aucun test n'appelle le modèle : `query` du SDK Claude Agent est remplacé par un faux
générateur async, ou monkeypatché pour lever si on l'appelle par erreur. Aucun test ne
lit ni n'écrit sous data/ : DB, préférences de ton, tournures interdites et CV de
référence sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException, Response

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db

PREFERENCES_TON = "# Préférences de ton\n- Direct, sans emphase\n"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\ncordialement\n"


def _fake_result(result=None, is_error=False, session_id="fake-session", cost=0.02):
    return ResultMessage(
        subtype="success" if not is_error else "error_during_execution",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
        result=result,
        structured_output=None,
    )


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire (ou lève une exception)."""

    async def _query(*, prompt, options):
        msgs = behavior(prompt, options)
        for m in msgs:
            yield m

    return _query


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


def _insert_offer(
    db_path,
    offer_id,
    title="Titre offre",
    description_raw="",
    description="",
    verdict="retenu",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, description) VALUES (?, 'test', ?, 'fp', ?, ?, ?)",
            (offer_id, str(offer_id), title, description_raw, description),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-30')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _points_8() -> list[dict]:
    tas_par_index = ["lettre", "lettre", "entretien", "rien", None, None, None, None]
    return [
        {
            "position": f"Point {i}",
            "citation": f"Citation {i}",
            "url": None,
            "tas": tas,
            "explication": None,
        }
        for i, tas in enumerate(tas_par_index)
    ]


def _insert_fiche(db_path, offer_id, points, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, ?, 'Présentation', ?, '2026-09-28')",
            (offer_id, statut, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
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


class TestCritere1TexteNettoyeQuandBrutVide:
    def test_brut_vide_nettoye_rempli_envoie_le_nettoye(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8401
        _insert_offer(
            db_path,
            offer_id,
            description_raw="",
            description="Texte nettoyé offre 8401.",
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Texte nettoyé offre 8401." in prompt_text


class TestCritere2BrutPrioritaireSurNettoye:
    def test_brut_rempli_envoie_le_brut_pas_le_nettoye(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8402
        _insert_offer(
            db_path,
            offer_id,
            description_raw="Texte brut offre 8402.",
            description="Texte nettoyé différent 8402.",
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Texte brut offre 8402." in prompt_text
        assert "Texte nettoyé différent 8402." not in prompt_text


class TestCritere3BrutSeulementEspaces:
    def test_brut_espaces_et_retours_ligne_envoie_le_nettoye(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8403
        _insert_offer(
            db_path,
            offer_id,
            description_raw="   \n\n\t  \n",
            description="Texte nettoyé offre 8403.",
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Texte nettoyé offre 8403." in prompt_text


class TestCritere4IntituleDansLePrompt:
    def test_intitule_present(self, db_path, lettre_fixture_paths, monkeypatch):
        offer_id = 8404
        _insert_offer(
            db_path,
            offer_id,
            title="Generative AI Engineer 8404",
            description_raw="Texte de l'offre 8404.",
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Generative AI Engineer 8404" in prompt_text


class TestCritere5IntituleAvantLeTexte:
    def test_intitule_precede_le_texte_de_offre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8405
        _insert_offer(
            db_path,
            offer_id,
            title="Intitulé Offre 8405",
            description_raw="Texte de l'offre 8405.",
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert prompt_text.index("Intitulé Offre 8405") < prompt_text.index(
            "Texte de l'offre 8405."
        )


class TestCritere6RefusTexteManquant:
    def test_refuse_sans_appeler_le_modele_ni_stocker_de_lettre(
        self, db_path, monkeypatch
    ):
        offer_id = 8406
        _insert_offer(db_path, offer_id, description_raw="   ", description="")
        _insert_fiche(db_path, offer_id, _points_8())

        def _forbidden(_oid):
            raise AssertionError(
                "le modèle a été appelé alors que le texte de l'offre manque"
            )

        monkeypatch.setattr(api_lettre, "run_lettre", _forbidden)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert "texte" in exc_info.value.detail.lower()
        assert _lettre_row(db_path, offer_id) is None
