"""Tests EXE-98 — une extraction échouée reste à refaire (TCK-273).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un double
contrôlable (`fake_extract`). Aucun test ne lit ni n'écrit sous data/ : base, profil
et REPO_ROOT (run/rescore) sont en tmp_path.
"""

import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import api.db as api_db
import api.offers as api_offers
import orchestrator.job_search.ajout.service as ajout_service
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.rescore as rescore
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.sources.manual as manual
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import ALIAS_PATH
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    TechRequirement,
)
from orchestrator.job_search.storage.db import init_db

REPO = Path(__file__).resolve().parent.parent

FACTS_OK = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="fastapi", importance="required"),
        TechRequirement(name="kubernetes", importance="nice_to_have"),
    ],
    domain="backend",
)

# Signature exacte des faits de repli produits par `_fallback()` avant ce ticket
# (orchestrator/job_search/scoring/extractor.py, historique figé pour la migration).
_LEGACY_FALLBACK_FACTS_JSON = (
    '{"seniority_required":"intermediate","techs_required":[],"domain":"other",'
    '"role_level":"ic","langues_requises":[],"parse_failed":true}'
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
    """Double de `ingestion.extract_facts` : rend `state['facts']` (par défaut
    FACTS_OK), ou None si `state['fail']` est vrai (extraction en échec, vocabulaire
    du ticket : aucune réponse lisible après les 3 tentatives). Compte ses appels.

    EXE-99 : neutralise aussi le contrôle de disponibilité Ollama du /run
    (`ensure_models_available`) — ces tests ne parlent jamais à un Ollama réel,
    tri ou précision, et FACTS_OK catégorise « atteignable » sous le profil
    exemple, donc aucune seconde passe n'est déclenchée par ce double."""
    calls: list[JobOffer] = []
    state = {"facts": FACTS_OK, "fail": False}

    def _extract(offer, model, host):
        calls.append(offer)
        if state["fail"]:
            return None
        return state["facts"]

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
        title=f"Développeur Python {n}",
        description="Nous cherchons un développeur Python FastAPI, stack moderne.",
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
            "--no-actiris",
        ],
    )
    run.main()


# ---------------------------------------------------------------------------
# Critère 1 — offre nouvelle enregistrée « en attente » avant l'appel au modèle
# ---------------------------------------------------------------------------


def test_critere1_offre_enregistree_en_attente_avant_extraction(
    db_path, loaded_profile, fake_extract
):
    calls, _ = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)

    outcome = ingestion.register_offer(conn, offer, loaded_profile)
    conn.close()

    assert outcome.filtered is False
    assert calls == []

    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "pending"
    assert row["extraction_attempts"] == 0
    assert row["extracted_facts_json"] is None
    assert row["category"] is None


# ---------------------------------------------------------------------------
# Critère 2 — run interrompu : les offres non traitées restent en attente, le
# run suivant les reprend sans les récupérer de leur source
# ---------------------------------------------------------------------------


class _CinqOffresSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return [
            _offer(i, fetched_at=datetime.now(timezone.utc) + timedelta(seconds=i))
            for i in range(1, 6)
        ]


def test_critere2_run_interrompu_laisse_le_reste_en_attente(
    db_path, profil, monkeypatch, tmp_path, fake_extract
):
    # EXE-99 : le /run appelle désormais `run_tri` (pas `extract_and_score`) pour
    # chaque offre en attente/à refaire — c'est ce point qu'on interrompt ici.
    real_run_tri = ingestion.run_tri
    progressed: list[int] = []

    def _crash_after_two(*args, **kwargs):
        progressed.append(1)
        if len(progressed) > 2:
            raise RuntimeError("coupure simulée")
        return real_run_tri(*args, **kwargs)

    monkeypatch.setattr(ingestion, "run_tri", _crash_after_two)

    with pytest.raises(RuntimeError):
        _run_main(monkeypatch, tmp_path, profil, _CinqOffresSource)

    ids = [_get_id(db_path, f"FT-{i}") for i in range(1, 6)]
    rows = [_row(db_path, i) for i in ids]
    done = [r for r in rows if r["extraction_status"] is None]
    pending = [r for r in rows if r["extraction_status"] == "pending"]
    assert len(done) == 2
    assert len(pending) == 3
    assert all(r["extraction_attempts"] == 0 for r in pending)

    # Le run suivant : la source rend les 5 mêmes offres (dédup → 0 nouvelle),
    # et pourtant les 3 restées en attente sont extraites.
    monkeypatch.setattr(ingestion, "run_tri", real_run_tri)
    _run_main(monkeypatch, tmp_path, profil, _CinqOffresSource)

    rows = [_row(db_path, i) for i in ids]
    assert all(r["extraction_status"] is None for r in rows)
    assert all(r["category"] is not None for r in rows)


# ---------------------------------------------------------------------------
# Critère 3 — extraction en échec : « à refaire » avec 1 essai, ni catégorie ni
# cause « sans techno »
# ---------------------------------------------------------------------------


def test_critere3_extraction_echoue_offre_a_refaire_1_essai(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    state["fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    outcome = ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h"
    )
    conn.close()

    assert outcome.extraction_status == "retry"
    assert outcome.extraction_attempts == 1

    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "retry"
    assert row["extraction_attempts"] == 1
    assert row["category"] is None
    assert row["hors_perimetre_reason"] is None
    assert row["perimetre_causes"] is None


# ---------------------------------------------------------------------------
# Critère 4 — relire une offre en attente ou à refaire ne rend aucun fait
# ---------------------------------------------------------------------------


def test_critere4_relire_offre_pending_ou_retry_ne_rend_aucun_fait(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pending = _offer(1)
    ingestion.register_offer(conn, pending, loaded_profile)

    retry = _offer(2)
    ingestion.register_offer(conn, retry, loaded_profile)
    state["fail"] = True
    ingestion.extract_and_score(
        conn, retry, loaded_profile, alias_table, model="m", host="h"
    )
    conn.close()

    detail_pending = api_offers.get_offer(_get_id(db_path, pending.source_id))
    detail_retry = api_offers.get_offer(_get_id(db_path, retry.source_id))
    assert detail_pending.extracted_facts is None
    assert detail_retry.extracted_facts is None


# ---------------------------------------------------------------------------
# Critère 5 — run sans offre nouvelle : le modèle est appelé pour les offres à
# refaire déjà en base
# ---------------------------------------------------------------------------


class _AucuneOffreSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return []


def test_critere5_run_appelle_le_modele_pour_les_offres_a_refaire(
    db_path, profil, alias_table, fake_extract, monkeypatch, tmp_path
):
    calls, state = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    profile, _ = load_profile(profil)
    offers = [
        _offer(i, fetched_at=datetime.now(timezone.utc) + timedelta(seconds=i))
        for i in range(1, 4)
    ]
    state["fail"] = True
    for o in offers:
        ingestion.register_offer(conn, o, profile)
        ingestion.extract_and_score(conn, o, profile, alias_table, model="m", host="h")
    conn.close()
    assert len(calls) == 3
    calls.clear()
    state["fail"] = False

    _run_main(monkeypatch, tmp_path, profil, _AucuneOffreSource)

    assert len(calls) == 3
    for o in offers:
        row = _row(db_path, _get_id(db_path, o.source_id))
        assert row["extraction_status"] is None
        assert row["category"] is not None


# ---------------------------------------------------------------------------
# Critère 6 — extraction réussie sur une offre à refaire : classée normalement
# ---------------------------------------------------------------------------


def test_critere6_extraction_reussit_sur_offre_a_refaire(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    state["fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h"
    )

    state["fail"] = False
    outcome = ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h", attempts_before=1
    )
    conn.close()

    assert outcome.extraction_status is None
    assert outcome.category is not None
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] is None
    assert row["category"] is not None


# ---------------------------------------------------------------------------
# Critère 7 — nouvel échec sur une offre à refaire : essais + 1
# ---------------------------------------------------------------------------


def test_critere7_echec_sur_offre_a_refaire_incremente_les_essais(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    state["fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)
    ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h", attempts_before=0
    )
    outcome2 = ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h", attempts_before=1
    )
    conn.close()

    assert outcome2.extraction_status == "retry"
    assert outcome2.extraction_attempts == 2


# ---------------------------------------------------------------------------
# Critère 8 — 3ᵉ échec : « illisible », plus jamais appelée par les runs suivants
# ---------------------------------------------------------------------------


def test_critere8_troisieme_echec_passe_illisible(
    db_path, loaded_profile, alias_table, fake_extract
):
    calls, state = fake_extract
    state["fail"] = True
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    outcome = ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h", attempts_before=2
    )
    conn.close()

    assert outcome.extraction_status == "unreadable"
    assert outcome.extraction_attempts == 3
    row = _row(db_path, _get_id(db_path, offer.source_id))
    assert row["extraction_status"] == "unreadable"

    calls.clear()
    conn2 = sqlite3.connect(db_path)
    reste_a_traiter = conn2.execute(
        "SELECT * FROM offers WHERE extraction_status IN ('pending', 'retry')"
    ).fetchall()
    conn2.close()
    assert reste_a_traiter == []


# ---------------------------------------------------------------------------
# Critère 9 — « sans techno » exclut en attente / à refaire / illisible
# ---------------------------------------------------------------------------


def test_critere9_sans_techno_exclut_en_cours_d_extraction(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sans_techno = _offer(1)
    state["facts"] = FACTS_OK.model_copy(update={"techs_required": []})
    ingestion.register_offer(conn, sans_techno, loaded_profile)
    ingestion.extract_and_score(
        conn, sans_techno, loaded_profile, alias_table, model="m", host="h"
    )

    state["facts"] = FACTS_OK
    pending = _offer(2)
    ingestion.register_offer(conn, pending, loaded_profile)

    retry = _offer(3)
    ingestion.register_offer(conn, retry, loaded_profile)
    state["fail"] = True
    ingestion.extract_and_score(
        conn, retry, loaded_profile, alias_table, model="m", host="h"
    )

    illisible = _offer(4)
    ingestion.register_offer(conn, illisible, loaded_profile)
    ingestion.extract_and_score(
        conn,
        illisible,
        loaded_profile,
        alias_table,
        model="m",
        host="h",
        attempts_before=2,
    )
    conn.close()

    rows = api_offers.list_offers(**{**_LIST_OFFERS_DEFAULTS, "hp_cause": "no_tech"})
    assert [r.id for r in rows] == [_get_id(db_path, sans_techno.source_id)]


# ---------------------------------------------------------------------------
# Critère 10 & 11 — filtres « Extraction en attente » et « Illisible »
# ---------------------------------------------------------------------------


def test_critere10_11_filtres_extraction_en_attente_et_illisible(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    pending = _offer(1)
    ingestion.register_offer(conn, pending, loaded_profile)

    retry = _offer(2)
    ingestion.register_offer(conn, retry, loaded_profile)
    state["fail"] = True
    ingestion.extract_and_score(
        conn, retry, loaded_profile, alias_table, model="m", host="h"
    )

    illisible = _offer(3)
    ingestion.register_offer(conn, illisible, loaded_profile)
    ingestion.extract_and_score(
        conn,
        illisible,
        loaded_profile,
        alias_table,
        model="m",
        host="h",
        attempts_before=2,
    )
    conn.close()

    rows = api_offers.list_offers(
        **{**_LIST_OFFERS_DEFAULTS, "extraction_status": "pending"}
    )
    par_id = {r.id: r for r in rows}
    assert set(par_id) == {
        _get_id(db_path, pending.source_id),
        _get_id(db_path, retry.source_id),
    }
    assert par_id[_get_id(db_path, pending.source_id)].extraction_attempts == 0
    assert par_id[_get_id(db_path, retry.source_id)].extraction_attempts == 1

    rows_illisibles = api_offers.list_offers(
        **{**_LIST_OFFERS_DEFAULTS, "extraction_status": "unreadable"}
    )
    assert [r.id for r in rows_illisibles] == [_get_id(db_path, illisible.source_id)]


# ---------------------------------------------------------------------------
# Critère 12 — extraction dégradée : comportement inchangé (scorée, classée)
# ---------------------------------------------------------------------------


def test_critere12_extraction_degradee_reste_scoree(
    db_path, loaded_profile, alias_table, fake_extract
):
    _, state = fake_extract
    state["facts"] = FACTS_OK.model_copy(update={"parse_failed": True})
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    offer = _offer(1)
    ingestion.register_offer(conn, offer, loaded_profile)

    outcome = ingestion.extract_and_score(
        conn, offer, loaded_profile, alias_table, model="m", host="h"
    )
    conn.close()

    assert outcome.extraction_status is None
    assert outcome.category is not None
    assert outcome.parse_failed is True


# ---------------------------------------------------------------------------
# Critères 13, 14, 15 — réparation des échecs historiques, idempotente, ciblée
# ---------------------------------------------------------------------------


def _insert_legacy_offer(
    conn,
    source_id,
    *,
    extracted_facts_json,
    extraction_version=None,
    hors_perimetre_reason=None,
    perimetre_causes=None,
) -> None:
    conn.execute(
        """
        INSERT INTO offers (source, source_id, fingerprint, title, filtered_out,
                             extracted_facts_json, extraction_version,
                             hors_perimetre_reason, perimetre_causes, fetched_at)
        VALUES ('france_travail', ?, ?, 'Titre', 0, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            f"fp-{source_id}",
            extracted_facts_json,
            extraction_version,
            hors_perimetre_reason,
            perimetre_causes,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def _by_source_id(path, source_id: str) -> sqlite3.Row:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM offers WHERE source_id = ?", (source_id,)
    ).fetchone()
    conn.close()
    return row


def test_critere13_14_15_reparation_des_echecs_historiques(tmp_path):
    path = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(path)
    # Schéma minimal pré-ticket (sans les colonnes extraction_status/attempts).
    conn.executescript("""
        CREATE TABLE offers (
            id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, fingerprint TEXT,
            title TEXT, filtered_out INTEGER NOT NULL DEFAULT 0,
            extracted_facts_json TEXT, extraction_version TEXT,
            hors_perimetre_reason TEXT, perimetre_causes TEXT,
            fetched_at TEXT, UNIQUE(source, source_id)
        );
    """)
    _insert_legacy_offer(
        conn,
        "ECHEC-1",
        extracted_facts_json=_LEGACY_FALLBACK_FACTS_JSON,
        hors_perimetre_reason="no_tech",
        perimetre_causes='["no_tech"]',
    )
    _insert_legacy_offer(
        conn,
        "DIFFERENT-1",
        extracted_facts_json=_LEGACY_FALLBACK_FACTS_JSON.replace(
            '"other"', '"backend"'
        ),
        hors_perimetre_reason="no_tech",
        perimetre_causes='["no_tech"]',
    )
    _insert_legacy_offer(
        conn,
        "VERSIONNEE-1",
        extracted_facts_json=_LEGACY_FALLBACK_FACTS_JSON,
        extraction_version="gemma4:12b|pXXXXXXXX|s1",
    )
    conn.close()

    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()

    r1 = _by_source_id(path, "ECHEC-1")
    assert r1["extraction_status"] == "retry"
    assert r1["extraction_attempts"] == 1
    assert r1["extracted_facts_json"] is None
    assert r1["hors_perimetre_reason"] is None
    assert r1["perimetre_causes"] is None

    r2 = _by_source_id(path, "DIFFERENT-1")
    assert r2["extraction_status"] is None
    assert r2["hors_perimetre_reason"] == "no_tech"

    r3 = _by_source_id(path, "VERSIONNEE-1")
    assert r3["extraction_status"] is None

    # Deuxième ouverture : idempotent, rien ne bouge plus.
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    r1_bis = _by_source_id(path, "ECHEC-1")
    assert r1_bis["extraction_attempts"] == 1
    assert r1_bis["extraction_status"] == "retry"


# ---------------------------------------------------------------------------
# Critère 16 — ajout à la main dont l'extraction échoue : « échec », à refaire
# ---------------------------------------------------------------------------


def test_critere16_ajout_dont_extraction_echoue_finit_en_echec(
    db_path, profil, fake_extract, monkeypatch
):
    _, state = fake_extract
    state["fail"] = True
    monkeypatch.setattr(ajout_service, "PROFILE_PATH", profil)

    conn = storage_db.get_connection()
    ajout_id = ajout_service.create_ajout(conn, None, "texte de l'offre collée")
    conn.close()

    source = manual.ManualSource(
        None,
        # EXE-115 : ≥ 50 caractères, sous ce seuil l'offre devient « texte manquant ».
        texte="Nous cherchons un développeur Python FastAPI, pour une équipe produit.",
        titre="Développeur Python",
        lieu="Strasbourg",
    )
    ajout_service.run_ajout(ajout_id, source)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ajout = conn.execute("SELECT * FROM ajouts WHERE id = ?", (ajout_id,)).fetchone()
    conn.close()

    assert ajout["statut"] == "echec"
    assert "refaire" in ajout["message"]
    assert ajout["offer_id"] is not None

    row = _row(db_path, ajout["offer_id"])
    assert row["extraction_status"] == "retry"
    assert row["extraction_attempts"] == 1


# ---------------------------------------------------------------------------
# Critère 17 — le rescore n'appelle jamais le modèle pour ces offres
# ---------------------------------------------------------------------------


def test_critere17_rescore_ne_touche_pas_les_offres_en_cours_d_extraction(
    db_path, profil, alias_table, fake_extract, monkeypatch, capsys, tmp_path
):
    _, state = fake_extract
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    profile, _ = load_profile(profil)

    pending = _offer(1)
    ingestion.register_offer(conn, pending, profile)

    retry = _offer(2)
    ingestion.register_offer(conn, retry, profile)
    state["fail"] = True
    ingestion.extract_and_score(conn, retry, profile, alias_table, model="m", host="h")

    illisible = _offer(3)
    ingestion.register_offer(conn, illisible, profile)
    ingestion.extract_and_score(
        conn, illisible, profile, alias_table, model="m", host="h", attempts_before=2
    )
    conn.close()

    def _boom(*args, **kwargs):
        raise AssertionError("extract_facts ne doit pas être appelé par le rescore")

    monkeypatch.setattr(extractor, "extract_facts", _boom)
    # rescore.py écrit data/unmatched_techs.txt sous REPO_ROOT — redirigé pour ne
    # rien écrire sous data/.
    monkeypatch.setattr(rescore, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setattr(sys, "argv", ["rescore", "--profile", str(profil)])

    rescore.main()

    out = capsys.readouterr().out
    assert "0 offres à scorer" in out

    for o in (pending, retry, illisible):
        row = _row(db_path, _get_id(db_path, o.source_id))
        assert row["category"] is None


# ---------------------------------------------------------------------------
# Critère 18 — la sortie du run dit combien d'offres sont en attente / à
# refaire / illisibles à la fin
# ---------------------------------------------------------------------------


class _TroisOffresSource:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def fetch(self) -> list[JobOffer]:
        return [
            _offer(i, fetched_at=datetime.now(timezone.utc) + timedelta(seconds=i))
            for i in range(1, 4)
        ]


def test_critere18_run_rapporte_les_comptes_finaux(
    db_path, profil, fake_extract, monkeypatch, tmp_path, capsys
):
    _, state = fake_extract
    state["fail"] = True

    _run_main(monkeypatch, tmp_path, profil, _TroisOffresSource)

    out = capsys.readouterr().out
    assert "0 en attente, 3 à refaire, 0 illisibles" in out
