import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class RoleCeiling(str, Enum):
    ic = "ic"
    lead = "lead"
    manager = "manager"


class SkillEntry(BaseModel):
    level: int = Field(ge=1, le=10)   # compréhension / capacité à en parler
    desire: int = Field(ge=0, le=10)  # envie de bosser dessus


class SearchCriteria(BaseModel):
    domains: list[str]
    locations: list[str]
    contract_types: list[str]


class Profile(BaseModel):
    profile_id: str
    role_ceiling: RoleCeiling
    skills: dict[str, SkillEntry]
    search_criteria: SearchCriteria

    def tech_level(self, tech: str) -> int | None:
        """Skill level (1-10) for a tech (case-insensitive). None = not in profile = neutral."""
        entry = self.skills.get(tech.lower())
        return entry.level if entry else None

    def tech_desire(self, tech: str) -> int | None:
        """Desire (0-10) for a tech (case-insensitive). None = not in profile = neutral."""
        entry = self.skills.get(tech.lower())
        return entry.desire if entry else None


# DEPRECATED — v1 enum, kept for import compat until chantier 2 Phase 3 (attainability.py rewrite)
class MasteryLevel(str, Enum):
    notions = "notions"
    working = "working"
    confirmed = "confirmed"


def load_profile(path: str | Path) -> tuple[Profile, str]:
    """Load and validate a profile YAML. Returns (Profile, sha256_hex)."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = yaml.safe_load(raw)
    return Profile.model_validate(data), digest
