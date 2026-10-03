"""Tests EXE-107 (TCK-221) — rejeu du jeu de référence sur un modèle nommé.

Aucun test n'appelle Ollama : `replay.extract_facts` / `replay.ensure_models_available`
/ `replay.unload_model` / `time.sleep` sont remplacés par des doubles qui
n'attendent ni ne parlent à un Ollama réel. Aucun test n'écrit dans le
mlflow.db du dépôt (fixture `_isolate_mlflow_tracking`, conftest.py) ni sous
data/ (jeu, rapports et profil pointent tmp_path).
"""

import copy
import time
from types import SimpleNamespace

import pytest
from mlflow.tracking import MlflowClient

import orchestrator.job_search.reference.replay as replay
import orchestrator.job_search.scoring.extractor as extractor
from orchestrator.job_search.matching.profile import (
    Profile,
    RoleCeiling,
    SearchCriteria,
    SkillEntry,
)
from orchestrator.job_search.reference.dataset import ReferenceEntry
from orchestrator.job_search.reference.replay import EXPERIMENT_NAME, replay_jeu
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.scoring.extractor import OllamaUnavailable
from orchestrator.job_search.sources.base import ExtractedFacts, TechRequirement

TRI_MODEL = "llama3-test"
PRECISION_MODEL = "gemma-test"

FACTS = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[TechRequirement(name="python", importance="core")],
    domain="backend",
)


def _profile() -> Profile:
    return Profile(
        profile_id="test",
        role_ceiling=RoleCeiling.ic,
        skills={"python": SkillEntry(level=8, desire=8)},
        search_criteria=SearchCriteria(
            keywords=["python"],
            domains=["backend"],
            locations=["remote"],
            contract_types=["cdi"],
        ),
    )


def _table() -> AliasTable:
    return AliasTable()


def _entry(relu: bool = True) -> ReferenceEntry:
    return ReferenceEntry(title="Offre", text="Texte", attendu=FACTS, relu=relu)


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def no_unload(monkeypatch):
    unloads: list[tuple[str, str]] = []
    monkeypatch.setattr(
        replay, "unload_model", lambda host, model: unloads.append((host, model))
    )
    return unloads


@pytest.fixture
def no_ollama_check(monkeypatch):
    monkeypatch.setattr(replay, "ensure_models_available", lambda *a, **k: None)


@pytest.fixture
def fake_extract(monkeypatch):
    calls: list[str] = []

    def _extract(offer, model, host):
        calls.append(offer.source_id)
        return FACTS

    monkeypatch.setattr(replay, "extract_facts", _extract)
    return calls


def _run(tmp_path, entries, model="model-x", **kwargs):
    return replay_jeu(
        entries,
        model,
        profile=_profile(),
        alias_table=_table(),
        reports_dir=tmp_path / "reports",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Critère 3 — seules les entrées relues sont extraites, le reste est compté
# ---------------------------------------------------------------------------


def test_critere3_seules_les_entrees_relues_sont_extraites(
    tmp_path, no_ollama_check, fake_extract
):
    entries = {"1": _entry(relu=True), "2": _entry(relu=False), "3": _entry(relu=True)}

    result = _run(tmp_path, entries)

    assert sorted(fake_extract) == ["1", "3"]
    assert result.n_skipped_non_relu == 1
    assert len(result.comparisons) == 2


# ---------------------------------------------------------------------------
# Critère 11 — rapport lisible, agrégats + détail par offre
# ---------------------------------------------------------------------------


def test_critere11_rapport_lisible_agregats_et_detail(
    tmp_path, no_ollama_check, fake_extract
):
    entries = {"1": _entry(relu=True)}

    result = _run(tmp_path, entries)

    assert result.report_path.exists()
    text = result.report_path.read_text(encoding="utf-8")
    assert "Agrégats" in text
    assert "Détail par offre" in text
    assert "1" in text  # identifiant de l'offre visible dans le détail


# ---------------------------------------------------------------------------
# Critère 12 — run MLflow sous l'expérience « reference »
# ---------------------------------------------------------------------------


def test_critere12_run_mlflow_sous_experience_reference(
    tmp_path, no_ollama_check, fake_extract
):
    entries = {"1": _entry(relu=True)}

    result = _run(tmp_path, entries, model="model-x")

    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1
    run_ = runs[0]
    assert run_.data.params["model"] == "model-x"
    assert run_.data.params["extraction_version"] == result.extraction_version
    assert run_.data.params["n_offres_rejouees"] == "1"
    assert run_.data.params["jeu_empreinte"] == result.jeu_fingerprint
    assert set(run_.data.metrics) == set(result.aggregates.as_dict())

    artifacts = client.list_artifacts(run_.info.run_id)
    assert [a.path for a in artifacts] == [result.report_path.name]


# ---------------------------------------------------------------------------
# Critère 14 — le rejeu du modèle de précision suit les lots et pauses de la
# pipeline ; un autre modèle nommé tourne sans lot ni pause
# ---------------------------------------------------------------------------


def test_critere14_modele_de_precision_suit_les_lots_et_pauses(
    monkeypatch, tmp_path, no_ollama_check, no_sleep, no_unload, fake_extract
):
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("SECOND_PASS_BATCH_SIZE", "2")
    monkeypatch.setenv("SECOND_PASS_PAUSE_SECONDS", "5")
    monkeypatch.setenv("SECOND_PASS_MAX_BATCHES", "10")
    entries = {str(i): _entry(relu=True) for i in range(5)}

    _run(tmp_path, entries, model=PRECISION_MODEL)

    assert no_sleep == [5.0, 5.0]  # 5 offres, lots de 2 → 3 lots, 2 pauses
    assert no_unload == [
        (replay._DEFAULT_HOST, PRECISION_MODEL),
        (replay._DEFAULT_HOST, PRECISION_MODEL),
    ]


def test_critere14_un_autre_modele_ne_batch_pas(
    monkeypatch, tmp_path, no_ollama_check, no_sleep, no_unload, fake_extract
):
    monkeypatch.setenv("OLLAMA_MODEL", PRECISION_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", TRI_MODEL)
    monkeypatch.setenv("SECOND_PASS_BATCH_SIZE", "2")
    monkeypatch.setenv("SECOND_PASS_PAUSE_SECONDS", "5")
    entries = {str(i): _entry(relu=True) for i in range(5)}

    _run(tmp_path, entries, model=TRI_MODEL)

    assert no_sleep == []
    assert no_unload == []


# ---------------------------------------------------------------------------
# Critère 15 — Ollama injoignable ou modèle absent : refuse de démarrer
# ---------------------------------------------------------------------------


def test_critere15_refuse_de_demarrer_si_ollama_injoignable(
    tmp_path, monkeypatch, fake_extract
):
    def _boom(host, models):
        raise OllamaUnavailable("Ollama injoignable (test)")

    monkeypatch.setattr(replay, "ensure_models_available", _boom)
    entries = {"1": _entry(relu=True)}

    with pytest.raises(OllamaUnavailable):
        _run(tmp_path, entries)

    assert fake_extract == []  # aucune extraction tentée


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — aucune écriture dans le fichier de traces du run
# ---------------------------------------------------------------------------


def test_rejeu_n_ecrit_rien_dans_le_fichier_de_traces_du_run(
    tmp_path, monkeypatch, no_ollama_check
):
    production_trace = tmp_path / "data" / "traces" / "extract_facts.jsonl"
    monkeypatch.setattr(extractor, "TRACE_PATH", production_trace)

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        def chat(self, *, model, messages, **kwargs):
            content = (
                '{"seniority_required": "intermediate", "techs_required": [], '
                '"domain": "backend", "role_level": "ic", "langues_requises": []}'
            )
            return SimpleNamespace(message=SimpleNamespace(content=content))

    monkeypatch.setattr("ollama.Client", _Client)
    entries = {"1": _entry(relu=True)}

    _run(tmp_path, entries)

    assert not production_trace.exists()
    assert extractor.TRACE_PATH == production_trace  # restaurée après l'appel


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — un rejeu ne modifie jamais le jeu
# ---------------------------------------------------------------------------


def test_rejeu_ne_modifie_jamais_le_jeu(tmp_path, no_ollama_check, fake_extract):
    entries = {"1": _entry(relu=True), "2": _entry(relu=False)}
    avant = copy.deepcopy(entries)

    _run(tmp_path, entries)

    assert entries == avant
