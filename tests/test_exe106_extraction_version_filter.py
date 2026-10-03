"""Tests EXE-106 — la page des traces se lit et se filtre par version d'extraction.

Aucun test ne lit ni n'écrit sous data/ : le fichier de traces et la base sont
tous les deux sous tmp_path (api.traces_reader._TRACES_PATH / api.db.DB_PATH
monkeypatchés). Le fichier de traces n'est jamais modifié, seulement lu
(traces_reader.read_traces_raw). Import local de api.traces après monkeypatch
de DB_PATH : le module connecte trace_notes à l'import (même convention que
test_cv_exe63.py) ; l'appel explicite à _ensure_trace_notes_table() dans la
fixture garantit la table même si api.traces a déjà été importé par un autre
test de la suite.
"""

import json
import sqlite3

import pytest

import api.db as api_db
import api.traces_reader as api_traces_reader
import orchestrator.job_search.storage.db as storage_db
from api.schemas import TraceNoteIn
from orchestrator.job_search.storage.db import init_db

VERSION_A = "llama3|pabcd1234|s1"
VERSION_B = "gemma4:12b|pef567890|s1"


def _raw(offer_id: str, timestamp: str, extraction_version: str | None = None) -> dict:
    raw = {
        "offer_id": offer_id,
        "model": "llama3",
        "temperature": 0.1,
        "timestamp": timestamp,
        "prompt_system": "sys",
        "prompt_user": "user",
        "raw_response": "{}",
        "parsed_facts": {},
        "parse_failed": False,
    }
    if extraction_version is not None:
        raw["extraction_version"] = extraction_version
    return raw


# 2 traces version A, 2 version B, 1 sans version — l'exemple du critère 4.
FIVE_TRACES = [
    _raw("o1", "2026-09-01T10:00:00Z", extraction_version=VERSION_A),
    _raw("o2", "2026-09-01T10:01:00Z", extraction_version=VERSION_A),
    _raw("o3", "2026-10-01T10:00:00Z", extraction_version=VERSION_B),
    _raw("o4", "2026-10-01T10:01:00Z", extraction_version=VERSION_B),
    _raw("o5", "2026-08-01T10:00:00Z"),  # antérieure à TCK-211 : pas de champ
]


def _write_traces(path, raws: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for raw in raws:
            fh.write(json.dumps(raw) + "\n")


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
def traces_path(tmp_path, monkeypatch):
    path = tmp_path / "traces" / "extract_facts.jsonl"
    monkeypatch.setattr(api_traces_reader, "_TRACES_PATH", path)
    return path


@pytest.fixture
def api_traces(db_path):
    """Import local de api.traces (connecte trace_notes au DB_PATH monkeypatché)."""
    import api.traces as _api_traces

    _api_traces._ensure_trace_notes_table()
    return _api_traces


class TestCritere1ChaqueTracePorteSaVersion:
    def test_trace_avec_version_la_porte(self, traces_path, api_traces):
        _write_traces(traces_path, [FIVE_TRACES[0]])

        out = api_traces.list_traces()

        assert out[0].extraction_version == VERSION_A


class TestCritere2TraceAncienneSansVersionDevinee:
    def test_trace_sans_champ_rendue_sans_version(self, traces_path, api_traces):
        _write_traces(traces_path, [FIVE_TRACES[4]])

        out = api_traces.list_traces()

        assert out[0].extraction_version is None


class TestCritere3ListeDesVersionsAvecComptage:
    def test_versions_comptees_sans_version_comprise(self, traces_path, api_traces):
        _write_traces(traces_path, FIVE_TRACES)

        out = api_traces.get_traces_versions()

        counts = {v.version: v.count for v in out}
        assert counts == {VERSION_A: 2, VERSION_B: 2, None: 1}


class TestCritere4FiltreParVersion:
    def test_demande_version_a_rend_2_traces(self, traces_path, api_traces):
        _write_traces(traces_path, FIVE_TRACES)

        out = api_traces.list_traces(version=VERSION_A)

        assert len(out) == 2
        assert {t.offer_id for t in out} == {"o1", "o2"}
        assert all(t.extraction_version == VERSION_A for t in out)


class TestCritere5FiltreSansVersion:
    def test_demande_sans_version_rend_1_trace(self, traces_path, api_traces):
        _write_traces(traces_path, FIVE_TRACES)

        out = api_traces.list_traces(sans_version=True)

        assert len(out) == 1
        assert out[0].offer_id == "o5"
        assert out[0].extraction_version is None


class TestCritere6SansFiltreRendTout:
    def test_sans_filtre_rend_les_5_traces_comme_avant(self, traces_path, api_traces):
        _write_traces(traces_path, FIVE_TRACES)

        out = api_traces.list_traces()

        assert len(out) == 5


class TestCritere7NotesSurviventAuFiltre:
    def test_note_reste_visible_filtree_ou_non(self, traces_path, api_traces):
        _write_traces(traces_path, FIVE_TRACES)
        trace_key = f"{FIVE_TRACES[0]['offer_id']}::{FIVE_TRACES[0]['timestamp']}"

        api_traces.upsert_trace_note(
            trace_key,
            TraceNoteIn(note="observation", cause="ok", severite="mineure"),
        )

        filtree = api_traces.list_traces(version=VERSION_A)
        trace_filtree = next(t for t in filtree if t.trace_key == trace_key)
        assert trace_filtree.note == "observation"
        assert trace_filtree.cause == "ok"
        assert trace_filtree.severite == "mineure"

        toutes = api_traces.list_traces()
        trace_toutes = next(t for t in toutes if t.trace_key == trace_key)
        assert trace_toutes.note == "observation"
