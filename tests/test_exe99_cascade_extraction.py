"""Tests EXE-99 — le run trie toutes les offres avec le modèle de tri, et le
modèle de précision relit celles classées parfait ou rêve et celles que le tri
n'a pas lues (architecture.md, exception TCK-273).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un double
qui distingue le modèle de tri du modèle de précision par le nom de modèle reçu
(critère 13 excepté, où le vrai `extract_facts` tourne contre un faux
`ollama.Client`, pour vérifier la trace qu'il écrit lui-même). Aucun test ne lit
ni n'écrit sous data/.
"""

import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.db as api_db
import api.offers as api_offers
import orchestrator.job_search.ajout.service as ajout_service
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.sources.manual as manual
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

REPO = Path(__file__).resolve().parent.parent

TRI_MODEL = "llama3-test"
PRECISION_MODEL = "gemma-test"

# Sous profiles/example.yaml (domaine ai_engineering=cœur-cible, role_ceiling=ic,
# seniority_ceiling=intermediate) :

# Désirable (ai_engineering) ET atteignable (techs connues, séniorité/rôle dans
# la cible) → parfait.
FACTS_PARFAIT = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="git", importance="required"),
    ],
    domain="ai_engineering",
    role_level="ic",
)

# Désirable (ai_engineering) mais pas atteignable (séniorité au-delà du plafond,
# techs inconnues) → rêve.
FACTS_REVE = ExtractedFacts(
    seniority_required="senior",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="rust", importance="core"),
    ],
    domain="ai_engineering",
    role_level="ic",
)

# Ni désirable ni atteignable → hors (jamais de seconde passe).
FACTS_HORS = ExtractedFacts(
    seniority_required="senior",
    techs_required=[
        TechRequirement(name="rust", importance="core"),
        TechRequirement(name="kubernetes", importance="core"),
    ],
    domain="backend",
    role_level="ic",
)

# Atteignable, peu désirable (backend) → atteignable (jamais de seconde passe).
FACTS_ATTEIGNABLE = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="fastapi", importance="required"),
        TechRequirement(name="kubernetes", importance="nice_to_have"),
    ],
    domain="backend",
)

# role_level=manager → cause hors-périmètre mgmt_role, qui prime sur une
# catégorie sous-jacente "rêve" (jamais de seconde passe pour elle non plus).
FACTS_MGMT_HP = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="git", importance="required"),
    ],
    domain="ai_engineering",
    role_level="manager",
)

FAITS_TRI_JSON = json.dumps(
    {
        "seniority_required": "intermediate",
        "techs_required": [
            {"name": "python", "importance": "core"},
            {"name": "git", "importance": "required"},
        ],
        "domain": "ai_engineering",
        "role_level": "ic",
        "langues_requises": [],
    }
)
FAITS_PRECISION_JSON = json.dumps(
    {
        "seniority_required": "senior",
        "techs_required": [
            {"name": "rust", "importance": "core"},
            {"name": "kubernetes", "importance": "core"},
        ],
        "domain": "backend",
        "role_level": "ic",
        "langues_requises": [],
    }
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
    """Double de `ingestion.extract_facts` distinguant tri/précision par le nom
    de modèle reçu. `state['tri_facts']`/`state['tri_fail']` et
    `state['precision_facts']`/`state['precision_fail']` pilotent chaque modèle
    indépendamment. `calls` liste (model, source_id) dans l'ordre d'appel."""
    calls: list[tuple[str, str]] = []
    state = {
        "tri_facts": FACTS_ATTEIGNABLE,
        "tri_fail": False,
        "precision_facts": FACTS_ATTEIGNABLE,
        "precision_fail": False,
    }

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        if model == TRI_MODEL:
            return None if state["tri_fail"] else state["tri_facts"]
        return None if state["precision_fail"] else state["precision_facts"]

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    # EXE-100 : le /run décharge les modèles en finissant — ces tests ne
    # parlent jamais à un Ollama réel.
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    return calls, state


def _offer(n: int, **overrides) -> JobOffer:
    base = dict(
        source="france_travail",
        source_id=f"FT-{n}",
        fingerprint=f"fp-{n}",
        title=f"Offre {n}",
        description="Une offre.",
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


_LIST_OFFERS_DEFAULTS = dict(
    remote=None,
    source=None,
    verdict=None,
    seen_candidat=None,
    filtered_out=None,
    category=None,
    exclude_category=None,
    hors_perimetre=None,
    hp_cause=None,
    exclude_ad_language=None,
    etat_review=None,
    q=None,
    view_profile=None,
    include_remote=None,
    extraction_status=None,
    sort="category",
    order="desc",
)


def _run_main(monkeypatch, tmp_path, profil_path, source_cls) -> None:
    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", source_cls)
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
# Critère 1 — chaque offre en attente ou à refaire est d'abord extraite par le
# modèle de tri
# ---------------------------------------------------------------------------


class _AucuneOffreSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return []


def test_critere1_pending_et_retry_extraites_par_le_tri_d_abord(
    db_path, profil, cascade, monkeypatch, tmp_path
):
    calls, _state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    profile, _ = load_profile(profil)

    pending = _offer(1)
    ingestion.register_offer(conn, pending, profile)

    retry = _offer(2)
    ingestion.register_offer(conn, retry, profile)
    conn.execute(
        "UPDATE offers SET extraction_status='retry', extraction_attempts=1 "
        "WHERE source_id=?",
        (retry.source_id,),
    )
    conn.commit()
    conn.close()

    _run_main(monkeypatch, tmp_path, profil, _AucuneOffreSource)

    assert {m for m, _ in calls} == {TRI_MODEL}
    assert {sid for _, sid in calls} == {pending.source_id, retry.source_id}


# ---------------------------------------------------------------------------
# Critère 2 — tri parfait ou rêve → la précision est appelée dans le même run
# ---------------------------------------------------------------------------


def test_critere2_tri_parfait_ou_reve_appelle_la_precision_dans_le_meme_run(
    db_path, profil, cascade, monkeypatch, tmp_path
):
    calls, _state = cascade
    offer_parfait = _offer(1)
    offer_reve = _offer(2)

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        if offer.source_id == offer_parfait.source_id:
            return FACTS_PARFAIT
        return FACTS_REVE

    monkeypatch.setattr(ingestion, "extract_facts", _extract)

    class _DeuxOffresSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [offer_parfait, offer_reve]

    _run_main(monkeypatch, tmp_path, profil, _DeuxOffresSource)

    assert calls.count((TRI_MODEL, offer_parfait.source_id)) == 1
    assert calls.count((PRECISION_MODEL, offer_parfait.source_id)) == 1
    assert calls.count((TRI_MODEL, offer_reve.source_id)) == 1
    assert calls.count((PRECISION_MODEL, offer_reve.source_id)) == 1


# ---------------------------------------------------------------------------
# Critère 3 — atteignable, hors, hors périmètre : pas de précision
# ---------------------------------------------------------------------------


def test_critere3_atteignable_hors_hors_perimetre_pas_de_precision(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    for i, facts in enumerate((FACTS_ATTEIGNABLE, FACTS_HORS, FACTS_MGMT_HP), start=1):
        state["tri_facts"] = facts
        offer = _offer(i)
        ingestion.register_offer(conn, offer, loaded_profile)
        tri = ingestion.run_tri(
            conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
        )
        assert tri.needs_second_pass is False

    conn.close()
    assert len(calls) == 3
    assert all(model == TRI_MODEL for model, _ in calls)


# ---------------------------------------------------------------------------
# Critère 4 — le tri échoue à lire une offre : la précision l'extrait dans le
# même run
# ---------------------------------------------------------------------------


def test_critere4_tri_echoue_a_lire_appelle_la_precision_dans_le_meme_run(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_fail"] = True
    state["precision_facts"] = FACTS_ATTEIGNABLE
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    assert tri.needs_second_pass is True
    assert tri.second_pass_reason == "unreadable"

    outcome = ingestion.resolve_unreadable_with_precision(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        attempts_before=0,
    )
    conn.close()

    assert calls == [(TRI_MODEL, offer.source_id), (PRECISION_MODEL, offer.source_id)]
    assert outcome.extraction_status is None
    assert outcome.category == Category.atteignable


# ---------------------------------------------------------------------------
# Critère 5 — la seconde passe réussit : faits et catégorie du modèle de
# précision
# ---------------------------------------------------------------------------


def test_critere5_seconde_passe_reussit_faits_et_categorie_de_la_precision(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_facts"] = FACTS_HORS
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    assert tri.needs_second_pass is True
    assert tri.second_pass_reason == "category"
    assert tri.outcome.category == Category.parfait

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
    conn.close()

    assert outcome.category == Category.hors
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["category"] == "hors"
    assert row["extraction_status"] is None
    facts_persisted = json.loads(row["extracted_facts_json"])
    assert facts_persisted["domain"] == "backend"  # faits précision, pas ceux du tri
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critère 6 — relire une offre rend la version du modèle dont les faits sont
# enregistrés
# ---------------------------------------------------------------------------


def test_critere6_relire_rend_la_version_du_modele_dont_les_faits_sont_enregistres(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade

    state["tri_facts"] = FACTS_ATTEIGNABLE
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer_tri = _offer(1)
    ingestion.register_offer(conn, offer_tri, loaded_profile)
    ingestion.run_tri(
        conn, offer_tri, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    state["tri_facts"] = FACTS_PARFAIT
    state["precision_facts"] = FACTS_HORS
    offer_precision = _offer(2)
    ingestion.register_offer(conn, offer_precision, loaded_profile)
    tri2 = ingestion.run_tri(
        conn, offer_precision, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    ingestion.resolve_category_second_pass(
        conn,
        offer_precision,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri2.outcome.category,
        second_pass_attempts_before=0,
    )
    conn.close()

    row_tri = _row(db_path, _get_id(db_path, offer_tri.source_id))
    row_precision = _row(db_path, _get_id(db_path, offer_precision.source_id))
    assert row_tri["extraction_version"].startswith(TRI_MODEL + "|")
    assert row_precision["extraction_version"].startswith(PRECISION_MODEL + "|")
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# Critère 7 — seconde passe en échec sur parfait/rêve : garde les faits et la
# catégorie du tri, reste « en attente de seconde passe »
# ---------------------------------------------------------------------------


def test_critere7_seconde_passe_echoue_garde_faits_et_categorie_du_tri(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    state["precision_fail"] = True
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
    conn.close()

    assert outcome.extraction_status == "second_pass_pending"
    assert outcome.category == Category.parfait
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "second_pass_pending"
    assert row["category"] == "parfait"
    assert row["second_pass_attempts"] == 1
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critère 8 — le run suivant reprend la seconde passe en attente sans rappeler
# le modèle de tri
# ---------------------------------------------------------------------------


def test_critere8_run_suivant_reprend_la_seconde_passe_sans_rappeler_le_tri(
    db_path, profil, cascade, monkeypatch, tmp_path
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    profile, _ = load_profile(profil)
    alias = load_alias_table(ALIAS_PATH)
    offer = _offer(1)
    ingestion.register_offer(conn, offer, profile)
    tri = ingestion.run_tri(conn, offer, profile, alias, model=TRI_MODEL, host="h")
    ingestion.resolve_category_second_pass(
        conn,
        offer,
        profile,
        alias,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )
    conn.close()
    calls.clear()

    state["precision_fail"] = False
    state["precision_facts"] = FACTS_PARFAIT

    _run_main(monkeypatch, tmp_path, profil, _AucuneOffreSource)

    assert calls == [(PRECISION_MODEL, offer.source_id)]
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] is None
    assert row["category"] == "parfait"


# ---------------------------------------------------------------------------
# Critère 9 — après 3 secondes passes en échec, l'offre sort de l'attente et
# garde les faits du tri
# ---------------------------------------------------------------------------


def test_critere9_apres_3_echecs_de_seconde_passe_sort_de_l_attente(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )

    outcome = None
    for attempts_before in range(3):
        outcome = ingestion.resolve_category_second_pass(
            conn,
            offer,
            loaded_profile,
            alias_table,
            model=PRECISION_MODEL,
            host="h",
            tri_category=tri.outcome.category,
            second_pass_attempts_before=attempts_before,
        )
    conn.close()

    assert outcome.extraction_status is None
    assert outcome.category == Category.parfait
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] is None
    assert row["category"] == "parfait"
    assert len(calls) == 4  # 1 tri + 3 secondes passes en échec


# ---------------------------------------------------------------------------
# Critère 10 — les deux modèles échouent : à refaire, un seul essai de plus
# ---------------------------------------------------------------------------


def test_critere10_les_deux_modeles_echouent_a_refaire_un_seul_essai_de_plus(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_fail"] = True
    state["precision_fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    assert tri.needs_second_pass is True
    assert tri.second_pass_reason == "unreadable"

    outcome = ingestion.resolve_unreadable_with_precision(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        attempts_before=0,
    )
    conn.close()

    assert outcome.extraction_status == "retry"
    assert outcome.extraction_attempts == 1
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "retry"
    assert row["extraction_attempts"] == 1
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critères 11 & 12 — le tri complet précède la première seconde passe ; l'ordre
# des secondes passes est parfait, puis rêve, puis non lues
# ---------------------------------------------------------------------------


def test_critere11_12_tri_complet_puis_ordre_parfait_reve_non_lues(
    db_path, profil, cascade, monkeypatch, tmp_path
):
    calls, _state = cascade
    offer_illisible = _offer(1)
    offer_reve = _offer(2)
    offer_parfait = _offer(3)

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        if model == TRI_MODEL:
            if offer.source_id == offer_illisible.source_id:
                return None
            if offer.source_id == offer_parfait.source_id:
                return FACTS_PARFAIT
            return FACTS_REVE
        # précision : tout le monde réussit
        if offer.source_id == offer_illisible.source_id:
            return FACTS_ATTEIGNABLE
        if offer.source_id == offer_parfait.source_id:
            return FACTS_PARFAIT
        return FACTS_REVE

    monkeypatch.setattr(ingestion, "extract_facts", _extract)

    class _TroisOffresSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            # Ordre de fetch volontairement inverse de l'ordre attendu en phase
            # 2, pour prouver que l'ordre vient de la catégorie, pas du fetch.
            return [offer_illisible, offer_reve, offer_parfait]

    _run_main(monkeypatch, tmp_path, profil, _TroisOffresSource)

    tri_positions = [i for i, (m, _sid) in enumerate(calls) if m == TRI_MODEL]
    precision_positions = [
        i for i, (m, _sid) in enumerate(calls) if m == PRECISION_MODEL
    ]
    assert len(tri_positions) == 3
    assert len(precision_positions) == 3
    assert max(tri_positions) < min(precision_positions)

    precision_order = [sid for m, sid in calls if m == PRECISION_MODEL]
    assert precision_order == [
        offer_parfait.source_id,
        offer_reve.source_id,
        offer_illisible.source_id,
    ]


# ---------------------------------------------------------------------------
# Critère 13 — une offre relue porte deux traces, chacune avec son modèle et sa
# version d'extraction
# ---------------------------------------------------------------------------


@pytest.fixture
def real_llm(tmp_path, monkeypatch):
    """Le vrai `extract_facts` tourne (donc trace) contre un faux `ollama.Client`
    qui distingue tri/précision par le nom de modèle reçu."""
    trace_path = tmp_path / "traces" / "extract_facts.jsonl"
    monkeypatch.setattr(extractor, "TRACE_PATH", trace_path)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def chat(self, *, model, messages, **kwargs):
            content = FAITS_TRI_JSON if model == TRI_MODEL else FAITS_PRECISION_JSON
            return SimpleNamespace(message=SimpleNamespace(content=content))

    monkeypatch.setattr("ollama.Client", _Client)
    return trace_path


def test_critere13_une_offre_relue_porte_deux_traces(
    db_path, loaded_profile, alias_table, real_llm
):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    assert tri.needs_second_pass is True
    ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )
    conn.close()

    lines = real_llm.read_text(encoding="utf-8").strip().splitlines()
    traces = [
        json.loads(line)
        for line in lines
        if json.loads(line)["offer_id"] == offer.source_id
    ]
    assert len(traces) == 2
    models = {t["model"] for t in traces}
    assert models == {TRI_MODEL, PRECISION_MODEL}
    for t in traces:
        assert t["extraction_version"].startswith(t["model"] + "|")


# ---------------------------------------------------------------------------
# Critère 14 — modèle de tri configurable, défaut llama3
# ---------------------------------------------------------------------------


def test_critere14_modele_de_tri_defaut_llama3_sans_configuration(
    db_path, profil, monkeypatch, tmp_path
):
    calls: list[tuple[str, str]] = []

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        return FACTS_ATTEIGNABLE

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    monkeypatch.delenv("OLLAMA_MODEL_TRI", raising=False)

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    run.main()

    assert calls == [("llama3", "FT-1")]


def test_critere14_modele_de_tri_configure_explicitement(
    db_path, profil, monkeypatch, tmp_path
):
    calls: list[tuple[str, str]] = []

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        return FACTS_ATTEIGNABLE

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", "mon-modele-tri")

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    run.main()

    assert calls == [("mon-modele-tri", "FT-1")]


# ---------------------------------------------------------------------------
# Critère 15 — le modèle de précision reste OLLAMA_MODEL, défaut gemma4:12b
# ---------------------------------------------------------------------------


def test_critere15_modele_de_precision_reste_ollama_model_defaut_gemma(
    db_path, profil, monkeypatch, tmp_path
):
    calls: list[tuple[str, str]] = []

    def _extract(offer, model, host):
        calls.append((model, offer.source_id))
        return FACTS_PARFAIT

    monkeypatch.setattr(ingestion, "extract_facts", _extract)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    monkeypatch.delenv("OLLAMA_MODEL_TRI", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    run.main()

    assert calls == [("llama3", "FT-1"), ("gemma4:12b", "FT-1")]


# ---------------------------------------------------------------------------
# Critère 16 — Ollama injoignable ou modèle absent : le run refuse de démarrer,
# rien n'est écrit en base
# ---------------------------------------------------------------------------


def test_critere16_ollama_injoignable_refuse_de_demarrer(
    db_path, profil, monkeypatch, tmp_path, capsys
):
    import orchestrator.job_search.sources.france_travail as ft

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    class _ClientIndisponible:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def list(self):
            raise ConnectionError("Ollama ne répond pas")

    monkeypatch.setattr("ollama.Client", _ClientIndisponible)
    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    run.main()

    out = capsys.readouterr().out
    assert "injoignable" in out
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    conn.close()
    assert n == 0


def test_critere16_modele_manquant_refuse_de_demarrer(
    db_path, profil, monkeypatch, tmp_path, capsys
):
    import orchestrator.job_search.sources.france_travail as ft

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    class _ClientModeleManquant:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def list(self):
            return SimpleNamespace(models=[SimpleNamespace(model="gemma4:12b")])

    monkeypatch.setattr("ollama.Client", _ClientModeleManquant)
    monkeypatch.setattr(ft, "FranceTravailSource", _UneOffreSource)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", "llama3")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b")
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    run.main()

    out = capsys.readouterr().out
    assert "llama3" in out
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    conn.close()
    assert n == 0


# ---------------------------------------------------------------------------
# Critère 17 — un ajout à la main suit la même cascade
# ---------------------------------------------------------------------------


def test_critere17_ajout_a_la_main_suit_la_meme_cascade(
    db_path, profil, cascade, monkeypatch
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_facts"] = FACTS_HORS
    monkeypatch.setattr(ajout_service, "PROFILE_PATH", profil)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)

    conn = storage_db.get_connection()
    ajout_id = ajout_service.create_ajout(conn, None, "texte de l'offre collée")
    conn.close()

    source = manual.ManualSource(
        None,
        texte="Nous cherchons un profil.",
        titre="Développeur",
        lieu="Strasbourg",
    )
    ajout_service.run_ajout(ajout_id, source)

    assert calls == [
        (TRI_MODEL, source.source_id),
        (PRECISION_MODEL, source.source_id),
    ]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ajout = conn.execute("SELECT * FROM ajouts WHERE id = ?", (ajout_id,)).fetchone()
    conn.close()
    assert ajout["statut"] == "termine"
    assert ajout["categorie"] == "hors"


# ---------------------------------------------------------------------------
# Critère 18 — la vue opérateur filtre sur « Seconde passe en attente »
# ---------------------------------------------------------------------------


def test_critere18_filtre_api_seconde_passe_en_attente(
    db_path, loaded_profile, alias_table, cascade
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model=TRI_MODEL, host="h"
    )
    ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model=PRECISION_MODEL,
        host="h",
        tri_category=tri.outcome.category,
        second_pass_attempts_before=0,
    )

    autre = _offer(2)
    ingestion.register_offer(conn, autre, loaded_profile)
    conn.close()

    rows = api_offers.list_offers(
        **{**_LIST_OFFERS_DEFAULTS, "extraction_status": "second_pass_pending"}
    )
    assert [r.id for r in rows] == [_get_id(db_path, offer.source_id)]
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# Critère 19 — la sortie du run dit combien d'offres triées, relues, en
# attente de seconde passe
# ---------------------------------------------------------------------------


def test_critere19_run_rapporte_triees_relues_en_attente(
    db_path, profil, cascade, monkeypatch, tmp_path, capsys
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    state["precision_fail"] = True

    class _UneOffreSource:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self) -> list[JobOffer]:
            return [_offer(1)]

    _run_main(monkeypatch, tmp_path, profil, _UneOffreSource)

    out = capsys.readouterr().out
    assert "1 offres triées, 1 relues, 1 en attente de seconde passe" in out
    assert len(calls) == 2
