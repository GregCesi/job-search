"""Tests EXE-116 — une offre que le tri range hors-périmètre pour la seule
cause « sans techno » attend une seconde passe du modèle de précision, en
dernier dans la file (après parfait, rêve, non lues — architecture.md,
exception TCK-273, 3e cas).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un
double contrôlable par offre et par rôle de modèle (`cascade`, repris de
test_exe100_gemma_lots.py). Aucun test ne lit ni n'écrit sous data/.
"""

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import api.db as api_db
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import ALIAS_PATH
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.scoring.categorize import Category
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    TechRequirement,
)
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.offers import save_offer

REPO = Path(__file__).resolve().parent.parent

TRI_MODEL = "llama3-test"
PRECISION_MODEL = "gemma-test"

# Aucune techno exigée → cause hors-périmètre unique : no_tech.
FACTS_NO_TECH = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[],
    domain="ai_engineering",
    role_level="ic",
)

# Désirable (ai_engineering) ET atteignable → parfait (déclenche la seconde passe).
FACTS_PARFAIT = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="git", importance="required"),
    ],
    domain="ai_engineering",
    role_level="ic",
)

# Désirable mais pas atteignable → rêve (déclenche la seconde passe).
FACTS_REVE = ExtractedFacts(
    seniority_required="senior",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="rust", importance="core"),
    ],
    domain="ai_engineering",
    role_level="ic",
)

# Atteignable, peu désirable → atteignable (jamais de seconde passe).
FACTS_ATTEIGNABLE = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="fastapi", importance="required"),
    ],
    domain="backend",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def profil(tmp_path):
    path = tmp_path / "profil.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", path)
    return path


@pytest.fixture
def loaded_profile(profil):
    profile, _ = load_profile(profil)
    return profile


@pytest.fixture
def alias_table():
    return load_alias_table(ALIAS_PATH)


@pytest.fixture
def cascade(monkeypatch):
    """Double de `ingestion.extract_facts`, contrôlable par offre et par rôle
    de modèle (tri/précision) : `state["tri"][source_id]` et
    `state["precision"][source_id]` valent "ok" (→ `state["*_facts"]`),
    "illisible" (→ None, sans lever) ou "no_response" (→ lève
    `extractor.NoResponseFromModel`). Par défaut (offre absente des deux
    dicts) : "ok"."""
    calls: list[tuple[str, str]] = []
    state = {
        "tri": {},
        "precision": {},
        "tri_facts": FACTS_ATTEIGNABLE,
        "precision_facts": FACTS_ATTEIGNABLE,
    }

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        is_tri = model == TRI_MODEL
        plan = state["tri"] if is_tri else state["precision"]
        outcome = plan.get(offer.source_id, "ok")
        if outcome == "no_response":
            raise extractor.NoResponseFromModel("pas de réponse (test)")
        if outcome == "illisible":
            return None
        return state["tri_facts"] if is_tri else state["precision_facts"]

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    return calls, state


def _offer(n: int, **overrides) -> JobOffer:
    base = dict(
        source="france_travail",
        source_id=f"FT-{n}",
        fingerprint=f"fp-{n}",
        title=f"Offre {n}",
        # EXE-115 : ≥ 50 caractères, sous ce seuil l'offre devient « texte manquant ».
        description="Une offre à pourvoir, décrite ici pour les besoins du test.",
        company="Acme",
        location="Strasbourg",
        remote=False,
        contract_type="CDI",
        url=f"https://example.test/{n}",
        fetched_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return JobOffer(**base)


def _row(db_path, offer_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()
    conn.close()
    return row


def _get_id(db_path, source_id: str) -> int:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM offers WHERE source_id = ?", (source_id,)
    ).fetchone()
    conn.close()
    return row[0]


def _run_main(monkeypatch, tmp_path, profil_path, offers: list[JobOffer]) -> None:
    import orchestrator.job_search.sources.france_travail as ft

    class _Source:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return offers

    monkeypatch.setattr(ft, "FranceTravailSource", _Source)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--profile",
            str(profil_path),
            "--no-remotive",
            "--no-indeed",
            "--no-eures",
        ],
    )
    run.main()


# ---------------------------------------------------------------------------
# Critère 1 — le tri range une offre sans techno : elle garde ce verdict et
# passe en attente de seconde passe
# ---------------------------------------------------------------------------


def test_critere1_tri_sans_techno_garde_le_verdict_et_attend_la_seconde_passe(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_facts"] = FACTS_NO_TECH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    assert tri.needs_second_pass is True
    assert tri.second_pass_reason == "no_tech"
    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()
    assert row["extraction_status"] == "second_pass_pending"
    assert row["hors_perimetre_reason"] == "no_tech"
    assert row["category"] is None
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Critère 2 — ordre de la file : parfait, rêve, non lues, sans techno ; aucune
# offre sans techno relue tant qu'il reste une offre des trois premiers
# groupes
# ---------------------------------------------------------------------------


def test_critere2_ordre_parfait_reve_non_lues_puis_sans_techno(
    db_path, profil, cascade, monkeypatch, tmp_path
):
    calls, state = cascade
    offer_illisible = _offer(1)
    offer_reve = _offer(2)
    offer_parfait = _offer(3)
    offer_sans_techno = _offer(4)

    state["tri"][offer_illisible.source_id] = "illisible"
    state["precision"][offer_illisible.source_id] = "ok"

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        is_tri = model == TRI_MODEL
        if offer.source_id == offer_illisible.source_id:
            if is_tri:
                return None
            return FACTS_ATTEIGNABLE
        if offer.source_id == offer_reve.source_id:
            return FACTS_REVE
        if offer.source_id == offer_parfait.source_id:
            return FACTS_PARFAIT
        # offer_sans_techno : le tri la range sans techno, la précision lui
        # trouve des technos.
        return FACTS_NO_TECH if is_tri else FACTS_ATTEIGNABLE

    monkeypatch.setattr(ingestion, "extract_facts", _extract)

    # Fetch volontairement dans un ordre différent de l'ordre attendu en
    # seconde passe, pour prouver que l'ordre vient de la catégorie/cause, pas
    # du fetch.
    offers = [offer_sans_techno, offer_illisible, offer_reve, offer_parfait]
    _run_main(monkeypatch, tmp_path, profil, offers)

    precision_order = [sid for m, sid in calls if m == PRECISION_MODEL]
    assert precision_order == [
        offer_parfait.source_id,
        offer_reve.source_id,
        offer_illisible.source_id,
        offer_sans_techno.source_id,
    ]


# ---------------------------------------------------------------------------
# Critère 3 — une offre sans techno relue, la précision lui trouve des
# technos : faits, catégorie et causes recalculés, version de la précision,
# plus en attente
# ---------------------------------------------------------------------------


def test_critere3_sans_techno_relue_precision_trouve_des_technos(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    state["tri_facts"] = FACTS_NO_TECH
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    assert tri.second_pass_reason == "no_tech"

    state["precision_facts"] = FACTS_ATTEIGNABLE
    outcome = ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert outcome.extraction_status is None
    assert outcome.category == Category.atteignable
    assert row["extraction_status"] is None
    assert row["category"] == "atteignable"
    assert row["hors_perimetre_reason"] is None
    assert row["extraction_version"].startswith(PRECISION_MODEL + "|")
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critère 4 — relue, la précision range encore l'offre sans techno : verdict
# définitif, jamais remise en attente
# ---------------------------------------------------------------------------


def test_critere4_sans_techno_relue_precision_confirme_sans_techno(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    state["tri_facts"] = FACTS_NO_TECH
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    state["precision_facts"] = FACTS_NO_TECH
    outcome = ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert outcome.extraction_status is None
    assert outcome.perimetre_causes == ["no_tech"]
    assert row["extraction_status"] is None
    assert row["hors_perimetre_reason"] == "no_tech"
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critère 5 — le plafond de lots est atteint avant la fin de la file : les
# offres sans techno restantes restent en attente, et au run suivant elles
# sont relues sans rappeler le modèle de tri
# ---------------------------------------------------------------------------


def test_critere5_plafond_laisse_les_sans_techno_restantes_sans_rappeler_le_tri(
    db_path, profil, loaded_profile, alias_table, cascade, monkeypatch, tmp_path
):
    calls, state = cascade

    # Une offre déjà « second_pass_pending » / sans techno, comme laissée par
    # un run précédent qui a atteint son plafond de lots.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer_restante = _offer(1)
    save_offer(
        conn,
        offer_restante,
        perimetre_causes=["no_tech"],
        extraction_version=f"{TRI_MODEL}|pDEAD|s1",
        extraction_status="second_pass_pending",
        second_pass_attempts=0,
    )
    conn.close()

    monkeypatch.setenv("SECOND_PASS_BATCH_SIZE", "10")
    monkeypatch.setenv("SECOND_PASS_PAUSE_SECONDS", "0")
    monkeypatch.setenv("SECOND_PASS_MAX_BATCHES", "5")

    state["precision_facts"] = FACTS_ATTEIGNABLE
    _run_main(monkeypatch, tmp_path, profil, [])

    assert (TRI_MODEL, offer_restante.source_id) not in calls
    assert (PRECISION_MODEL, offer_restante.source_id) in calls
    row = _row(db_path, _get_id(db_path, offer_restante.source_id))
    assert row["extraction_status"] is None
    assert row["category"] == "atteignable"


# ---------------------------------------------------------------------------
# Critère 6 — la précision ne répond pas pour une offre sans techno : la
# règle d'essais déjà en place (aucun essai compté, reste en attente)
# s'applique inchangée
# ---------------------------------------------------------------------------


def test_critere6_precision_sans_reponse_ne_compte_aucun_essai(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    state["tri_facts"] = FACTS_NO_TECH
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    state["precision"][offer.source_id] = "no_response"
    outcome = ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert outcome.no_response is True
    assert outcome.second_pass_attempts == 0
    assert row["extraction_status"] == "second_pass_pending"
    assert row["second_pass_attempts"] == 0


# ---------------------------------------------------------------------------
# Critère 7 — rattrapage : une offre déjà en base dont la version d'extraction
# nomme le modèle de tri et dont la cause hors-périmètre est sans techno
# repasse en attente de seconde passe
# ---------------------------------------------------------------------------


def test_critere7_rattrapage_sans_techno_deja_persiste_par_le_tri(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    save_offer(
        conn,
        offer,
        perimetre_causes=["no_tech"],
        extraction_version=f"{TRI_MODEL}|pABC|s1",
        extraction_status=None,
    )

    n = ingestion.rattraper_sans_techno_tri(conn, TRI_MODEL)

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()
    assert n == 1
    assert row["extraction_status"] == "second_pass_pending"
    assert row["hors_perimetre_reason"] == "no_tech"


def test_critere7_rattrapage_ignore_une_offre_sans_version_d_extraction(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    save_offer(
        conn,
        offer,
        perimetre_causes=["no_tech"],
        extraction_version=None,
        extraction_status=None,
    )

    n = ingestion.rattraper_sans_techno_tri(conn, TRI_MODEL)

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()
    assert n == 0
    assert row["extraction_status"] is None


def test_critere7_rattrapage_ignore_une_autre_cause_hors_perimetre(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    save_offer(
        conn,
        offer,
        perimetre_causes=["mgmt_role"],
        extraction_version=f"{TRI_MODEL}|pABC|s1",
        extraction_status=None,
    )

    n = ingestion.rattraper_sans_techno_tri(conn, TRI_MODEL)

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()
    assert n == 0
    assert row["extraction_status"] is None


# ---------------------------------------------------------------------------
# Critère 8 — la ligne de bilan du run dit combien d'offres sans techno ont
# été relues, et combien ont changé de verdict
# ---------------------------------------------------------------------------


def test_critere8_bilan_compte_relues_et_verdicts_changes(
    db_path, profil, cascade, monkeypatch, tmp_path, capsys
):
    calls, state = cascade
    offer_change = _offer(1)
    offer_inchange = _offer(2)

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        is_tri = model == TRI_MODEL
        if offer.source_id == offer_change.source_id:
            return FACTS_NO_TECH if is_tri else FACTS_ATTEIGNABLE
        return FACTS_NO_TECH

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    _run_main(monkeypatch, tmp_path, profil, [offer_change, offer_inchange])

    out = capsys.readouterr().out
    assert "2 offres sans techno relues, 1 ont changé de verdict" in out


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — une offre hors périmètre pour une autre cause
# que sans techno n'est jamais relue
# ---------------------------------------------------------------------------


def test_une_offre_mgmt_role_n_est_jamais_relue(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    state["tri_facts"] = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[TechRequirement(name="python", importance="core")],
        domain="ai_engineering",
        role_level="manager",
    )
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert tri.needs_second_pass is False
    assert row["extraction_status"] is None
    assert row["hors_perimetre_reason"] == "mgmt_role"
    assert len(calls) == 1
