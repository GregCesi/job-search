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
    attainability: float | None        # score 0-100 (chantier 2 — était ReachLevel string)
    category: str | None = None        # parfait | reve | atteignable | hors
    score_in_category: float | None = None
    verdict: str | None
    seen: bool
    fetched_at: str
    filtered_out: bool = False
    filter_reason: str | None = None


class ExtractedFactsSchema(BaseModel):
    seniority_required: str
    techs_required: list[str]
    domain: str
    parse_failed: bool = False


class AttainabilityDetailSchema(BaseModel):
    attain_tech: float
    attain_role: float
    blocked_by: str | None
    techs_matched: list[str]
    techs_missing: list[str]


class OfferDetail(OfferRow):
    description: str | None
    url: str | None
    source: str
    extracted_facts: ExtractedFactsSchema | None
    desirability_detail: dict | None
    attainability_detail: AttainabilityDetailSchema | None
    criteria: list[CriterionSchema]


class VerdictIn(BaseModel):
    status: Literal["favori", "rejeté", "candidaté", "masqué"]


class CriterionSchema(BaseModel):
    nom: str
    note: float        # 0-10
    justif: str
    axe: str           # "desirability" | "attainability"


class ReviewIn(BaseModel):
    ratings_json: dict              # {nom_critère: {note: int|null, justif: str|null}}
    global_audit_text: str | None = None
    global_score: int | None = None


class ReviewOut(BaseModel):
    offer_id: str
    ratings_json: dict
    ai_snapshot_json: list          # copie figée des criteria à l'instant T
    global_audit_text: str | None
    global_score: int | None
    seen_at_review: bool
    created_at: str
