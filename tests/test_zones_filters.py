"""Tests unitaires — zones profil + gate contrat."""
import pytest
from pydantic import ValidationError

from orchestrator.job_search.matching.profile import SearchCriteria, Zone
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.sources.base import JobOffer

# -- Helpers --

ZONES = {
    "nancy_area": Zone(insee=["54395"], dept=["54"], keywords=["nancy"]),
    "strasbourg_area": Zone(insee=["67482"], dept=["67"], keywords=["strasbourg", "bas-rhin"]),
}

CRITERIA = SearchCriteria(
    domains=["backend"],
    locations=["nancy_area", "strasbourg_area", "remote"],
    contract_types=["cdi", "freelance"],
)


def _offer(**overrides) -> JobOffer:
    from datetime import datetime, timezone
    defaults = dict(
        source="test", source_id="1", fingerprint="fp",
        title="Dev Python", description="", url="http://example.com",
        remote=False, alternance=False,
        company="Acme", contract_type="CDI",
        fetched_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return JobOffer(**defaults)


# -- L7 : zone sans dept → ValidationError --

def test_zone_without_dept_raises():
    with pytest.raises(ValidationError):
        Zone(insee=["67482"], dept=[], keywords=[])


def test_zone_without_insee_raises():
    with pytest.raises(ValidationError):
        Zone(insee=[], dept=["67"], keywords=[])


# -- L8 : offre Nancy passe le hard filter --

def test_nancy_offer_passes_with_nancy_active():
    offer = _offer(location="54 - Nancy")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert not filtered_out, f"Nancy should pass but got: {reason}"


def test_nancy_offer_passes_via_keyword():
    offer = _offer(location="NANCY (54)")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert not filtered_out, f"Nancy keyword should pass but got: {reason}"


def test_unknown_location_rejected():
    offer = _offer(location="33 - Bordeaux")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert filtered_out
    assert reason == "location:hors_zone"


def test_remote_offer_passes():
    offer = _offer(remote=True, location="Anywhere")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert not filtered_out


# -- L9 : alternance rejetée par contract_types --

def test_alternance_rejected():
    offer = _offer(alternance=True, location="54 - Nancy")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert filtered_out
    assert reason == "contract:alternance"


def test_cdi_passes():
    offer = _offer(contract_type="CDI", location="54 - Nancy")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert not filtered_out


def test_mis_rejected_when_not_in_contract_types():
    offer = _offer(contract_type="MIS", location="54 - Nancy")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert filtered_out
    assert reason == "contract:mis"


def test_stage_code_rejected():
    offer = _offer(contract_type="STA", location="54 - Nancy")
    filtered_out, reason = apply_hard_filters(offer, CRITERIA, ZONES)
    assert filtered_out
