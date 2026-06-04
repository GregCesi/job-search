from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator


class SeniorityLevel(str, Enum):
    junior = "junior"
    intermediate = "intermediate"
    senior = "senior"
    lead = "lead"


class RoleLevel(str, Enum):
    ic = "ic"
    lead = "lead"
    manager = "manager"


class TechRequirement(BaseModel):
    name: str
    importance: Literal["core", "required", "nice_to_have"]


class ExtractedFacts(BaseModel):
    """Faits intrinsèques extraits par LLM une seule fois à l'ingestion (architecture.md §4)."""
    seniority_required: SeniorityLevel
    techs_required: list[TechRequirement]   # y compris implicites ("RAG en prod" → "RAG")
    domain: str                              # domaine métier réel désambiguïsé
    role_level: RoleLevel = RoleLevel.ic    # rôle non-technique (ic/lead/manager)
    parse_failed: bool = False              # flag si extraction LLM dégradée (architecture.md §3)

    @model_validator(mode="before")
    @classmethod
    def _coerce_techs_v1(cls, data: object) -> object:
        """Compat v1 : techs_required était list[str] — coerce en list[TechRequirement]."""
        if isinstance(data, dict):
            techs = data.get("techs_required", [])
            if techs and isinstance(techs[0], str):
                data = dict(data)
                data["techs_required"] = [
                    {"name": t, "importance": "required"} for t in techs
                ]
        return data


class JobOffer(BaseModel):
    source: str           # "france_travail", futur: autre source
    source_id: str        # id natif stable côté source
    fingerprint: str      # hash(titre normalisé + entreprise + localisation) — crochet cross-source
    title: str
    description: str
    company: str | None
    location: str | None  # libellé brut
    remote: bool          # full-remote détecté
    contract_type: str | None         # code court ("CDI", "CDD", "MIS"…)
    nature_contract: str | None = None  # libellé long ("Contrat apprentissage"…)
    alternance: bool = False
    full_time: bool | None = None     # None si non renseigné
    company_size: str | None = None   # trancheEffectifEtab brut ("500 à 999 salariés"…)
    experience_required: str | None = None  # D/S/E — signal grossier pré-LLM
    rome_code: str | None = None      # ex: "M1889"
    rome_label: str | None = None     # ex: "Ingénieur / Ingénieure en IA"
    url: str
    fetched_at: datetime
    extracted_facts: ExtractedFacts | None = None  # rempli par l'étage LLM (L3)


class Source(ABC):
    @abstractmethod
    def fetch(self) -> list[JobOffer]:
        ...
