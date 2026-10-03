"""Tests EXE-114 — le filtre de contrat connaît les valeurs Indeed (Permanent,
Full-time, Part-time), et rattrape les offres déjà écartées à tort.

Aucun test ne lit ni n'écrit sous data/, ni n'appelle un modèle : base en
tmp_path, profil construit en mémoire (pas de YAML sous profiles/).
"""

import sqlite3
from datetime import datetime, timezone

import pytest

import orchestrator.job_search.ingestion as ingestion
from orchestrator.job_search.matching.profile import (
    Profile,
    RoleCeiling,
    SearchCriteria,
    Zone,
)
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.offers import save_offer

ZONES = {
    "strasbourg_area": Zone(insee=["67482"], dept=["67"], keywords=["strasbourg"]),
}

CRITERIA_CDI_FREELANCE = SearchCriteria(
    keywords=["python"],
    domains=["backend"],
    locations=["strasbourg_area", "remote"],
    contract_types=["cdi", "freelance"],
)

CRITERIA_FREELANCE_ONLY = SearchCriteria(
    keywords=["python"],
    domains=["backend"],
    locations=["strasbourg_area", "remote"],
    contract_types=["freelance"],
)


def _offer(**overrides) -> JobOffer:
    defaults = dict(
        source="indeed",
        source_id="ind-1",
        fingerprint="fp",
        title="Data Architecte H/F",
        description="",
        url="http://example.com",
        remote=False,
        alternance=False,
        company="Acme",
        location="67 - Strasbourg",
        contract_type="Permanent",
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return JobOffer(**defaults)


def _profile(criteria: SearchCriteria) -> Profile:
    return Profile(
        profile_id="test",
        role_ceiling=RoleCeiling.ic,
        skills={},
        zones=ZONES,
        search_criteria=criteria,
    )


# ---------------------------------------------------------------------------
# Critère 1 — offre « Permanent », profil cdi : non écartée
# ---------------------------------------------------------------------------


def test_critere1_permanent_passe_avec_profil_cdi():
    offer = _offer(contract_type="Permanent")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert not filtered_out, f"attendu non filtrée, obtenu : {reason}"


# ---------------------------------------------------------------------------
# Critère 2 — insensibilité à la casse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("valeur", ["permanent", "PERMANENT", "Permanent"])
def test_critere2_casse_indifferente(valeur):
    offer = _offer(contract_type=valeur)
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert not filtered_out, f"attendu non filtrée pour {valeur!r}, obtenu : {reason}"


# ---------------------------------------------------------------------------
# Critère 3 — offre « Permanent », profil freelance seulement : écartée contract:cdi
# ---------------------------------------------------------------------------


def test_critere3_permanent_ecartee_si_profil_freelance_seul():
    offer = _offer(contract_type="Permanent")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_FREELANCE_ONLY, ZONES)
    assert filtered_out
    assert reason == "contract:cdi"


# ---------------------------------------------------------------------------
# Critère 4 — offre « Full-time », profil cdi+freelance : non écartée
# ---------------------------------------------------------------------------


def test_critere4_full_time_ne_decide_rien():
    offer = _offer(contract_type="Full-time")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert not filtered_out, f"attendu non filtrée, obtenu : {reason}"


# ---------------------------------------------------------------------------
# Critère 5 — offre « Part-time » : toujours écartée, raison contract:part-time
# ---------------------------------------------------------------------------


def test_critere5_part_time_toujours_ecartee():
    offer = _offer(contract_type="Part-time")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert filtered_out
    assert reason == "contract:part-time"


# ---------------------------------------------------------------------------
# Non-régression — un code France Travail ou EURES n'est pas affecté
# ---------------------------------------------------------------------------


def test_non_regression_code_france_travail_cdi_inchange():
    offer = _offer(contract_type="CDI")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert not filtered_out


def test_non_regression_code_eures_directhire_inchange():
    offer = _offer(contract_type="DIRECTHIRE")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert not filtered_out


def test_non_regression_code_france_travail_mis_toujours_ecarte():
    offer = _offer(contract_type="MIS")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA_CDI_FREELANCE, ZONES)
    assert filtered_out
    assert reason == "contract:mis"


# ---------------------------------------------------------------------------
# Rattrapage (critères 6-8)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "job_search.sqlite"
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    init_db(c)
    yield c
    c.close()


def _save_filtered(conn, offer, filter_reason):
    save_offer(conn, offer, filtered_out=True, filter_reason=filter_reason)


def _get_row(conn, source_id):
    return conn.execute(
        "SELECT * FROM offers WHERE source_id = ?", (source_id,)
    ).fetchone()


def test_critere6_offre_rattrapee_passe_en_attente_extraction(conn):
    offer = _offer(source_id="ind-6", contract_type="Permanent")
    _save_filtered(conn, offer, "contract:permanent")

    n = ingestion.rattraper_filtre_contrat(conn, _profile(CRITERIA_CDI_FREELANCE))

    assert n == 1
    row = _get_row(conn, "ind-6")
    assert bool(row["filtered_out"]) is False
    assert row["filter_reason"] is None
    assert row["extraction_status"] == "pending"
    assert row["extraction_attempts"] == 0


def test_critere7_offre_rattrapee_reste_ecartee_pour_autre_raison(conn):
    # Toujours écartée après correctif, mais pour une autre raison : le lieu.
    offer = _offer(
        source_id="ind-7",
        contract_type="Permanent",
        location="33 - Bordeaux",
    )
    _save_filtered(conn, offer, "contract:permanent")

    n = ingestion.rattraper_filtre_contrat(conn, _profile(CRITERIA_CDI_FREELANCE))

    assert n == 1
    row = _get_row(conn, "ind-7")
    assert bool(row["filtered_out"]) is True
    assert row["filter_reason"] == "location:hors_zone"


def test_critere8_compte_rendu_du_nombre_rattrape(conn):
    offer_a = _offer(source_id="ind-8a", contract_type="Permanent")
    offer_b = _offer(source_id="ind-8b", contract_type="Full-time")
    offer_c = _offer(source_id="ind-8c", contract_type="MIS")
    _save_filtered(conn, offer_a, "contract:permanent")
    _save_filtered(conn, offer_b, "contract:full-time")
    _save_filtered(conn, offer_c, "contract:mis")

    n = ingestion.rattraper_filtre_contrat(conn, _profile(CRITERIA_CDI_FREELANCE))

    assert n == 2
    # L'offre écartée pour une autre raison (contract:mis) n'est pas touchée.
    row_c = _get_row(conn, "ind-8c")
    assert row_c["filter_reason"] == "contract:mis"
    assert bool(row_c["filtered_out"]) is True


def test_rattrapage_offre_non_concernee_non_reevaluee(conn):
    """Une offre écartée pour une autre raison (ici le lieu) n'est pas touchée,
    même si elle ne serait jamais passée par le filtre de contrat."""
    offer = _offer(source_id="ind-9", location="33 - Bordeaux", contract_type="CDI")
    _save_filtered(conn, offer, "location:hors_zone")

    n = ingestion.rattraper_filtre_contrat(conn, _profile(CRITERIA_CDI_FREELANCE))

    assert n == 0
    row = _get_row(conn, "ind-9")
    assert row["filter_reason"] == "location:hors_zone"
