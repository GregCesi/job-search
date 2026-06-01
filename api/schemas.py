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
    score: float | None
    verdict: str | None
    seen: bool
    fetched_at: str


class CriterionScore(BaseModel):
    key: str
    score: float
    justification: str
    parse_failed: bool = False


class OfferDetail(OfferRow):
    description: str | None
    url: str | None
    source: str
    criteria: list[CriterionScore]


class VerdictIn(BaseModel):
    status: Literal["favori", "rejeté", "candidaté", "masqué"]
