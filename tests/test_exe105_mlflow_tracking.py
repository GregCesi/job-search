"""Tests EXE-105 — chaque run de la pipeline est suivi dans MLflow : réglages,
volumes, échecs et durées (critères 1 à 9).

Aucun test n'appelle Ollama : `ingestion.extract_facts` est remplacé par un
double contrôlable (`cascade`, repris de test_exe100_gemma_lots.py), et
`extractor.unload_model` / `time.sleep` par des doubles qui n'attendent ni ne
parlent à un Ollama réel. Aucun test n'écrit dans le mlflow.db du dépôt : la
fixture `_isolate_mlflow_tracking` de conftest.py pointe chaque test vers un
SQLite temporaire. Aucun test ne lit ni n'écrit sous data/.
"""

import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import mlflow
import pytest
from mlflow.tracking import MlflowClient

import api.db as api_db
import orchestrator.job_search.ingestion as ingestion
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.scoring.extractor import extraction_version
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    JobOffer,
    RoleLevel,
    TechRequirement,
)
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.tracking.mlflow_tracking import EXPERIMENT_NAME

REPO = Path(__file__).resolve().parent.parent

TRI_MODEL = "llama3-test"
PRECISION_MODEL = "gemma-test"

FACTS_PARFAIT = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="git", importance="required"),
    ],
    domain="ai_engineering",
    role_level="ic",
)

FACTS_ATTEIGNABLE = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[
        TechRequirement(name="python", importance="core"),
        TechRequirement(name="fastapi", importance="required"),
    ],
    domain="backend",
)

FACTS_MANAGER = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[TechRequirement(name="python", importance="core")],
    domain="backend",
    role_level=RoleLevel.manager,
)


# ---------------------------------------------------------------------------
# Fixtures (reprises de test_exe100_gemma_lots.py)
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
def no_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    return sleeps


@pytest.fixture
def no_unload(monkeypatch):
    unloads: list[tuple[str, str]] = []
    monkeypatch.setattr(
        extractor, "unload_model", lambda host, model: unloads.append((host, model))
    )
    return unloads


@pytest.fixture
def cascade(monkeypatch):
    state = {
        "tri": {},
        "precision": {},
        "tri_facts": FACTS_ATTEIGNABLE,
        "precision_facts": FACTS_ATTEIGNABLE,
    }

    def _extract(offer, model, host):
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
    return state


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


def _single_run():
    """Le run MLflow unique écrit par le test courant, sous `run-pipeline`."""
    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert experiment is not None, "aucune expérience run-pipeline"
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 1, f"attendu un seul run, trouvé {len(runs)}"
    return runs[0]


# ---------------------------------------------------------------------------
# Scénario principal — 63 offres, réglages par défaut (repris de
# test_exe100_gemma_lots.py::test_critere10_15) : 5 lots, plafond atteint,
# 50 relues finalisées « atteignable » (faits de précision), 13 encore en
# attente de seconde passe. Sert les critères 1, 2, 3, 4, 5, 6, 8.
# ---------------------------------------------------------------------------


def test_critere1_le_run_est_range_sous_l_experience_run_pipeline(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    _run_main(monkeypatch, tmp_path, profil, [])
    run_ = _single_run()
    assert run_.info.status == "FINISHED"


def test_critere2_parametres_du_run(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    _run_main(monkeypatch, tmp_path, profil, [])
    params = _single_run().data.params
    assert params["tri_model"] == TRI_MODEL
    assert params["precision_model"] == PRECISION_MODEL
    assert params["tri_extraction_version"] == extraction_version(TRI_MODEL)
    assert params["precision_extraction_version"] == extraction_version(PRECISION_MODEL)
    assert params["batch_size"] == "10"
    assert params["pause_seconds"] == "300.0"
    assert params["max_batches"] == "5"


def test_criteres_3_4_5_6_8_volumes_categories_echecs_durees_et_arret(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path, capsys
):
    state = cascade
    state["tri_facts"] = FACTS_PARFAIT  # déclenche systématiquement la seconde passe
    monkeypatch.delenv("SECOND_PASS_BATCH_SIZE", raising=False)
    monkeypatch.delenv("SECOND_PASS_PAUSE_SECONDS", raising=False)
    monkeypatch.delenv("SECOND_PASS_MAX_BATCHES", raising=False)

    offers = [_offer(i) for i in range(1, 64)]  # 63 offres
    _run_main(monkeypatch, tmp_path, profil, offers)

    out = capsys.readouterr().out
    assert "63 offres triées, 50 relues, 13 en attente de seconde passe" in out
    assert "plafond de lots atteint" in out

    run_ = _single_run()
    metrics = run_.data.metrics
    params = run_.data.params

    # Critère 3 — volumes. Récupérées = 126 : le profil exemple déclare 2 zones
    # avec code INSEE (strasbourg_area, paris_area) → 2 FranceTravailSource,
    # chacune renvoyant les 63 offres (guard intra-batch de la dédup, pipeline.md
    # étage 2) ; nouvelles = 63, les 63 autres sont les doublons du même fetch.
    assert metrics["offres_recuperees"] == 126.0
    assert metrics["offres_nouvelles"] == 63.0
    assert metrics["offres_filtrees"] == 0.0
    assert metrics["offres_triees"] == 63.0
    assert metrics["offres_relues"] == 50.0
    assert metrics["offres_en_attente_extraction"] == 0.0
    assert metrics["offres_a_refaire"] == 0.0
    assert metrics["offres_illisibles"] == 0.0
    assert metrics["offres_en_attente_seconde_passe"] == 13.0

    # Critère 4 — les 50 relues sont finalisées avec les faits de précision
    # (FACTS_ATTEIGNABLE, défaut de `cascade`) : catégorie « atteignable ».
    # Les 13 non traitées n'ont ni catégorie ni cause hors-périmètre.
    assert metrics["categorie_atteignable"] == 50.0
    assert metrics["categorie_parfait"] == 0.0
    assert metrics["categorie_reve"] == 0.0
    assert metrics["categorie_hors"] == 0.0
    assert metrics["offres_hors_perimetre"] == 0.0

    # Critère 5 — aucun échec (cascade "ok" partout), une durée médiane par
    # modèle, non négative (elle n'a pas de sens précis sur un double mocké).
    assert metrics["tri_extractions_echouees"] == 0.0
    assert metrics["precision_extractions_echouees"] == 0.0
    assert metrics["tri_duree_mediane_s"] >= 0.0
    assert metrics["precision_duree_mediane_s"] >= 0.0

    # Critère 6 — durées, en secondes. 4 pauses à 300s (5 lots, défaut) : la
    # valeur nominale s'accumule même si `time.sleep` est doublé (`no_sleep`),
    # donc indépendante du temps mur réel du test, lui proche de zéro.
    assert metrics["duree_pauses_s"] == 1200.0
    assert metrics["duree_run_s"] >= 0.0
    assert metrics["duree_tri_s"] >= 0.0
    assert metrics["duree_seconde_passe_s"] >= 0.0

    # Critère 8 — le run s'arrête sur le plafond, la raison est portée.
    assert params["stop_reason"] == "cap"


# ---------------------------------------------------------------------------
# Critère 4 (bis) — hors périmètre (TechRequirement manager → mgmt_role)
# ---------------------------------------------------------------------------


def test_critere4_offres_hors_perimetre(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    state = cascade
    state["tri_facts"] = FACTS_MANAGER  # role_ceiling=ic (profil example) → mgmt_role

    offers = [_offer(i) for i in range(1, 4)]
    _run_main(monkeypatch, tmp_path, profil, offers)

    metrics = _single_run().data.metrics
    assert metrics["offres_hors_perimetre"] == 3.0
    assert metrics["categorie_parfait"] == 0.0
    assert metrics["categorie_reve"] == 0.0
    assert metrics["categorie_atteignable"] == 0.0
    assert metrics["categorie_hors"] == 0.0


# ---------------------------------------------------------------------------
# Critère 3 (bis) — offres écartées par les filtres durs
# ---------------------------------------------------------------------------


def test_critere3_offres_filtrees(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    offers = [_offer(1, alternance=True), _offer(2)]
    _run_main(monkeypatch, tmp_path, profil, offers)

    metrics = _single_run().data.metrics
    # 2 zones avec code INSEE dans le profil exemple → chaque offre est
    # récupérée 2 fois (2 FranceTravailSource), dédupliquée à 1 (pipeline.md
    # étage 2, guard intra-batch).
    assert metrics["offres_recuperees"] == 4.0
    assert metrics["offres_nouvelles"] == 2.0
    assert metrics["offres_filtrees"] == 1.0


# ---------------------------------------------------------------------------
# Critère 5 (bis) — extractions échouées (illisible, puis sans réponse)
# ---------------------------------------------------------------------------


def test_critere5_extractions_echouees_par_modele(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    state = cascade
    state["tri"]["FT-1"] = "illisible"
    state["tri"]["FT-2"] = "illisible"
    state["precision"]["FT-1"] = "illisible"
    state["precision"]["FT-2"] = "illisible"

    offers = [_offer(1), _offer(2), _offer(3)]
    _run_main(monkeypatch, tmp_path, profil, offers)

    metrics = _single_run().data.metrics
    # FT-1 et FT-2 : illisibles au tri (unreadable=True, no_response=False),
    # relus en seconde passe avec le modèle de précision, illisibles aussi →
    # 2 échecs par modèle. FT-3 : « ok » partout, aucun échec.
    assert metrics["tri_extractions_echouees"] == 2.0
    assert metrics["precision_extractions_echouees"] == 2.0


# ---------------------------------------------------------------------------
# Critère 7 — le digest est attaché comme artefact, identique octet pour octet
# ---------------------------------------------------------------------------


def test_critere7_digest_attache_comme_artefact_identique(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    _run_main(monkeypatch, tmp_path, profil, [])

    digest_files = list((tmp_path / "data").glob("digest_*.txt"))
    assert len(digest_files) == 1
    digest_bytes = digest_files[0].read_bytes()

    run_ = _single_run()
    client = MlflowClient()
    artifacts = client.list_artifacts(run_.info.run_id)
    assert [a.path for a in artifacts] == [digest_files[0].name]

    downloaded = mlflow.artifacts.download_artifacts(
        run_id=run_.info.run_id,
        artifact_path=artifacts[0].path,
        dst_path=str(tmp_path / "dl"),
    )
    assert Path(downloaded).read_bytes() == digest_bytes


# ---------------------------------------------------------------------------
# Critère 8 (bis) — arrêt sur absence de réponse du modèle
# ---------------------------------------------------------------------------


def test_critere8_arret_sur_absence_de_reponse(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    state = cascade
    state["tri_facts"] = FACTS_PARFAIT
    for i in range(1, 4):
        state["precision"][f"FT-{i}"] = "no_response"

    offers = [_offer(i) for i in range(1, 11)]
    _run_main(monkeypatch, tmp_path, profil, offers)

    params = _single_run().data.params
    assert params["stop_reason"] == "no_response"


# ---------------------------------------------------------------------------
# Critère 8 (ter) — arrêt sur une erreur : le run MLflow existe quand même
# ---------------------------------------------------------------------------


def test_critere8_arret_sur_erreur(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path
):
    import orchestrator.job_search.sources.france_travail as ft

    class _Boom:
        def __init__(self, *a, **k) -> None:
            pass

        def fetch(self):
            raise RuntimeError("coupure simulée")

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

    with pytest.raises(RuntimeError):
        run.main()

    run_ = _single_run()
    assert run_.data.params["stop_reason"] == "erreur"
    assert run_.data.metrics["offres_recuperees"] == 0.0


# ---------------------------------------------------------------------------
# Critère 9 — MLflow ne peut pas écrire : le run de la pipeline va au bout
# ---------------------------------------------------------------------------


def test_critere9_le_run_va_au_bout_si_mlflow_ne_peut_pas_ecrire(
    monkeypatch, db_path, profil, cascade, no_sleep, no_unload, tmp_path, capsys
):
    monkeypatch.setattr(
        mlflow,
        "start_run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stockage verrouillé")),
    )

    offers = [_offer(1)]
    _run_main(monkeypatch, tmp_path, profil, offers)  # ne lève pas

    out = capsys.readouterr().out
    assert "suivi MLflow a échoué" in out

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM offers WHERE source_id = 'FT-1'").fetchone()
    conn.close()
    assert row is not None
    assert row["category"] == "atteignable"  # cascade par défaut : FACTS_ATTEIGNABLE

    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert experiment is None or client.search_runs([experiment.experiment_id]) == []
