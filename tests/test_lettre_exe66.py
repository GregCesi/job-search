"""Tests EXE-66 — reprise du texte de la lettre, historique des versions, régénération.

Couvre : enregistrement du texte repris (critères 1-3, 5-7), historique à 3 versions
(critère 4), régénération (critères 8-13).

Aucun test n'appelle le modèle : `query` du SDK Claude Agent est remplacé par un faux
générateur async, ou monkeypatché pour lever si on l'appelle par erreur. Aucun test ne
lit ni n'écrit sous data/ : DB, préférences de ton, tournures interdites et CV de
référence sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

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


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, description_raw) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-28')",
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


def _set_choice(db_path, offer_id, indices):
    conn = sqlite3.connect(db_path)
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, points_choisis_json, created_at) "
            "VALUES (?, 'aucune', ?, ?) "
            "ON CONFLICT(offer_id) DO UPDATE SET points_choisis_json=excluded.points_choisis_json",
            (offer_id, json.dumps(sorted(indices)), now),
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


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _generer_lettre_prete(
    db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre initiale."
):
    """Fait exister une lettre `done` pour l'offre, sans passer par la route HTTP."""
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id, _points_8())

    def behavior(prompt, options):
        return [_fake_result(result=texte)]

    monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
    asyncio.run(lettre_service.run_lettre(offer_id))


class TestCritere1TexteRepriteEtGarde:
    def test_texte_modifie_relu_tel_quel(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Mon texte à moi.")
        )
        result = api_lettre.get_lettre(offer_id)
        assert result["texte"] == "Mon texte à moi."


class TestCritere2TournureSignaleeSurMonTexte:
    def test_tournure_signalee_texte_non_corrige(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Je veux rejoindre votre équipe.")
        )
        assert result["texte"] == "Je veux rejoindre votre équipe."
        assert result["tournures_signalees"] == ["Je veux"]


class TestCritere3DepassementLongueurSignale:
    def test_420_mots_signale_avec_le_compte(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 3
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)
        texte_420 = " ".join(["mot"] * 420)

        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte=texte_420)
        )
        assert result["depasse_longueur"] is True
        assert result["nb_mots"] == 420


class TestCritere4HistoriqueTroisVersionsOrdre:
    def test_deux_modifications_rendent_trois_versions_dans_l_ordre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Version modèle.",
        )

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma première reprise.")
        )
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma deuxième reprise.")
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        assert len(versions) == 3
        assert [v["texte"] for v in versions] == [
            "Version modèle.",
            "Ma première reprise.",
            "Ma deuxième reprise.",
        ]
        assert [v["origine"] for v in versions] == ["modele", "moi", "moi"]
        for v in versions:
            assert v["created_at"]


class TestCritere5RefusTexteVide:
    def test_texte_vide_refuse_lettre_inchangee(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 5
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        with pytest.raises(HTTPException) as exc_info:
            api_lettre.put_lettre_texte(offer_id, api_lettre.LettreTexteIn(texte="   "))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail
        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Lettre initiale."
        versions = api_lettre.get_lettre_versions(offer_id)
        assert [v["texte"] for v in versions] == ["Lettre initiale."]


class TestCritere6RefusSansLettrePrete:
    def test_refuse_offre_sans_lettre(self, db_path, lettre_fixture_paths):
        offer_id = 6
        _insert_offer(db_path, offer_id)

        with pytest.raises(HTTPException) as exc_info:
            api_lettre.put_lettre_texte(
                offer_id, api_lettre.LettreTexteIn(texte="Un texte quelconque.")
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail


class TestCritere7AucunAppelModeleAEnregistrement:
    def test_save_texte_n_appelle_jamais_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 7
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        def _forbidden(*, prompt, options):
            raise AssertionError("le modèle a été appelé pour un simple enregistrement")

        monkeypatch.setattr(lettre_service, "query", _forbidden)
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Texte sans modèle.")
        )
        assert _lettre_row(db_path, offer_id)["texte"] == "Texte sans modèle."


class TestCritere8Regeneration:
    def test_regenerer_appelle_le_modele_et_rend_une_nouvelle_lettre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Ancienne lettre.",
        )

        def behavior(prompt, options):
            return [_fake_result(result="Nouvelle lettre régénérée.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))
        assert response.status_code == 202

        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Nouvelle lettre régénérée."

    def test_redemander_sans_regenerer_rend_inchange(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 80
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )

        def _forbidden(*, prompt, options):
            raise AssertionError("le modèle a été rappelé par un simple redemander")

        monkeypatch.setattr(lettre_service, "query", _forbidden)
        response = Response()
        result = asyncio.run(api_lettre.create_lettre(offer_id, response))
        assert response.status_code == 200
        assert result["texte"] == "Lettre stable."


class TestCritere9PromptRegenerationChoixCourant:
    def test_prompt_regeneration_contient_le_nouveau_choix_seulement(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 9
        points = _points_8()
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points)
        _set_choice(db_path, offer_id, [0, 1])

        def behavior_initial(prompt, options):
            return [_fake_result(result="Première lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior_initial))
        asyncio.run(lettre_service.run_lettre(offer_id))

        # Je change mon choix de points avant de régénérer (critère 9).
        api_lettre.set_lettre_points(offer_id, api_lettre.PointsChoisisIn(indices=[3]))

        captured = {}

        def behavior_regen(prompt, options):
            captured["prompt"] = prompt
            return [_fake_result(result="Lettre régénérée.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior_regen))
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))

        prompt_text = captured["prompt"]
        assert "Point 3" in prompt_text
        assert "Point 0" not in prompt_text
        assert "Point 1" not in prompt_text


class TestCritere10HistoriqueApresRegeneration:
    def test_historique_garde_la_precedente_et_ajoute_la_nouvelle_en_dernier(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Version modèle.",
        )
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma reprise.")
        )

        def behavior(prompt, options):
            return [_fake_result(result="Version régénérée.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))

        versions = api_lettre.get_lettre_versions(offer_id)
        assert [v["texte"] for v in versions] == [
            "Version modèle.",
            "Ma reprise.",
            "Version régénérée.",
        ]
        assert versions[-1]["origine"] == "modele"


class TestCritere11EchecRegenerationGardeVersionAvant:
    def test_echec_du_modele_garde_la_version_d_avant_et_signale_l_echec(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        avant = _lettre_row(db_path, offer_id)

        def behavior(prompt, options):
            raise RuntimeError("SDK indisponible")

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        apres = _lettre_row(db_path, offer_id)
        assert apres["texte"] == avant["texte"] == "Lettre stable."
        assert apres["tournures_signalees_json"] == avant["tournures_signalees_json"]
        assert apres["statut"] == "done"
        assert apres["regeneration_en_cours"] == 0
        assert apres["regeneration_error"]

    def test_timeout_garde_la_version_d_avant(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 110
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        monkeypatch.setattr(lettre_service, "TIMEOUT_S", 0.01)

        async def _slow_query(*, prompt, options):
            await asyncio.sleep(1)
            yield _fake_result(result="trop tard")

        monkeypatch.setattr(lettre_service, "query", _slow_query)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Lettre stable."
        assert row["regeneration_error"]


class TestCritere12LectureRegenerationEnCours:
    def test_relire_pendant_regeneration_rend_la_version_d_avant_et_le_signale(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        conn = _connect(db_path)
        try:
            lettre_service.mark_regenerating(conn, offer_id)
        finally:
            conn.close()

        result = api_lettre.get_lettre(offer_id)
        assert result["texte"] == "Lettre stable."
        assert result["regeneration_en_cours"] is True


class TestCritere13RefusRegenerationOffreNonRetenueOuSansLettre:
    def test_refuse_offre_non_retenue_sans_appeler_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 13
        _insert_offer(db_path, offer_id, verdict="candidaté")

        def _forbidden(*, prompt, options):
            raise AssertionError("le modèle a été appelé pour une offre non retenue")

        monkeypatch.setattr(lettre_service, "query", _forbidden)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.regenerer_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409

    def test_refuse_sans_lettre_prete_sans_appeler_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 130
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def _forbidden(*, prompt, options):
            raise AssertionError("le modèle a été appelé sans lettre prête")

        monkeypatch.setattr(lettre_service, "query", _forbidden)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.regenerer_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
