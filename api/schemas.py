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
    hors_perimetre_reason: str | None = None
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
    status: Literal["favori", "rejeté", "candidaté", "masqué", "hors_perimetre_ok", "hors_perimetre_faux_pos"]


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


# ── Traces viewer ────────────────────────────────────────────────────────────

class TraceParsedFacts(BaseModel):
    """Reflet de parsed_facts tel quel — NON jugé, NON normalisé."""
    seniority_required: str | None = None
    techs_required: list = []           # str ou objets {name, importance}, bruts
    domain: str | None = None
    role_level: str | None = None
    parse_failed: bool = False


class TraceOut(BaseModel):
    trace_key: str                      # f"{offer_id}::{timestamp}"
    offer_id: str
    offer_title: str | None = None      # enrichi depuis offers (L3)
    offer_company: str | None = None
    model: str
    temperature: float
    timestamp: str
    prompt_system: str
    prompt_user: str
    raw_response: str
    parsed_facts: TraceParsedFacts
    parse_failed: bool
    note: str | None = None             # joint depuis trace_notes (L4)
    cause: str | None = None            # troncature | bug_llm | ok | null
    severite: str | None = None         # mineure | majeure | critique | null


CAUSE_VALUES = {"troncature", "bug_llm", "ok"}
SEVERITE_VALUES = {"mineure", "majeure", "critique"}


class TraceNoteIn(BaseModel):
    note: str                           # vide = effacement
    cause: str | None = None
    severite: str | None = None
