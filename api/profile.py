"""Profile endpoint — expose skill names for frontend matching."""
from pathlib import Path

import yaml
from fastapi import APIRouter

router = APIRouter(prefix="/profile", tags=["profile"])

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


@router.get("/skills")
def get_profile_skills(profile_id: str = "gregoire") -> list[str]:
    """Return the list of skill names from a profile YAML."""
    path = PROFILES_DIR / f"{profile_id}.yaml"
    data = yaml.safe_load(path.read_bytes())
    return list(data.get("skills", {}).keys())
