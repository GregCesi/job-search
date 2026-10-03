"""Tests EXE-101 — statut de pièce (CV / lettre) d'une offre retenue : À faire,
En cours, Prête — « Prête » ne vient que de ma marque.

Aucun test n'appelle un modèle : les générations CV/lettre sont simulées par
insertion SQL directe des états (`statut`, `marque_pret_at`), ou par les
fonctions de service réelles avec `query` du SDK Claude Agent monkeypatché.
Aucun test ne lit ni n'écrit sous data/ : DB sous `tmp_path` (même isolation
que test_cv_corrections_service.py / test_lettre_exe66.py).
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException, Response

import api.cv as api_cv
import api.db as api_db
import api.lettre as api_lettre
import api.pieces as api_pieces
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, verdict, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_cv(db_path, offer_id, statut, marque_pret_at=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, marque_pret_at, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(
    db_path, offer_id, statut, marque_pret_at=None, regeneration_en_cours=0
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres "
            "(offer_id, statut, marque_pret_at, regeneration_en_cours, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (offer_id, statut, marque_pret_at, regeneration_en_cours, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, points, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, created_at) VALUES (?, ?, 'Présentation', ?, ?)",
            (offer_id, statut, json.dumps(points, ensure_ascii=False), _now()),
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


def _fake_result(result=None, structured_output=None):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id="fake-session",
        total_cost_usd=0.01,
        result=result,
        structured_output=structured_output,
    )


def _make_query(behavior):
    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


REF_CV_HTML = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Ancien titre</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Strasbourg, France</b></div>
    </div>
    <h2>Compétences</h2>
  <div class="grp">
    <div class="grp-label">Langages</div>
    <div class="grp-list">Python · SQL</div>
  </div>
  <div class="grp-notions">Notions en : GraphQL</div>
  <h2>Formation</h2>
    <div class="edu">Diplôme fictif</div>
  </div>
</body></html>
"""

PROFILE_YAML = """
profile_id: test
role_ceiling: ic
skills:
  python: {level: 6, desire: 8}
zones:
  strasbourg_area:
    insee: []
    dept: []
    keywords: ["strasbourg"]
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: [remote]
  contract_types: [cdi]
"""

PREFERENCES_TON = "# Préférences de ton\n- Direct, sans emphase\n"
TOURNURES_INTERDITES = "je veux\n"


@pytest.fixture
def cv_fixture_paths(tmp_path, monkeypatch):
    ref = tmp_path / "cv_reference.html"
    ref.write_text(REF_CV_HTML, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    return ref, profile


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


def _run_cv(monkeypatch, offer_id):
    monkeypatch.setattr(
        cv_service,
        "query",
        _make_query(lambda p, o: [_fake_result(structured_output={"groupes": []})]),
    )
    asyncio.run(cv_service.run_cv(offer_id))


def _generer_lettre_prete(db_path, offer_id, monkeypatch, texte="Lettre initiale."):
    _insert_fiche(db_path, offer_id, _points_8())
    monkeypatch.setattr(
        lettre_service, "query", _make_query(lambda p, o: [_fake_result(result=texte)])
    )
    asyncio.run(lettre_service.run_lettre(offer_id))


class TestCritere1CvJamaisGenereAFaire:
    def test_cv_sans_generation_est_a_faire(self, db_path):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        result = api_pieces.get_pieces(offer_id)
        assert result["cv"]["statut"] == "a_faire"


class TestCritere2LettreJamaisGenereeAFaire:
    def test_lettre_sans_generation_est_a_faire(self, db_path):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        result = api_pieces.get_pieces(offer_id)
        assert result["lettre"]["statut"] == "a_faire"

    def test_lettre_avec_seulement_un_choix_de_points_est_a_faire(self, db_path):
        offer_id = 20
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="aucune")
        result = api_pieces.get_pieces(offer_id)
        assert result["lettre"]["statut"] == "a_faire"


class TestCritere3CvLanceEstEnCours:
    @pytest.mark.parametrize("statut", ["pending", "done", "error"])
    def test_cv_lance_est_en_cours(self, db_path, statut):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut=statut)
        result = api_pieces.get_pieces(offer_id)
        assert result["cv"]["statut"] == "en_cours"


class TestCritere4LettreLanceeEstEnCours:
    @pytest.mark.parametrize("statut", ["pending", "done", "error"])
    def test_lettre_lancee_est_en_cours(self, db_path, statut):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut=statut)
        result = api_pieces.get_pieces(offer_id)
        assert result["lettre"]["statut"] == "en_cours"


class TestCritere5MarqueCvPret:
    def test_marquer_pret_un_cv_termine(self, db_path):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done")
        result = api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert result["statut"] == "prete"
        assert result["marque_pret_le"]


class TestCritere6MarqueLettrePrete:
    def test_marquer_prete_une_lettre_terminee(self, db_path):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="done")
        result = api_pieces.set_lettre_pret(
            offer_id, api_pieces.MarquePretIn(pret=True)
        )
        assert result["statut"] == "prete"
        assert result["marque_pret_le"]


class TestCritere7RefusMarquePieceNonTerminee:
    def test_refuse_cv_jamais_genere(self, db_path):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail

    @pytest.mark.parametrize("statut", ["pending", "error"])
    def test_refuse_cv_en_cours_ou_en_erreur(self, db_path, statut):
        offer_id = 70
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut=statut)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409
        row = (
            _connect(db_path)
            .execute("SELECT marque_pret_at FROM cvs WHERE offer_id = ?", (offer_id,))
            .fetchone()
        )
        assert row["marque_pret_at"] is None

    def test_refuse_lettre_jamais_generee(self, db_path):
        offer_id = 71
        _insert_offer(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409

    @pytest.mark.parametrize("statut", ["aucune", "pending", "error"])
    def test_refuse_lettre_en_cours_ou_en_erreur(self, db_path, statut):
        offer_id = 72
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut=statut)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409

    def test_refuse_lettre_en_cours_de_regeneration(self, db_path):
        offer_id = 73
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="done", regeneration_en_cours=1)
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409


class TestCritere8RetireMarque:
    def test_demarquer_cv_pret_redevient_en_cours(self, db_path):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        result = api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=False))
        assert result["statut"] == "en_cours"

    def test_demarquer_lettre_prete_redevient_en_cours(self, db_path):
        offer_id = 80
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="done", marque_pret_at=_now())
        result = api_pieces.set_lettre_pret(
            offer_id, api_pieces.MarquePretIn(pret=False)
        )
        assert result["statut"] == "en_cours"


class TestCritere9CorrectionCvRedevientEnCours:
    def test_ajout_competence_efface_la_marque(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "prete"

        api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(
                action="ajout",
                competence="Kubernetes",
                maitrisee=True,
                groupe="Langages",
            ),
        )
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"

    def test_retrait_competence_efface_la_marque(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 90
        _insert_offer(db_path, offer_id)
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))

        api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(action="retrait", competence="Python"),
        )
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"


class TestCritere10TexteModifieRedevientEnCours:
    def test_enregistrer_texte_modifie_efface_la_marque(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _insert_offer(db_path, offer_id)
        _generer_lettre_prete(db_path, offer_id, monkeypatch)
        api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert api_pieces.get_pieces(offer_id)["lettre"]["statut"] == "prete"

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Mon texte modifié.")
        )
        assert api_pieces.get_pieces(offer_id)["lettre"]["statut"] == "en_cours"


class TestCritere11RegenerationRedevientEnCoursDesLeLancement:
    def test_regenerer_efface_la_marque_des_le_lancement(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _insert_offer(db_path, offer_id)
        _generer_lettre_prete(db_path, offer_id, monkeypatch)
        api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))

        monkeypatch.setattr(
            lettre_service,
            "query",
            _make_query(lambda p, o: [_fake_result(result="Nouvelle lettre.")]),
        )
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))

        assert api_pieces.get_pieces(offer_id)["lettre"]["statut"] == "en_cours"


class TestCritere12ChoixPointsSansRegenererResteSansEffet:
    def test_changer_choix_points_sans_regenerer_garde_prete(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        _generer_lettre_prete(db_path, offer_id, monkeypatch)
        api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))

        api_lettre.set_lettre_points(offer_id, api_lettre.PointsChoisisIn(indices=[3]))

        assert api_pieces.get_pieces(offer_id)["lettre"]["statut"] == "prete"


class TestCritere13LectureDesDeuxStatuts:
    def test_lecture_rend_cv_et_lettre(self, db_path):
        offer_id = 13
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="pending")

        result = api_pieces.get_pieces(offer_id)
        assert result["cv"]["statut"] == "prete"
        assert result["lettre"]["statut"] == "en_cours"


class TestCritere14PreteALEnvoiSiLesDeuxPretes:
    def test_les_deux_pretes_rend_prete_a_l_envoi(self, db_path):
        offer_id = 14
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="done", marque_pret_at=_now())

        assert api_pieces.get_pieces(offer_id)["prete_a_l_envoi"] is True


class TestCritere15PasPreteALEnvoiSiUneSeule:
    def test_une_seule_prete_ne_rend_pas_prete_a_l_envoi(self, db_path):
        offer_id = 15
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, statut="done", marque_pret_at=_now())
        _insert_lettre(db_path, offer_id, statut="done")

        assert api_pieces.get_pieces(offer_id)["prete_a_l_envoi"] is False


class TestCritere16RefusOffreNonRetenue:
    def test_refuse_lecture_offre_non_retenue(self, db_path):
        offer_id = 16
        _insert_offer(db_path, offer_id, verdict="candidaté")
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.get_pieces(offer_id)
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail

    def test_refuse_marque_cv_offre_non_retenue(self, db_path):
        offer_id = 160
        _insert_offer(db_path, offer_id, verdict=None)
        _insert_cv(db_path, offer_id, statut="done")
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409

    def test_refuse_marque_lettre_offre_non_retenue(self, db_path):
        offer_id = 161
        _insert_offer(db_path, offer_id, verdict="rejeté")
        _insert_lettre(db_path, offer_id, statut="done")
        with pytest.raises(HTTPException) as exc_info:
            api_pieces.set_lettre_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert exc_info.value.status_code == 409
