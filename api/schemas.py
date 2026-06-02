"""Schémas Pydantic de l'API."""
from typing import Literal
from pydantic import BaseModel


class OfferRow(BaseModel):
    id: int
    title: str | None
    company: str | None
    location: str | None
    remote: bool
    contract_type: str | None
    desirability: float | None
    attainability: str | None
    verdict: str | None
    seen: bool
    fetched_at: str


class ExtractedFactsSchema(BaseModel):
    seniority_required: str
    techs_required: list[str]
    domain: str
    parse_failed: bool = False


class AttainabilityDetailSchema(BaseModel):
    techs_matched: list[str]
    techs_missing: list[str]
    seniority_gap: int


class OfferDetail(OfferRow):
    description: str | None
    url: str | None
    source: str
    extracted_facts: ExtractedFactsSchema | None
    desirability_detail: dict | None
    attainability_detail: AttainabilityDetailSchema | None


class VerdictIn(BaseModel):
    status: Literal["favori", "rejeté", "candidaté", "masqué"]
