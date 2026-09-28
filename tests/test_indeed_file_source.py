"""Tests unitaires — IndeedFileSource, repli d'identifiant sans indeed_id/id (EXE-56)."""

import json
import warnings

from orchestrator.job_search.sources.indeed_file import IndeedFileSource


def _write_jsonl(tmp_path, name: str, lines: list[dict]) -> None:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def test_offer_without_indeed_id_is_ingested(tmp_path):
    _write_jsonl(
        tmp_path,
        "offers.jsonl",
        [{"title": "Dev Python", "company": "Acme", "location": "Strasbourg"}],
    )

    offers = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()

    assert len(offers) == 1


def test_offer_without_indeed_id_gets_16_hex_char_source_id(tmp_path):
    _write_jsonl(
        tmp_path,
        "offers.jsonl",
        [{"title": "Dev Python", "company": "Acme", "location": "Strasbourg"}],
    )

    offers = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()

    source_id = offers[0].source_id
    assert len(source_id) == 16
    int(source_id, 16)  # lève si non hexadécimal


def test_same_offer_without_id_gets_same_source_id_across_reads(tmp_path):
    offer = {"title": "Dev Python", "company": "Acme", "location": "Strasbourg"}
    _write_jsonl(tmp_path, "offers.jsonl", [offer])
    first = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()[0].source_id

    _write_jsonl(tmp_path, "offers.jsonl", [offer])
    second = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()[0].source_id

    assert first == second


def test_two_offers_differing_only_by_company_get_different_source_ids(tmp_path):
    _write_jsonl(
        tmp_path,
        "offers.jsonl",
        [
            {"title": "Dev Python", "company": "Acme", "location": "Strasbourg"},
            {"title": "Dev Python", "company": "Globex", "location": "Strasbourg"},
        ],
    )

    offers = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()

    assert offers[0].source_id != offers[1].source_id


def test_offer_with_indeed_id_keeps_it_as_source_id(tmp_path):
    _write_jsonl(
        tmp_path,
        "offers.jsonl",
        [
            {
                "indeed_id": "abc123",
                "title": "Dev Python",
                "company": "Acme",
                "location": "Strasbourg",
            }
        ],
    )

    offers = IndeedFileSource(inbox_dir=str(tmp_path)).fetch()

    assert offers[0].source_id == "abc123"


def test_reading_offer_without_id_emits_no_warning(tmp_path):
    _write_jsonl(
        tmp_path,
        "offers.jsonl",
        [{"title": "Dev Python", "company": "Acme", "location": "Strasbourg"}],
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        IndeedFileSource(inbox_dir=str(tmp_path)).fetch()

    assert len(caught) == 0
