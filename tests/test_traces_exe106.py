"""Tests EXE-106 — la page des traces se lit et se filtre par version d'extraction.

Couvre les critères 1 à 7 du ticket. Aucun test ne lit ni n'écrit sous data/ :
le fichier de traces est un tmp_path (monkeypatché dans api.traces_reader,
comme db_path monkeypatche la DB dans test_expiration_exe76.py). Le fichier de
traces n'est jamais écrit par le code testé, seulement par le test (il simule
le JSONL produit par l'orchestrator).
"""

import json
import sqlite3

import pytest

import api.db as api_db
import api.traces as api_traces
import api.traces_reader as api_traces_reader
import orchestrator.job_search.storage.db as storage_db
from api.schemas import NO_VERSION_LABEL, TraceNoteIn
from orchestrator.job_search.storage.db import init_db

VERSION_A = "llama3.1:8b|pa1b2c3d4|s1"
VERSION_B = "gemma3:12b|pz9z9z9z9|s1"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


def _raw_trace(offer_id, timestamp, extraction_version="__absent__", model="llama3.1:8b"):
    trace = {
        "offer_id": offer_id,
        "model": model,
        "temperature": 0.1,
        "prompt_system": "sys",
        "prompt_user": "user",
        "raw_response": "{}",
        "parsed_facts": {},
        "parse_failed": False,
        "timestamp": timestamp,
    }
    if extraction_version != "__absent__":
        trace["extraction_version"] = extraction_version
    return trace


@pytest.fixture
def traces_path(tmp_path, monkeypatch):
    """5 traces : 2 version A, 2 version B, 1 sans version (champ absent, comme
    une trace écrite avant TCK-211)."""
    path = tmp_path / "extract_facts.jsonl"
    rows = [
        _raw_trace("o1", "2026-10-01T10:00:00", VERSION_A),
        _raw_trace("o1", "2026-10-01T10:05:00", VERSION_A),
        _raw_trace("o2", "2026-10-01T11:00:00", VERSION_B),
        _raw_trace("o2", "2026-10-01T11:05:00", VERSION_B),
        _raw_trace("o3", "2026-09-01T09:00:00", extraction_version="__absent__"),
    ]
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    monkeypatch.setattr(api_traces_reader, "_TRACES_PATH", path)
    return path


def test_chaque_trace_porte_sa_version(db_path, traces_path):
    """Critère 1 : chaque trace rendue par l'API porte sa version d'extraction."""
    traces = api_traces.list_traces(version=None)
    by_key = {t.trace_key: t.extraction_version for t in traces}
    assert by_key["o1::2026-10-01T10:00:00"] == VERSION_A
    assert by_key["o2::2026-10-01T11:00:00"] == VERSION_B


def test_trace_sans_version_jamais_devinee(db_path, traces_path):
    """Critère 2 : une trace écrite avant les versions est rendue sans version,
    jamais avec une version devinée."""
    traces = api_traces.list_traces(version=None)
    o3 = next(t for t in traces if t.offer_id == "o3")
    assert o3.extraction_version is None


def test_liste_des_versions_avec_leur_nombre(db_path, traces_path):
    """Critère 3 : l'API rend la liste des versions présentes, chacune avec son
    nombre de traces, sans version comprise."""
    versions = api_traces.get_traces_versions()
    counts = {v.version: v.count for v in versions}
    assert counts == {VERSION_A: 2, VERSION_B: 2, NO_VERSION_LABEL: 1}


def test_filtre_sur_une_version(db_path, traces_path):
    """Critère 4 : sur 5 traces dont 2 de la version A, 2 de la version B et 1
    sans version, la demande de la version A en rend 2."""
    traces = api_traces.list_traces(version=VERSION_A)
    assert len(traces) == 2
    assert all(t.extraction_version == VERSION_A for t in traces)


def test_filtre_sans_version(db_path, traces_path):
    """Critère 5 : je demande les traces sans version, l'API ne rend que celles-là."""
    traces = api_traces.list_traces(version=NO_VERSION_LABEL)
    assert len(traces) == 1
    assert traces[0].offer_id == "o3"
    assert traces[0].extraction_version is None


def test_sans_filtre_toutes_les_traces(db_path, traces_path):
    """Critère 6 : sans filtre, l'API rend toutes les traces, comme avant le ticket."""
    traces = api_traces.list_traces(version=None)
    assert len(traces) == 5


def test_annotation_survit_au_filtre(db_path, traces_path):
    """Critère 7 : les notes, causes et sévérités déjà écrites sur une trace
    restent rendues avec leur trace, filtre ou non."""
    trace_key = "o1::2026-10-01T10:00:00"
    api_traces.upsert_trace_note(
        trace_key, TraceNoteIn(note="à relire", cause="bug_llm", severite="majeure")
    )

    filtered = api_traces.list_traces(version=VERSION_A)
    annotated = next(t for t in filtered if t.trace_key == trace_key)
    assert annotated.note == "à relire"
    assert annotated.cause == "bug_llm"
    assert annotated.severite == "majeure"

    unfiltered = api_traces.list_traces(version=None)
    annotated_again = next(t for t in unfiltered if t.trace_key == trace_key)
    assert annotated_again.note == "à relire"
    assert annotated_again.cause == "bug_llm"
    assert annotated_again.severite == "majeure"
