"""Tests EXE-115 — une offre sans texte n'est ni lue par un modèle ni classée
(architecture.md, « Offre sans texte »).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un double
contrôlable (`fake_extract`). Aucun test ne lit ni n'écrit sous data/ : base, profil
et REPO_ROOT (run) sont en tmp_path.
"""

import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import api.db as api_db
import api.offers as api_offers
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.digest.formatter import generate_digest
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
from orchestrator.job_search.storage.offers import get_offers_since, save_offer

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
    manquant ne doit jamais apparaître dans `calls` (critère 1)."""
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
# Critère 1 — aucun appel modèle pour une offre dont le texte nettoyé < 50 car.
# ---------------------------------------------------------------------------


def test_critere1_aucun_appel_modele_texte_court(db_path, loaded_profile, fake_extract):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1, description=_TEXTE_COURT)

    outcome = ingestion.register_offer(conn, offer, loaded_profile)

    # Reproduit la sélection du /run (run.py, étage 5b) : seules pending/retry
    # sont triées — une offre texte manquant ne doit jamais y figurer.
    pending_rows = conn.execute(
        "SELECT * FROM offers WHERE extraction_status IN ('pending', 'retry')"
    ).fetchall()
    conn.close()

    assert outcome.filtered is False
    assert outcome.missing_text is True
    assert calls == []
    assert pending_rows == []


# ---------------------------------------------------------------------------
# Critère 2 — ni faits, ni catégorie, ni cause hors périmètre ; état « texte
# manquant »
# ---------------------------------------------------------------------------


def test_critere2_offre_sans_texte_porte_etat_texte_manquant(
    db_path, loaded_profile, fake_extract
):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(2, description=_TEXTE_COURT)

    ingestion.register_offer(conn, offer, loaded_profile)
    conn.close()

    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "missing_text"
    assert row["extracted_facts_json"] is None
    assert row["category"] is None
    assert row["hors_perimetre_reason"] is None
    assert row["perimetre_causes"] is None


# ---------------------------------------------------------------------------
# Critère 3 — absente du digest
# ---------------------------------------------------------------------------


def test_critere3_absente_du_digest(db_path, loaded_profile, alias_table, fake_extract):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(3, description=_TEXTE_COURT, title="OffreUniqueSansTexte")
    # Chaîne complète (comme process_offer / run.py) : avant ce ticket, le texte
    # court n'empêchait pas l'appel au modèle ni la catégorisation qui suit.
    ingestion.process_offer(
        conn,
        offer,
        loaded_profile,
        alias_table,
        tri_model="m",
        tri_host="h",
        precision_model="m2",
        precision_host="h",
    )

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    scored = get_offers_since(conn, since)
    conn.close()
    digest = generate_digest(scored, run_at=datetime.now(timezone.utc))

    assert "OffreUniqueSansTexte" not in digest


# ---------------------------------------------------------------------------
# Critère 4 — absente de la vue candidat (jamais de catégorie à filtrer dessus)
# ---------------------------------------------------------------------------


def test_critere4_absente_vue_candidat(
    db_path, loaded_profile, alias_table, fake_extract
):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(4, description=_TEXTE_COURT)
    ingestion.process_offer(
        conn,
        offer,
        loaded_profile,
        alias_table,
        tri_model="m",
        tri_host="h",
        precision_model="m2",
        precision_host="h",
    )
    conn.close()

    offer_id = _get_id(db_path, offer.source_id)
    for cat in ("parfait", "reve", "atteignable"):
        rows = api_offers.list_offers(**{**_LIST_OFFERS_DEFAULTS, "category": cat})
        assert offer_id not in {r.id for r in rows}


# ---------------------------------------------------------------------------
# Critère 5 — filtre API « texte manquant », rend ces offres et elles seules,
# avec leur nombre
# ---------------------------------------------------------------------------


def test_critere5_filtre_api_texte_manquant(db_path, loaded_profile, fake_extract):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sans_texte = _offer(5, description=_TEXTE_COURT)
    normale = _offer(6, description=_TEXTE_LONG)
    ingestion.register_offer(conn, sans_texte, loaded_profile)
    ingestion.register_offer(conn, normale, loaded_profile)
    conn.close()

    rows = api_offers.list_offers(
        **{**_LIST_OFFERS_DEFAULTS, "extraction_status": "missing_text"}
    )

    assert [r.id for r in rows] == [_get_id(db_path, sans_texte.source_id)]
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Critère 6 — un run ultérieur qui reçoit le texte la fait passer en attente
# ---------------------------------------------------------------------------


def test_critere6_texte_recu_repasse_en_attente(db_path, loaded_profile, fake_extract):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(7, description=_TEXTE_COURT)
    ingestion.register_offer(conn, offer, loaded_profile)

    offer_avec_texte = _offer(7, description=_TEXTE_LONG)
    n = ingestion.rattraper_texte_recu(conn, [offer_avec_texte])
    conn.close()

    assert n == 1
    assert calls == []  # le rattrapage n'appelle lui-même aucun modèle
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "pending"
    assert row["extraction_attempts"] == 0
    assert row["description"] == _TEXTE_LONG


def test_critere6_offre_pas_en_texte_manquant_non_touchee(
    db_path, loaded_profile, fake_extract
):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(8, description=_TEXTE_LONG)
    ingestion.register_offer(conn, offer, loaded_profile)  # déjà "pending"

    n = ingestion.rattraper_texte_recu(conn, [offer])
    conn.close()

    assert n == 0


# ---------------------------------------------------------------------------
# Critère 7 — rattrapage d'une offre déjà catégorisée (ou hors périmètre) dont
# le texte est en réalité trop court
# ---------------------------------------------------------------------------


def test_critere7_offre_categorisee_sans_texte_repasse_texte_manquant(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(9, description=_TEXTE_COURT)
    # Simule une offre classée avant ce ticket (texte déjà court à l'époque).
    save_offer(
        conn,
        offer,
        category=Category.reve,
        techs_matched=["python"],
        techs_missing=["kubernetes"],
        extraction_version="llama3@abc",
        extraction_status=None,
    )

    n = ingestion.rattraper_offres_categorisees_sans_texte(conn)
    conn.close()

    assert n == 1
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "missing_text"
    assert row["category"] is None
    assert row["extracted_facts_json"] is None
    assert row["perimetre_causes"] is None


def test_critere7_offre_hors_perimetre_sans_texte_repasse_texte_manquant(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(10, description=_TEXTE_COURT)
    save_offer(
        conn,
        offer,
        perimetre_causes=["no_tech"],
        extraction_status=None,
    )

    n = ingestion.rattraper_offres_categorisees_sans_texte(conn)
    conn.close()

    assert n == 1
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "missing_text"
    assert row["hors_perimetre_reason"] is None
    assert row["perimetre_causes"] is None


def test_critere7_offre_categorisee_texte_suffisant_non_touchee(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(11, description=_TEXTE_LONG)
    save_offer(conn, offer, category=Category.atteignable, extraction_status=None)

    n = ingestion.rattraper_offres_categorisees_sans_texte(conn)
    conn.close()

    assert n == 0
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["category"] == "atteignable"


def test_critere7_champs_humains_non_effaces(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(12, description=_TEXTE_COURT)
    save_offer(conn, offer, category=Category.reve, extraction_status=None)
    conn.execute(
        "UPDATE offers SET categorie_corrigee = ?, remarque = ?, reviewed_at = ? "
        "WHERE source_id = ?",
        ("hors", "pas pertinent", "2026-10-01T00:00:00+00:00", offer.source_id),
    )
    conn.commit()

    ingestion.rattraper_offres_categorisees_sans_texte(conn)
    conn.close()

    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["categorie_corrigee"] == "hors"
    assert row["remarque"] == "pas pertinent"
    assert row["reviewed_at"] == "2026-10-01T00:00:00+00:00"


def test_critere7_offre_filtree_non_touchee(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(13, description=_TEXTE_COURT)
    save_offer(conn, offer, filtered_out=True, filter_reason="location:hors_zone")

    n = ingestion.rattraper_offres_categorisees_sans_texte(conn)
    conn.close()

    assert n == 0


# ---------------------------------------------------------------------------
# Critère 8 — la ligne de bilan du run donne le nombre d'offres en texte
# manquant, à part des offres à refaire et des illisibles
# ---------------------------------------------------------------------------


class _DeuxOffresSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return [
            _offer(14, description=_TEXTE_COURT, fetched_at=datetime.now(timezone.utc)),
            _offer(
                15,
                description=_TEXTE_LONG,
                fetched_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            ),
        ]


def test_critere8_bilan_compte_texte_manquant(
    db_path, profil, fake_extract, monkeypatch, tmp_path, capsys
):
    _run_main(monkeypatch, tmp_path, profil, _DeuxOffresSource)

    out = capsys.readouterr().out
    assert "0 à refaire, 0 illisibles, 1 texte manquant" in out


# ---------------------------------------------------------------------------
# Invariant « une seule implémentation » (ingestion.py, docstring de module) —
# l'ajout à la main suit la même règle que le /run (architecture.md, « Offre
# sans texte »).
# ---------------------------------------------------------------------------


def test_process_offer_texte_court_sans_appel_modele(
    db_path, loaded_profile, alias_table, fake_extract
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(16, description=_TEXTE_COURT)

    outcome = ingestion.process_offer(
        conn,
        offer,
        loaded_profile,
        alias_table,
        tri_model="m",
        tri_host="h",
        precision_model="m2",
        precision_host="h",
    )
    conn.close()

    assert outcome.extraction_status == "missing_text"
    assert calls == []
