import hashlib
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator


class CriterionConfig(BaseModel):
    key: str
    weight: float


class LocationConfig(BaseModel):
    base: str
    radius_km: int
    remote_ok: bool


class Profile(BaseModel):
    profile_id: str
    title: str
    seniority: str
    stack: list[str]
    location: LocationConfig
    criteria: list[CriterionConfig]

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "Profile":
        total = sum(c.weight for c in self.criteria)
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"criteria weights must sum to 1.0, got {total:.4f}")
        return self


def load_profile(path: str | Path) -> tuple[Profile, str]:
    """Load and validate a profile YAML. Returns (Profile, sha256_hex)."""
    path = Path(path)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    data: dict[str, Any] = yaml.safe_load(raw)
    profile = Profile.model_validate(data)
    return profile, digest
