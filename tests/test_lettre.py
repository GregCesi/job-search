"""Tests EXE-65 — lettre de motivation.

Couvre : choix des points (critères 5-8), guards de génération (1-4, 8), contenu du
prompt envoyé (9-13), préférences de ton absentes (14), tournures interdites et
longueur (15-20), modèle et outils (21-22), échec/timeout (23).

Aucun test n'appelle le modèle : `query` du SDK Claude Agent est remplacé par un faux
générateur async. Aucun test ne lit ni n'écrit sous data/ : DB, préférences de ton,
tournures interdites et CV de référence sont des fichiers tmp_path.
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
from orchestrator.job_search.lettre.redaction import (
    count_words,
    detect_tournures,
    exceeds_length,
    point_text,
    resolve_chosen_indices,
    strip_html,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
PREFERENCES_TON = (
    "# Préférences de ton\n"
    "Sources : notes perso\n"
    "- Direct, sans emphase\n"
    "- Pas de superlatifs\n"
    "- Phrases courtes\n"
    "- Aucune formule toute faite\n"
    "- Ton posé\n"
    "- Pas d'anglicisme inutile\n"
    "- Sobriété\n"
)
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
    cv_ref.write_text(CV_HTML, encoding="utf-8")
    monkeypatch.setattr(lettre_service, "LETTRE_PREFERENCES_PATH", prefs)
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    monkeypatch.setattr(lettre_service, "CV_REFERENCE_PATH", cv_ref)
    return prefs, tournures, cv_ref


def _insert_offer(
    db_path, offer_id, verdict="retenu", description_raw="Texte de l'offre X"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, description_raw) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', ?)",
            (offer_id, str(offer_id), description_raw),
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


def _insert_fiche(
    db_path, offer_id, points, statut="done", presentation="Présentation entreprise X"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, ?, ?, ?, '2026-09-28')",
            (offer_id, statut, presentation, json.dumps(points, ensure_ascii=False)),
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
            "VALUES (?, 'aucune', ?, ?)",
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


def _fiche_points(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT points_json FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        return json.loads(row["points_json"])
    finally:
        conn.close()


class TestCritere1GenerationEtConservation:
    def test_offre_retenue_fiche_terminee_genere_et_garde(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Voici ma lettre de motivation.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["texte"] == "Voici ma lettre de motivation."


class TestCritere2Idempotence:
    def test_redemande_rend_la_meme_lettre_sans_rappeler_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        call_count = {"n": 0}

        def behavior(prompt, options):
            call_count["n"] += 1
            return [_fake_result(result="Lettre générée une fois.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))
        assert call_count["n"] == 1

        def _never_called(_oid):
            raise AssertionError("le modèle a été rappelé pour une lettre déjà générée")

        monkeypatch.setattr(api_lettre, "run_lettre", _never_called)
        response = Response()
        result = asyncio.run(api_lettre.create_lettre(offer_id, response))
        assert response.status_code == 200
        assert result["texte"] == "Lettre générée une fois."
        assert call_count["n"] == 1


class TestCritere3RefusOffreNonRetenue:
    def test_refuse_et_ne_stocke_rien(self, db_path, lettre_fixture_paths):
        offer_id = 3
        _insert_offer(db_path, offer_id, verdict="candidaté")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert _lettre_row(db_path, offer_id) is None

    def test_refuse_quand_aucun_verdict(self, db_path, lettre_fixture_paths):
        offer_id = 30
        _insert_offer(db_path, offer_id, verdict=None)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert _lettre_row(db_path, offer_id) is None


class TestCritere4RefusSansFicheTerminee:
    def test_refuse_avec_message_nommant_la_fiche_manquante(
        self, db_path, lettre_fixture_paths
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        # Aucune fiche du tout.

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert "fiche" in exc_info.value.detail.lower()
        assert _lettre_row(db_path, offer_id) is None

    def test_refuse_quand_fiche_pending(self, db_path, lettre_fixture_paths):
        offer_id = 40
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, [], statut="pending")

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert _lettre_row(db_path, offer_id) is None


class TestCritere5PointsAvecTasParDefaut:
    def test_huit_points_deux_choisis_par_defaut(self, db_path):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        result = api_lettre.get_lettre_points(offer_id)

        assert len(result) == 8
        for i, p in enumerate(result):
            assert p["tas"] == _points_8()[i]["tas"]
            assert p["texte"] == point_text(_points_8()[i])
        choisis = [i for i, p in enumerate(result) if p["choisi"]]
        assert choisis == [0, 1]


class TestCritere6ChoixExplicite:
    def test_retrait_et_ajout_persistent_exactement(self, db_path):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        body = api_lettre.PointsChoisisIn(indices=[1, 2])
        api_lettre.set_lettre_points(offer_id, body)

        result = api_lettre.get_lettre_points(offer_id)
        choisis = [i for i, p in enumerate(result) if p["choisi"]]
        assert choisis == [1, 2]


class TestCritere7TasFicheInchangeApresChoix:
    def test_tas_fiche_identiques_apres_changement_de_choix(self, db_path):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        points_avant = _points_8()
        _insert_fiche(db_path, offer_id, points_avant)

        api_lettre.set_lettre_points(
            offer_id, api_lettre.PointsChoisisIn(indices=[1, 2])
        )

        points_apres = _fiche_points(db_path, offer_id)
        assert [p["tas"] for p in points_apres] == [p["tas"] for p in points_avant]
        assert points_apres == points_avant


class TestCritere8RefusAucunPointChoisi:
    def test_refuse_quand_tout_demarque_et_ne_rappelle_pas_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        api_lettre.set_lettre_points(offer_id, api_lettre.PointsChoisisIn(indices=[]))

        def _forbidden(_oid):
            raise AssertionError(
                "le modèle a été appelé alors qu'aucun point n'est choisi"
            )

        monkeypatch.setattr(api_lettre, "run_lettre", _forbidden)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert "point" in exc_info.value.detail.lower()
        row = _lettre_row(db_path, offer_id)
        assert row["statut"] != "done"
        assert row["texte"] is None


class TestCritere9TextePointsChoisisSeulement:
    def test_prompt_contient_seulement_les_points_choisis(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        points = _points_8()
        _insert_fiche(db_path, offer_id, points)
        _set_choice(db_path, offer_id, [0, 3])

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        prompt_text = row["prompt_text"]
        assert point_text(points[0]) in prompt_text
        assert point_text(points[3]) in prompt_text
        for i in (1, 2, 4, 5, 6, 7):
            assert point_text(points[i]) not in prompt_text


class TestCritere10PreferencesTonEntierementIncluses:
    def test_chaque_ligne_des_preferences_est_dans_le_prompt(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        for line in PREFERENCES_TON.splitlines():
            if line.strip():
                assert line.strip() in prompt_text


class TestCritere11TexteOffreInclus:
    def test_description_raw_dans_le_prompt(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _insert_offer(
            db_path, offer_id, description_raw="Description unique de l'offre 11."
        )
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Description unique de l'offre 11." in prompt_text


class TestCritere12PresentationFicheIncluse:
    def test_presentation_dans_le_prompt(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        _insert_fiche(
            db_path, offer_id, _points_8(), presentation="Présentation unique 12."
        )

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Présentation unique 12." in prompt_text


class TestCritere13CvReferenceSansHtml:
    def test_cv_reference_present_sans_balise(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 13
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
        assert "Contenu CV de test" in prompt_text
        assert "<" not in prompt_text
        assert ">" not in prompt_text


class TestCritere14PreferencesTonAbsentesRefusGeneration:
    def test_fichier_absent_refuse_et_nomme_le_fichier(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 14
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        prefs_path, _tournures, _cv = lettre_fixture_paths
        prefs_path.unlink()

        def _forbidden(*, prompt, options):
            raise AssertionError("le modèle a été appelé sans préférences de ton")

        monkeypatch.setattr(lettre_service, "query", _forbidden)
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["texte"] is None
        assert str(prefs_path) in row["error_message"]


class TestCritere15TournureJeVeuxSignaleeNonCorrigee:
    def test_texte_garde_tel_quel_et_tournure_citee(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Je veux rejoindre votre équipe.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Je veux rejoindre votre équipe."
        signalees = json.loads(row["tournures_signalees_json"])
        assert signalees == ["Je veux"]


class TestCritere16DeuxTournuresCasseDifferente:
    def test_les_deux_tournures_sont_signalees(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 16
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [
                _fake_result(result="CORDIALEMENT, et N'Hésitez Pas à me recontacter.")
            ]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        signalees = json.loads(
            _lettre_row(db_path, offer_id)["tournures_signalees_json"]
        )
        assert "CORDIALEMENT" in signalees
        assert "N'Hésitez Pas" in signalees


class TestCritere17AucuneTournureSignalee:
    def test_rien_signale_quand_absente(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 17
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            return [_fake_result(result="Une lettre propre, sans tournure à éviter.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        signalees = json.loads(
            _lettre_row(db_path, offer_id)["tournures_signalees_json"]
        )
        assert signalees == []


class TestCritere18DepasseLongueur:
    def test_420_mots_signale_le_depassement(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 18
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        texte_420_mots = " ".join(["mot"] * 420)

        def behavior(prompt, options):
            return [_fake_result(result=texte_420_mots)]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["nb_mots"] == 420
        assert bool(row["depasse_longueur"]) is True


class TestCritere19SousLaLimite:
    def test_380_mots_ne_signale_rien(self, db_path, lettre_fixture_paths, monkeypatch):
        offer_id = 19
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        texte_380_mots = " ".join(["mot"] * 380)

        def behavior(prompt, options):
            return [_fake_result(result=texte_380_mots)]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["nb_mots"] == 380
        assert bool(row["depasse_longueur"]) is False


class TestCritere20TournureAjouteeSansToucherCode:
    def test_nouvelle_ligne_du_fichier_est_prise_en_compte(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 20
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        _prefs, tournures_path, _cv = lettre_fixture_paths
        tournures_path.write_text(
            TOURNURES_INTERDITES + "pour votre bienveillante attention\n",
            encoding="utf-8",
        )

        def behavior(prompt, options):
            return [_fake_result(result="Merci pour votre bienveillante attention.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        signalees = json.loads(
            _lettre_row(db_path, offer_id)["tournures_signalees_json"]
        )
        assert "pour votre bienveillante attention" in signalees


class TestCritere21ModeleFixeEnregistre:
    def test_modele_passe_et_enregistre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 21
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        captured = {}

        def behavior(prompt, options):
            captured["model"] = options.model
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        assert captured["model"] == lettre_service.MODELE
        assert _lettre_row(db_path, offer_id)["modele"] == lettre_service.MODELE


class TestCritere22AucunOutil:
    def test_aucun_outil_disponible(self, db_path, lettre_fixture_paths, monkeypatch):
        offer_id = 22
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        captured = {}

        def behavior(prompt, options):
            captured["tools"] = options.tools
            captured["allowed_tools"] = options.allowed_tools
            captured["disallowed_tools"] = options.disallowed_tools
            return [_fake_result(result="Lettre.")]

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        assert captured["tools"] == []
        assert captured["allowed_tools"] == []
        for forbidden in (
            "WebSearch",
            "WebFetch",
            "Bash",
            "Write",
            "Edit",
            "NotebookEdit",
        ):
            assert forbidden in captured["disallowed_tools"]


class TestCritere23EchecEtTimeout:
    def test_echec_du_modele_rien_stocke_signale(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 23
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def behavior(prompt, options):
            raise RuntimeError("SDK indisponible")

        monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["texte"] is None
        assert row["error_message"]

    def test_timeout_rien_stocke_signale(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 230
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())
        monkeypatch.setattr(lettre_service, "TIMEOUT_S", 0.01)

        async def _slow_query(*, prompt, options):
            await asyncio.sleep(1)
            yield _fake_result(result="trop tard")

        monkeypatch.setattr(lettre_service, "query", _slow_query)
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["texte"] is None
        assert row["error_message"]


class TestReglesTransversales:
    """Comportements interdits par le ticket, vérifiés indépendamment des critères
    numérotés : le choix des points ne touche jamais la fiche, et le module de calcul
    reste pur (utile en isolation par les tests unitaires ci-dessous)."""

    def test_resolve_chosen_indices_defaut_tas_lettre(self):
        points = _points_8()
        assert resolve_chosen_indices(points, None) == [0, 1]

    def test_resolve_chosen_indices_choix_explicite_vide(self):
        points = _points_8()
        assert resolve_chosen_indices(points, json.dumps([])) == []

    def test_detect_tournures_insensible_a_la_casse(self):
        assert detect_tournures("JE VEUX partir", ["je veux"]) == ["JE VEUX"]

    def test_detect_tournures_absente(self):
        assert detect_tournures("Texte neutre", ["je veux"]) == []

    def test_count_words_et_exceeds_length(self):
        assert count_words("un deux trois") == 3
        assert exceeds_length(401) is True
        assert exceeds_length(400) is False

    def test_strip_html_retire_les_balises(self):
        assert strip_html("<p>Bonjour <b>Monde</b></p>") == "Bonjour Monde"
