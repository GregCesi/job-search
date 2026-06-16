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
    category: str | None = None        # parfait | reve | atteignable | hors
    verdict: str | None
    hors_perimetre_reason: str | None = None
    seen: bool
    fetched_at: str
    filtered_out: bool = False
    filter_reason: str | None = None
    # chantier review humaine
    categorie_suggeree: str | None = None
    categorie_corrigee: str | None = None
    categorie_finale: str | None = None    # dérivé : corrigee ?? suggeree (jamais persisté)
    etat_review: str | None = None         # dérivé : non_relue | validee | corrigee
    remarque: str | None = None
    reviewed_at: str | None = None


class TechSchema(BaseModel):
    name: str
    importance: str | None = None  # core | required | nice_to_have | None (v1 compat)


class ExtractedFactsSchema(BaseModel):
    seniority_required: str
    techs_required: list[TechSchema]
    domain: str
    role_level: str | None = None  # ic | lead | manager
    parse_failed: bool = False


class OfferDetail(OfferRow):
    description: str | None
    url: str | None
    source: str
    extracted_facts: ExtractedFactsSchema | None


class VerdictIn(BaseModel):
    status: Literal["favori", "rejeté", "candidaté", "masqué", "hors_perimetre_ok", "hors_perimetre_faux_pos"]


class CategoryReviewIn(BaseModel):
    """Review de catégorie — chantier review humaine."""
    categorie_corrigee: str | None = None   # None = validation de la suggestion
    remarque: str | None = None


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
