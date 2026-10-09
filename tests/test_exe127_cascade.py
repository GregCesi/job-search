"""Tests EXE-127 — retenir une offre lance la fiche, le CV puis la lettre, et
l'API dit où en est chaque pièce (TCK-281).

Aucun test n'appelle un modèle : `query` du SDK Claude Agent (fiche, CV, lettre)
et la cascade d'identification employeur (Ollama) sont toutes remplacées par des
doublures. Aucun test ne lit ni n'écrit sous data/ : DB, préférences de ton,
tournures interdites et CV de référence sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.avancement as api_avancement
import api.cv as cv_api
import api.db as api_db
import api.fiche as fiche_api
import api.lettre as lettre_api
import api.offers as api_offers
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from api.schemas import VerdictIn
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_RIEN_A_REDIRE,
    Jugement,
    ResultatBoucle,
)
from orchestrator.job_search.storage.db import init_db

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

TOURNURES_INTERDITES = "je veux\n"

POINTS_2 = [
    {"position": "Point A", "citation": "Citation A", "url": None},
    {"position": "Point B", "citation": None, "url": None},
]


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire (ou lève)."""

    async def _query(*, prompt, options):
        msgs = behavior(prompt, options)
        for m in msgs:
            yield m

    return _query


def _fiche_result(
    points, session_id="fiche-session", cost=0.1, points_pour_lettre=None
):
    """`points_pour_lettre` par défaut = tous les points rendus (EXE-132, critère 1) :
    ce double représente un modèle qui désigne tout ce qu'il rend, pour ne pas changer
    les attentes des tests EXE-127 qui ne portent pas sur la désignation elle-même."""
    if points_pour_lettre is None:
        points_pour_lettre = list(range(len(points)))
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
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


def _cv_result(session_id="cv-session", cost=0.02):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
        result=None,
        structured_output={
            "groupes": [{"label": "Langages", "items": ["Python", "SQL"]}]
        },
    )


def _resultat_lettre(texte="Voici ma lettre de motivation.") -> ResultatBoucle:
    lettre = {
        "texte": texte,
        "nb_mots": len(texte.split()),
        "tournures_signalees": [],
        "jugement": Jugement(
            rien_a_redire=True, ressenti="bien", details="d", reussites="r", verdict="v"
        ),
        "releve_redaction": {"tournures": [], "lieux": [], "affirmations": []},
        "releve_correction": None,
    }
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id="tt",
        lettres=[lettre],
        nb_tours=1,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
    )


def _erreur_result(msg="panne SDK"):
    return ResultMessage(
        subtype="error_during_execution",
        duration_ms=1,
        duration_api_ms=1,
        is_error=True,
        num_turns=1,
        session_id="err-session",
        total_cost_usd=0.0,
        result=msg,
        structured_output=None,
    )


def _fiche_ok(points=POINTS_2):
    return lambda prompt, options: [_fiche_result(points)]


def _cv_ok():
    return lambda prompt, options: [_cv_result()]


def _lettre_ok(texte="Voici ma lettre de motivation."):
    return lambda *a, **k: _resultat_lettre(texte)


def _en_erreur(msg="panne SDK"):
    return lambda prompt, options: [_erreur_result(msg)]


def _jamais_appele(nom):
    def behavior(prompt, options):
        raise AssertionError(
            f"le modèle {nom} a été rappelé alors qu'il ne devait pas l'être"
        )

    return behavior


def _lettre_jamais_appelee():
    def _fn(*a, **k):
        raise AssertionError(
            "le modèle lettre a été rappelé alors qu'il ne devait pas l'être"
        )

    return _fn


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
    tournures = tmp_path / "tournures_interdites.txt"
    tournures.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    return tournures


@pytest.fixture(autouse=True)
def _stub_cascade_employeur(monkeypatch):
    """La cascade d'identification employeur appelle Ollama (orchestrator/job_search/
    fiche/cascade.py) : hors périmètre de ce ticket, et interdit en test (« un test
    appelle un modèle »). Doublure déterministe, jamais de réseau."""

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


def _insert_offer(
    db_path,
    offer_id,
    *,
    description_raw="Texte complet de l'offre pour la lettre.",
    techs=None,
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, description_raw, extracted_facts_json) "
            "VALUES (?, 'test', ?, 'fp', 'Ingénieur H/F', 'ACME', 'Strasbourg', ?, ?)",
            (
                offer_id,
                str(offer_id),
                description_raw,
                json.dumps({"techs_required": techs or []}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _row(db_path, table, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            f"SELECT * FROM {table} WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def _fiche_row(db_path, offer_id):
    return _row(db_path, "fiches_entreprise", offer_id)


def _cv_row(db_path, offer_id):
    return _row(db_path, "cvs", offer_id)


def _lettre_row(db_path, offer_id):
    return _row(db_path, "lettres", offer_id)


async def _drain() -> None:
    """Attend que toutes les tâches de fond créées pendant le scénario (y compris
    celles qu'une tâche en cours crée à son tour, comme la lettre à la fin de la
    fiche) soient terminées."""
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _retenir(offer_id):
    asyncio.run(_scenario_retenir(offer_id))


async def _scenario_retenir(offer_id):
    await api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))
    await _drain()


class TestCritere1FicheEtCvEnCoursSansAutreAppel:
    def test_offre_jamais_traitee(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        # La fiche rend des points par défaut : elle enchaîne la lettre toute
        # seule (critère 2) — doublure nécessaire pour qu'aucun test n'appelle
        # le vrai SDK, même si ce n'est pas ce que ce critère-ci observe.
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        async def _scenario():
            await api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))
            # Synchrone : au retour du PUT verdict, les deux pièces sont déjà
            # passées en cours, sans autre appel de ma part.
            assert fiche_api.is_running(offer_id)
            assert cv_api.is_running(offer_id)
            assert _fiche_row(db_path, offer_id)["statut"] == "pending"
            assert _cv_row(db_path, offer_id)["statut"] == "pending"
            await _drain()

        asyncio.run(_scenario())
        assert _fiche_row(db_path, offer_id)["statut"] == "done"
        assert _cv_row(db_path, offer_id)["statut"] == "done"


class TestCritere2LettreEnCoursQuandFicheTermine:
    def test_lettre_se_lance_automatiquement_apres_la_fiche(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        """EXE-162, critère 3 : la désignation de points ne gate plus le
        lancement de la lettre — la fiche terminée et le texte de l'offre
        présent suffisent, même si la fiche ne désigne plus aucun point
        (`pour_lettre` vaut toujours False depuis EXE-161). Inverse l'ancienne
        attente d'EXE-161 (la lettre restait en attente)."""
        offer_id = 2
        _insert_offer(db_path, offer_id)
        appels = {"n": 0}

        def _lettre_behavior(*a, **k):
            appels["n"] += 1
            return _resultat_lettre()

        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_behavior
        )

        _retenir(offer_id)

        assert appels["n"] == 1
        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


class TestCritere3PointsChoisisParSysteme:
    def test_aucun_point_designe_par_le_systeme_depuis_exe161(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        # EXE-161, critère 2 : la fiche ne porte plus aucune désignation vraie —
        # le système ne peut plus choisir de point tant qu'elle n'en désigne pas.
        offer_id = 3
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)

        row = _lettre_row(db_path, offer_id)
        chosen = json.loads(row["points_choisis_json"])
        assert chosen == []


class TestCritere4OrigineSysteme:
    def test_api_dit_que_le_choix_vient_du_systeme(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)

        result = lettre_api.get_lettre(offer_id)
        assert result["points_choisis_origine"] == "systeme"


class TestCritere5OrigineMoi:
    def test_api_dit_que_le_choix_vient_de_moi_apres_changement(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)
        assert lettre_api.get_lettre(offer_id)["points_choisis_origine"] == "systeme"

        lettre_api.set_lettre_points(offer_id, lettre_api.PointsChoisisIn(indices=[1]))

        result = lettre_api.get_lettre(offer_id)
        assert result["points_choisis_origine"] == "moi"


class TestCritere6FicheSansPointLettreQuandMeme:
    """EXE-162, critère 3 : une fiche terminée sans aucun point ne bloque plus
    la lettre — la boucle part en générique. Inverse l'ancien comportement
    d'EXE-127 (6), où l'absence de point bloquait."""

    def test_fiche_sans_point_la_lettre_part_quand_meme(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok(points=[])))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)

        assert _fiche_row(db_path, offer_id)["statut"] == "done"
        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


class TestCritere7FicheEchoueSansLettre:
    def test_fiche_en_erreur_bloque_la_lettre(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_jamais_appelee()
        )

        _retenir(offer_id)

        assert _fiche_row(db_path, offer_id)["statut"] == "error"
        assert not lettre_api.is_running(offer_id)
        row = _lettre_row(db_path, offer_id)
        assert row is None or row["statut"] == "aucune"


class TestCritere8FicheEchoueCvTermine:
    def test_cv_termine_malgre_fiche_en_erreur(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))

        _retenir(offer_id)

        assert _fiche_row(db_path, offer_id)["statut"] == "error"
        assert _cv_row(db_path, offer_id)["statut"] == "done"


class TestCritere9CvEchoueFicheEtLettreTerminent:
    def test_fiche_termine_malgre_cv_en_erreur(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        # EXE-162, critère 3 : la fiche terminée suffit à lancer la lettre, que
        # la fiche désigne ou non des points — le CV en erreur ne l'affecte pas.
        offer_id = 9
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)

        assert _cv_row(db_path, offer_id)["statut"] == "error"
        assert _fiche_row(db_path, offer_id)["statut"] == "done"
        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


class TestCritere10TexteOffreManquantPasDeLettre:
    def test_texte_manquant_bloque_la_lettre(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _insert_offer(db_path, offer_id, description_raw="   ")
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_jamais_appelee()
        )

        _retenir(offer_id)

        assert _fiche_row(db_path, offer_id)["statut"] == "done"
        assert not lettre_api.is_running(offer_id)
        row = _lettre_row(db_path, offer_id)
        assert row is None or row["statut"] == "aucune"


class TestCritere11PieceDejaTermineeNonRelancee:
    def test_retrait_puis_retenue_a_nouveau_ne_relance_rien(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        _retenir(offer_id)
        fiche_before = dict(_fiche_row(db_path, offer_id))
        cv_before = dict(_cv_row(db_path, offer_id))
        lettre_before = dict(_lettre_row(db_path, offer_id))

        asyncio.run(api_offers.upsert_verdict(offer_id, VerdictIn(status="rejeté")))

        monkeypatch.setattr(
            fiche_service, "query", _make_query(_jamais_appele("fiche"))
        )
        monkeypatch.setattr(cv_service, "query", _make_query(_jamais_appele("cv")))
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_jamais_appelee()
        )

        _retenir(offer_id)

        assert dict(_fiche_row(db_path, offer_id)) == fiche_before
        assert dict(_cv_row(db_path, offer_id)) == cv_before
        assert dict(_lettre_row(db_path, offer_id)) == lettre_before


class TestCritere12DeuxAppelsConsecutifs:
    def test_chaque_piece_generee_une_seule_fois(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        compte = {"fiche": 0, "cv": 0}

        def _fiche_behavior(prompt, options):
            compte["fiche"] += 1
            return [_fiche_result(POINTS_2)]

        def _cv_behavior(prompt, options):
            compte["cv"] += 1
            return [_cv_result()]

        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_behavior))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_behavior))
        # La fiche rend des points par défaut : elle enchaîne la lettre toute
        # seule — doublure nécessaire même si ce n'est pas ce que ce critère
        # observe (aucun test n'appelle le vrai SDK).
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        async def _scenario():
            await api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))
            # Second appel « de suite », avant que les tâches de fond du premier
            # n'aient fini — la garde `_running` doit l'empêcher de relancer.
            await api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))
            await _drain()

        asyncio.run(_scenario())
        assert compte["fiche"] == 1
        assert compte["cv"] == 1


class TestCritere13VerdictAutreQueRetenuNeLanceRien:
    def test_rejete_ne_lance_aucune_piece(self, db_path):
        offer_id = 13
        _insert_offer(db_path, offer_id)

        asyncio.run(api_offers.upsert_verdict(offer_id, VerdictIn(status="rejeté")))

        assert _fiche_row(db_path, offer_id) is None
        assert _cv_row(db_path, offer_id) is None
        assert not fiche_api.is_running(offer_id)
        assert not cv_api.is_running(offer_id)


class TestCritere14AvancementQuatreEtats:
    def test_rend_un_etat_parmi_quatre_pour_chaque_piece(
        self, db_path, tmp_path, monkeypatch
    ):
        import orchestrator.job_search.mail.candidature as candidature_module

        offer_id = 14
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(cv_service, "query", _make_query(_en_erreur()))
        asyncio.run(api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu")))
        asyncio.run(_drain())

        gabarit = tmp_path / "mail_candidature.md"
        gabarit.write_text(
            "Objet : Candidature {intitule}\n\nBonjour.\n", encoding="utf-8"
        )
        monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", gabarit)

        result = api_avancement.get_avancement(offer_id)
        for piece in ("fiche", "cv", "lettre", "mail"):
            assert piece in result
            assert result[piece]["etat"] in {
                "en_attente",
                "en_cours",
                "terminee",
                "en_erreur",
            }
        assert result["mail"]["etat"] == "terminee"

    def test_refuse_si_offre_non_retenue(self, db_path):
        offer_id = 140
        _insert_offer(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_avancement.get_avancement(offer_id)
        assert exc_info.value.status_code == 409


class TestCritere15RaisonExpliquant:
    def test_en_attente_et_en_erreur_portent_une_raison(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service, "query", _make_query(_en_erreur("fiche en panne"))
        )
        monkeypatch.setattr(
            cv_service, "query", _make_query(_en_erreur("plus de crédit"))
        )

        _retenir(offer_id)

        result = api_avancement.get_avancement(offer_id)
        assert result["cv"]["etat"] == "en_erreur"
        assert result["cv"]["raison"] is not None
        assert "plus de crédit" in result["cv"]["raison"]

        # La lettre : la fiche a échoué, donc jamais lancée — en attente, avec
        # la raison qui le dit.
        assert result["lettre"]["etat"] == "en_attente"
        assert result["lettre"]["raison"]
        assert "fiche" in result["lettre"]["raison"].lower()


class TestCritere16MailTermineOuEnErreur:
    def test_mail_termine_quand_le_gabarit_se_lit(self, db_path, tmp_path, monkeypatch):
        import orchestrator.job_search.mail.candidature as candidature_module

        offer_id = 16
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(cv_service, "query", _make_query(_en_erreur()))
        asyncio.run(api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu")))
        asyncio.run(_drain())
        gabarit = tmp_path / "mail_candidature.md"
        gabarit.write_text(
            "Objet : Candidature {intitule}\n\nBonjour.\n", encoding="utf-8"
        )
        monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", gabarit)

        result = api_avancement.get_avancement(offer_id)
        assert result["mail"] == {"etat": "terminee", "raison": None}

    def test_mail_en_erreur_sans_gabarit(self, db_path, tmp_path, monkeypatch):
        import orchestrator.job_search.mail.candidature as candidature_module

        offer_id = 160
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_en_erreur()))
        monkeypatch.setattr(cv_service, "query", _make_query(_en_erreur()))
        asyncio.run(api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu")))
        asyncio.run(_drain())
        monkeypatch.setattr(
            candidature_module, "MAIL_CANDIDATURE_PATH", tmp_path / "absent.md"
        )

        result = api_avancement.get_avancement(offer_id)
        assert result["mail"]["etat"] == "en_erreur"
        assert result["mail"]["raison"]


class TestCritere17ListeOffresActivesOuChangees:
    def test_offre_en_cours_puis_disparait_une_fois_signalee(
        self, db_path, cv_fixture_paths, lettre_fixture_paths, monkeypatch, tmp_path
    ):
        import orchestrator.job_search.mail.candidature as candidature_module

        monkeypatch.setattr(
            candidature_module, "MAIL_CANDIDATURE_PATH", tmp_path / "absent.md"
        )
        offer_id = 17
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(fiche_service, "query", _make_query(_fiche_ok()))
        monkeypatch.setattr(cv_service, "query", _make_query(_cv_ok()))
        # La fiche rend des points par défaut : elle enchaîne la lettre toute
        # seule — doublure nécessaire même si ce n'est pas ce que ce critère
        # observe (aucun test n'appelle le vrai SDK).
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _lettre_ok()
        )

        async def _scenario():
            await api_offers.upsert_verdict(offer_id, VerdictIn(status="retenu"))
            # En cours : visible sans avoir encore changé d'état.
            actives = api_avancement.list_avancement()
            assert any(o["id"] == offer_id for o in actives)
            trouve = next(o for o in actives if o["id"] == offer_id)
            assert trouve["title"] == "Ingénieur H/F"
            assert "avancement" in trouve
            await _drain()

        asyncio.run(_scenario())

        # Juste après la fin : signalée une fois (« vient de changer d'état »).
        actives = api_avancement.list_avancement()
        assert any(o["id"] == offer_id for o in actives)

        # Rien de nouveau depuis : plus signalée, plus en cours.
        actives = api_avancement.list_avancement()
        assert not any(o["id"] == offer_id for o in actives)
