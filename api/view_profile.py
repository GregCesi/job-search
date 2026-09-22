"""Filtre SQL pour le profil de vue candidat.

Charge vue_candidat.yaml (liste de noms de zones), résout les définitions
depuis gregoire.yaml, et construit les conditions SQL pour GET /offers.
"""
from __future__ import annotations

import yaml

from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import PROFILE_PATH, VUE_CANDIDAT_PATH

_clauses_cache: tuple[list[str], list] | None = None


def build_view_clauses() -> tuple[list[str], list]:
    """Retourne (conditions, params) pour filtrer sur les zones du profil de vue.

    Les conditions sont des OR entre elles — l'assemblage (jointure, wrapping)
    est à la charge de l'appelant.

    Lève FileNotFoundError si VUE_CANDIDAT_PATH est illisible.
    Lève ValueError si un nom de zone est absent de gregoire.yaml.
    """
    global _clauses_cache
    if _clauses_cache is not None:
        return _clauses_cache

    if not VUE_CANDIDAT_PATH.exists():
        raise FileNotFoundError(f"Profil de vue introuvable : {VUE_CANDIDAT_PATH}")
    vue_data = yaml.safe_load(VUE_CANDIDAT_PATH.read_text(encoding="utf-8"))
    zone_names: list[str] = vue_data.get("zones", [])

    profile, _ = load_profile(PROFILE_PATH)

    conditions: list[str] = []
    params: list = []

    for name in zone_names:
        zone = profile.zones.get(name)
        if zone is None:
            raise ValueError(f"zone inconnue : {name}")
        for dept in zone.dept:
            conditions.append("UPPER(o.location) LIKE ?")
            params.append(f"{dept.upper()}%")
        for kw in zone.keywords:
            conditions.append("UPPER(o.location) LIKE ?")
            params.append(f"%{kw.upper()}%")

    _clauses_cache = (conditions, params)
    return _clauses_cache
