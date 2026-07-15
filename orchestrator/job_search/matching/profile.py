import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from orchestrator.job_search.sources.base import SeniorityLevel


class RoleCeiling(str, Enum):
    ic = "ic"
    lead = "lead"
    manager = "manager"


class SkillEntry(BaseModel):
    level: int = Field(ge=1, le=10)   # compréhension / capacité à en parler
    desire: int = Field(ge=0, le=10)  # envie de bosser dessus


class Zone(BaseModel):
    insee: list[str] = Field(min_length=1)
    dept: list[str] = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class SearchCriteria(BaseModel):
    keywords: list[str] = Field(min_length=1)
    domains: list[str]
    locations: list[str]
    contract_types: list[str]


class Profile(BaseModel):
    profile_id: str
    role_ceiling: RoleCeiling
    seniority_ceiling: SeniorityLevel | None = None
    skills: dict[str, SkillEntry]
    zones: dict[str, Zone] = Field(default_factory=dict)
    search_criteria: SearchCriteria

    def tech_level(self, tech: str) -> int | None:
        """Skill level (1-10) for a tech (case-insensitive). None = not in profile = neutral."""
        entry = self.skills.get(tech.lower())
        return entry.level if entry else None

    def tech_desire(self, tech: str) -> int | None:
        """Desire (0-10) for a tech (case-insensitive). None = not in profile = neutral."""
        entry = self.skills.get(tech.lower())
        return entry.desire if entry else None



def load_profile(path: str | Path) -> tuple[Profile, str]:
    """Load and validate a profile YAML. Returns (Profile, sha256_hex)."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = yaml.safe_load(raw)
    return Profile.model_validate(data), digest
