import hashlib
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from orchestrator.job_search.sources.base import SeniorityLevel


class MasteryLevel(str, Enum):
    notions = "notions"
    working = "working"
    confirmed = "confirmed"


class SearchCriteria(BaseModel):
    domains: list[str]
    locations: list[str]
    contract_types: list[str]


class Profile(BaseModel):
    profile_id: str
    seniority: SeniorityLevel
    techs: dict[str, MasteryLevel]
    search_criteria: SearchCriteria

    def tech_level(self, tech: str) -> MasteryLevel | None:
        """Mastery level for a tech (case-insensitive), or None if not in profile."""
        return self.techs.get(tech.lower())


def load_profile(path: str | Path) -> tuple[Profile, str]:
    """Load and validate a profile YAML. Returns (Profile, sha256_hex)."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = yaml.safe_load(raw)
    return Profile.model_validate(data), digest
