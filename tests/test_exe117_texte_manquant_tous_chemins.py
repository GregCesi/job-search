"""Tests EXE-117 — aucune offre sans texte n'est envoyée à un modèle, quel que
soit le chemin par lequel elle entre en file (architecture.md, « Offre sans
texte ») : attente d'extraction, à refaire, attente de seconde passe, ou
rattrapage du filtre de contrat (EXE-114).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un
double contrôlable (`fake_extract`, repris de test_exe115_texte_manquant.py).
Aucun test ne lit ni n'écrit sous data/.
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

FACTS_OK = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[TechRequirement(name="python", importance="core")],
    domain="backend",
)

# 16 caractères — sous le seuil de 50 (ingestion._MIN_TEXT_LENGTH).
_TEXTE_COURT = "Développeur H/F"
# 77 caractères — au-dessus du seuil.
_TEXTE_LONG = (
    "Nous cherchons un développeur Python FastAPI, stack moderne, équipe produit."
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
def fake_extract(monkeypatch):
    """Double de `ingestion.extract_facts` — compte ses appels. Une offre texte
    manquant ne doit jamais apparaître dans `calls` (critères 1-4)."""
    calls: list[JobOffer] = []
    state = {"facts": FACTS_OK, "fail": False}

    def _extract(offer, model, host):
        calls.append(offer)
        if state["fail"]:
            return None
        return state["facts"]

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
        description=_TEXTE_LONG,
        company="Acme",
        location="67 - Strasbourg",
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


def _run_main(monkeypatch, tmp_path, profil_path, source_cls) -> None:
    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", source_cls)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
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
            "--no-actiris",
            "--no-forem",
        ],
    )
    run.main()


class _VideSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return []


# ---------------------------------------------------------------------------
# Critère 1 — offre « en attente d'extraction » (pending) texte court : aucun
# appel modèle, passe en texte manquant
# ---------------------------------------------------------------------------


def test_critere1_pending_texte_court_aucun_appel_modele(
    db_path, loaded_profile, alias_table, fake_extract
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1, description=_TEXTE_COURT)
    # Simule une offre déjà « en attente » par un chemin qui n'est pas
    # register_offer (ex. rattrapage) alors que son texte est trop court.
    save_offer(conn, offer, extraction_status="pending", extraction_attempts=0)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model="m", host="h"
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert calls == []
    assert tri.needs_second_pass is False
    assert tri.outcome.extraction_status == "missing_text"
    assert row["extraction_status"] == "missing_text"


# ---------------------------------------------------------------------------
# Critère 2 — offre « à refaire » (retry) texte court : même résultat
# ---------------------------------------------------------------------------


def test_critere2_retry_texte_court_aucun_appel_modele(
    db_path, loaded_profile, alias_table, fake_extract
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(2, description=_TEXTE_COURT)
    save_offer(conn, offer, extraction_status="retry", extraction_attempts=2)

    tri = ingestion.run_tri(
        conn, offer, loaded_profile, alias_table, model="m", host="h"
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert calls == []
    assert tri.outcome.extraction_status == "missing_text"
    assert row["extraction_status"] == "missing_text"
    assert row["extraction_attempts"] == 0


# ---------------------------------------------------------------------------
# Critère 3 — offre « en attente de seconde passe » texte court : le modèle de
# précision n'est pas appelé, elle perd faits/catégorie/cause, passe en texte
# manquant
# ---------------------------------------------------------------------------


def test_critere3_second_pass_pending_texte_court_devient_texte_manquant(
    db_path, loaded_profile, alias_table, fake_extract
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(3, description=_TEXTE_COURT)
    # Classée parfait par le tri, puis le texte s'avère en réalité trop court
    # (ex. une source qui révise son texte entre le tri et la seconde passe).
    save_offer(
        conn,
        offer,
        category=Category.parfait,
        techs_matched=["python"],
        techs_missing=[],
        extraction_version="llama3|pXXX|s1",
        extraction_status="second_pass_pending",
        second_pass_attempts=0,
    )

    outcome = ingestion.resolve_category_second_pass(
        conn,
        offer,
        loaded_profile,
        alias_table,
        model="m2",
        host="h",
        tri_category=Category.parfait,
        second_pass_attempts_before=0,
    )

    row = _row(db_path, _get_id(db_path, offer.source_id))
    conn.close()

    assert calls == []
    assert outcome.extraction_status == "missing_text"
    assert row["extraction_status"] == "missing_text"
    assert row["category"] is None
    assert row["extracted_facts_json"] is None
    assert row["hors_perimetre_reason"] is None
    assert row["techs_matched_json"] is None


# ---------------------------------------------------------------------------
# Critère 4 — offre sans texte rattrapée par le filtre de contrat : à la fin
# de ce même run, elle est en texte manquant et n'a aucune catégorie
# ---------------------------------------------------------------------------


def test_critere4_rattrapage_filtre_contrat_offre_sans_texte_devient_texte_manquant(
    db_path, profil, fake_extract, monkeypatch, tmp_path
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(
        4,
        description=_TEXTE_COURT,
        source="indeed",
        contract_type="Permanent",
        location="67 - Strasbourg",
    )
    save_offer(conn, offer, filtered_out=True, filter_reason="contract:permanent")
    conn.close()

    _run_main(monkeypatch, tmp_path, profil, _VideSource)

    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "missing_text"
    assert row["category"] is None
    assert bool(row["filtered_out"]) is False
    assert all(c.source_id != offer.source_id for c in calls)


# ---------------------------------------------------------------------------
# Critère 5 — la ligne de bilan du run compte ces offres dans le nombre de
# textes manquants
# ---------------------------------------------------------------------------


def test_critere5_bilan_compte_texte_manquant_rattrape_par_filtre_contrat(
    db_path, profil, fake_extract, monkeypatch, tmp_path, capsys
):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(
        5,
        description=_TEXTE_COURT,
        source="indeed",
        contract_type="Permanent",
        location="67 - Strasbourg",
    )
    save_offer(conn, offer, filtered_out=True, filter_reason="contract:permanent")
    conn.close()

    _run_main(monkeypatch, tmp_path, profil, _VideSource)

    out = capsys.readouterr().out
    assert "0 à refaire, 0 illisibles, 1 texte manquant" in out
