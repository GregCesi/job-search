"""Tests EXE-100 — gemma4:12b (modèle de précision) tourne par lots en seconde
passe, avec pause entre deux lots, plafond de lots, arrêt sur absence de
réponse du modèle (tri et seconde passe), et déchargement des deux modèles en
fin de run (normal, erreur, ou interruption au clavier).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un
double contrôlable par offre (`cascade`), et `extractor.unload_model` /
`time.sleep` sont remplacés par des doubles qui n'attendent ni ne parlent à un
Ollama réel. Aucun test ne lit ni n'écrit sous data/.
"""

import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.db as api_db
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
def no_sleep(monkeypatch):
    """Aucun test n'attend réellement la durée d'une pause : `time.sleep` est
    remplacé par un double qui enregistre ses appels sans dormir."""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def no_unload(monkeypatch):
    """Aucun test ne parle à un Ollama réel pour décharger un modèle."""
    unloads: list[tuple[str, str]] = []
    monkeypatch.setattr(
        extractor, "unload_model", lambda host, model: unloads.append((host, model))
    )
    return unloads


@pytest.fixture
def cascade(monkeypatch):
    """Double de `ingestion.extract_facts`, contrôlable par offre et par rôle
    de modèle (tri/précision) : `state["tri"][source_id]` et
    `state["precision"][source_id]` valent "ok" (→ `state["*_facts"]`),
    "illisible" (→ None, sans lever) ou "no_response" (→ lève
    `extractor.NoResponseFromModel`, EXE-100 critères 11/13). Par défaut
    (offre absente des deux dicts) : "ok"."""
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
# `_second_pass_batches` en isolation — mécanique des lots/pauses/plafond
# (critères 1, 2, 4, 9, 10, 13, 15), sans toucher à la base ni à Ollama.
# ---------------------------------------------------------------------------


def _entry(n: int, no_response_after: int | None = None):
    return SimpleNamespace(
        offer=SimpleNamespace(title=f"Offre seconde passe {n}"),
        kind="category",
        category=None,
        attempts_before=0,
    )


def _make_resolver(outcomes: list[bool]):
    """`outcomes[i]` = True si l'entrée i doit renvoyer `no_response=True`."""
    calls: list[int] = []

    def _resolve(conn, entry, profile, alias_table, *, model, host):
        i = len(calls)
        calls.append(i)
        no_response = outcomes[i] if i < len(outcomes) else False
        return SimpleNamespace(
            no_response=no_response,
            extraction_status="second_pass_pending",
            second_pass_attempts=0,
            extraction_attempts=0,
            category=None,
        )

    return _resolve, calls


def test_critere1_2_vingt_trois_offres_trois_lots_deux_pauses(
    monkeypatch, no_sleep, no_unload
):
    resolver, calls = _make_resolver([False] * 23)
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)
    queue = [_entry(i) for i in range(23)]

    report = run._second_pass_batches(
        None,
        queue,
        None,
        None,
        tri_model="tri",
        precision_model="prec",
        host="h",
        batch_size=10,
        pause_seconds=300,
        max_batches=5,
    )

    assert len(calls) == 23
    assert report.n_relues == 23
    assert report.batches_done == 3
    assert no_sleep == [300, 300]
    assert report.pause_seconds_total == 600
    assert report.stop_reason is None


def test_critere4_taille_de_lot_configurable(monkeypatch, no_sleep, no_unload):
    resolver, calls = _make_resolver([False] * 7)
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)
    queue = [_entry(i) for i in range(7)]

    report = run._second_pass_batches(
        None,
        queue,
        None,
        None,
        tri_model="tri",
        precision_model="prec",
        host="h",
        batch_size=3,
        pause_seconds=1,
        max_batches=10,
    )

    assert report.batches_done == 3  # 3, 3, 1
    assert len(no_sleep) == 2


def test_critere9_10_plafond_de_lots_configurable(monkeypatch, no_sleep, no_unload):
    resolver, calls = _make_resolver([False] * 23)
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)
    queue = [_entry(i) for i in range(23)]

    report = run._second_pass_batches(
        None,
        queue,
        None,
        None,
        tri_model="tri",
        precision_model="prec",
        host="h",
        batch_size=10,
        pause_seconds=1,
        max_batches=2,
    )

    assert len(calls) == 20
    assert report.batches_done == 2
    assert report.stop_reason == "cap"


def test_critere5_decharge_le_modele_de_tri_avant_le_premier_lot(
    monkeypatch, no_sleep, no_unload
):
    resolver, calls = _make_resolver([])
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)

    run._second_pass_batches(
        None,
        [],
        None,
        None,
        tri_model="tri-x",
        precision_model="prec-x",
        host="h",
        batch_size=10,
        pause_seconds=1,
        max_batches=5,
    )

    assert no_unload == [("h", "tri-x")]


def test_critere6_decharge_le_modele_de_precision_a_chaque_pause(
    monkeypatch, no_sleep, no_unload
):
    resolver, calls = _make_resolver([False] * 15)
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)
    queue = [_entry(i) for i in range(15)]

    run._second_pass_batches(
        None,
        queue,
        None,
        None,
        tri_model="tri-x",
        precision_model="prec-x",
        host="h",
        batch_size=10,
        pause_seconds=1,
        max_batches=5,
    )

    assert no_unload == [("h", "tri-x"), ("h", "prec-x")]


def test_critere13_trois_offres_sans_reponse_de_suite_arrete_la_seconde_passe(
    monkeypatch, no_sleep, no_unload
):
    resolver, calls = _make_resolver(
        [False, True, True, True, False, False, False, False, False, False]
    )
    monkeypatch.setattr(run, "_resolve_second_pass_entry", resolver)
    queue = [_entry(i) for i in range(10)]

    report = run._second_pass_batches(
        None,
        queue,
        None,
        None,
        tri_model="tri",
        precision_model="prec",
        host="h",
        batch_size=10,
        pause_seconds=1,
        max_batches=5,
    )

    # Offre 0 (ok), puis 1,2,3 (3 sans réponse de suite) → arrêt.
    assert len(calls) == 4
    assert report.stop_reason == "no_response"


# ---------------------------------------------------------------------------
# `_tri_phase` en isolation — critères 11, 12, 14
# ---------------------------------------------------------------------------


def _tri_outcome(
    no_response=False, needs_second_pass=False, reason=None, category=None
):
    return SimpleNamespace(
        no_response=no_response,
        needs_second_pass=needs_second_pass,
        second_pass_reason=reason,
        outcome=SimpleNamespace(
            category=category, perimetre_causes=[], extraction_status=None
        ),
    )


def test_critere11_12_trois_offres_sans_reponse_de_suite_arrete_le_tri(
    monkeypatch, db_path, loaded_profile, alias_table
):
    offers = [_offer(i) for i in range(1, 7)]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for o in offers:
        ingestion.register_offer(conn, o, loaded_profile)
    rows = conn.execute("SELECT * FROM offers ORDER BY fetched_at").fetchall()

    calls: list[str] = []

    def _run_tri(conn, offer, profile, alias_table, *, model, host):
        calls.append(offer.source_id)
        # Les 3 premières offres n'obtiennent aucune réponse → arrêt du tri.
        if len(calls) <= 3:
            return _tri_outcome(
                no_response=True, needs_second_pass=True, reason="unreadable"
            )
        return _tri_outcome(category=Category.atteignable)

    monkeypatch.setattr(ingestion, "run_tri", _run_tri)

    report = run._tri_phase(
        conn, rows, loaded_profile, alias_table, tri_model=TRI_MODEL, host="h"
    )
    conn.close()

    assert len(calls) == 3
    assert report.stopped_no_response is True
    assert report.a_relire_non_lues == []  # critère 12 : aucun essai pour les 3

    for o in offers:
        row = _row(db_path, _get_id(db_path, o.source_id))
        assert row["extraction_attempts"] == 0
        assert row["extraction_status"] == "pending"


def test_critere14_reponse_illisible_non_vide_ne_compte_pas_dans_la_serie(
    monkeypatch, db_path, loaded_profile, alias_table
):
    offers = [_offer(i) for i in range(1, 5)]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    for o in offers:
        ingestion.register_offer(conn, o, loaded_profile)
    rows = conn.execute("SELECT * FROM offers ORDER BY fetched_at").fetchall()

    calls: list[str] = []

    def _run_tri(conn, offer, profile, alias_table, *, model, host):
        calls.append(offer.source_id)
        n = len(calls)
        if n in (1, 2):
            return _tri_outcome(
                no_response=True, needs_second_pass=True, reason="unreadable"
            )
        if n == 3:
            # Illisible mais non vide : ne compte pas dans la série (critère 14).
            return _tri_outcome(
                no_response=False, needs_second_pass=True, reason="unreadable"
            )
        return _tri_outcome(category=Category.atteignable)

    monkeypatch.setattr(ingestion, "run_tri", _run_tri)

    report = run._tri_phase(
        conn, rows, loaded_profile, alias_table, tri_model=TRI_MODEL, host="h"
    )
    conn.close()

    assert len(calls) == 4
    assert report.stopped_no_response is False
    # Les offres 1, 2 (sans réponse mais la série est rompue par l'offre 3) et
    # l'offre 3 (illisible) rejoignent toutes la file de seconde passe.
    assert {o.source_id for o, _ in report.a_relire_non_lues} == {
        offers[0].source_id,
        offers[1].source_id,
        offers[2].source_id,
    }


# ---------------------------------------------------------------------------
# Déchargement en fin de run — critères 7, 8
# ---------------------------------------------------------------------------


def test_critere7_decharge_les_deux_modeles_a_la_fin_d_un_run_normal(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    _run_main(monkeypatch, tmp_path, profil, [])

    assert no_unload[-2:] == [
        ("http://localhost:11434", TRI_MODEL),
        ("http://localhost:11434", PRECISION_MODEL),
    ]


@pytest.mark.parametrize("exc_cls", [RuntimeError, KeyboardInterrupt])
def test_critere8_decharge_les_deux_modeles_sur_erreur_ou_interruption(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path, exc_cls
):
    class _Boom:
        def __init__(self, *a, **k) -> None:
            pass

        def fetch(self):
            raise exc_cls("coupure simulée")

    import orchestrator.job_search.sources.france_travail as ft

    monkeypatch.setattr(ft, "FranceTravailSource", _Boom)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)
    monkeypatch.setattr(
        sys,
        "argv",
        ["run", "--profile", str(profil), "--no-remotive", "--no-indeed", "--no-eures"],
    )

    with pytest.raises(exc_cls):
        run.main()

    assert no_unload[-2:] == [
        ("http://localhost:11434", TRI_MODEL),
        ("http://localhost:11434", PRECISION_MODEL),
    ]


# ---------------------------------------------------------------------------
# Intégration — critères 3 (pause configurable), 9 (plafond configurable),
# 10 (63 offres, réglages par défaut), 15 (sortie du run)
# ---------------------------------------------------------------------------


def test_critere3_9_pause_et_plafond_configurables(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path, capsys
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    monkeypatch.setenv("SECOND_PASS_BATCH_SIZE", "4")
    monkeypatch.setenv("SECOND_PASS_PAUSE_SECONDS", "7")
    monkeypatch.setenv("SECOND_PASS_MAX_BATCHES", "2")

    offers = [_offer(i) for i in range(1, 11)]  # 10 offres → parfait → seconde passe
    _run_main(monkeypatch, tmp_path, profil, offers)

    assert no_sleep == [7]  # 1 pause entre les 2 lots du plafond
    out = capsys.readouterr().out
    assert "2 lots" in out
    assert "plafond de lots atteint" in out


def test_critere10_15_soixante_trois_offres_reglages_par_defaut(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path, capsys
):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    monkeypatch.delenv("SECOND_PASS_BATCH_SIZE", raising=False)
    monkeypatch.delenv("SECOND_PASS_PAUSE_SECONDS", raising=False)
    monkeypatch.delenv("SECOND_PASS_MAX_BATCHES", raising=False)

    offers = [_offer(i) for i in range(1, 64)]  # 63 offres
    _run_main(monkeypatch, tmp_path, profil, offers)

    out = capsys.readouterr().out
    assert "63 offres triées, 50 relues, 13 en attente de seconde passe" in out
    assert "5 lots" in out
    assert "plafond de lots atteint" in out
    assert no_sleep == [300.0] * 4  # 5 lots → 4 pauses, défaut 5 min


# ---------------------------------------------------------------------------
# Critère 16 — un ajout à la main ne marque aucune pause
# ---------------------------------------------------------------------------


def test_critere16_ajout_ne_marque_aucune_pause(monkeypatch, db_path, profil, cascade):
    calls, state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    monkeypatch.setattr(ajout_service, "PROFILE_PATH", profil)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)

    def _boom(seconds):
        raise AssertionError("un ajout à la main ne doit jamais dormir")

    monkeypatch.setattr(time, "sleep", _boom)

    conn = storage_db.get_connection()
    ajout_id = ajout_service.create_ajout(conn, None, "texte de l'offre collée")
    conn.close()

    source = manual.ManualSource(
        None,
        # EXE-115 : ≥ 50 caractères, sous ce seuil l'offre devient « texte manquant ».
        texte="Nous cherchons un profil pour une équipe produit à Strasbourg.",
        titre="Développeur",
        lieu="Strasbourg",
    )
    ajout_service.run_ajout(ajout_id, source)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ajout = conn.execute("SELECT * FROM ajouts WHERE id = ?", (ajout_id,)).fetchone()
    conn.close()
    assert ajout["statut"] == "termine"
