"""
Dérivation du bucket hors-périmètre — Python pur, 0 LLM (architecture.md §4).

Une offre est hors-périmètre si elle n'est pas un poste IC technique :
- no_tech  : aucune techno exigée (techs_required == [])
- mgmt_role: rôle managérial (role_level == manager)

Ordre intentionnel : no_tech testé en premier (cause la plus incertaine,
à inspecter en priorité — peut masquer un bug d'extraction).
"""
from enum import Enum

from orchestrator.job_search.sources.base import ExtractedFacts, RoleLevel


class HorsPerimetreReason(str, Enum):
    no_tech = "no_tech"      # techs_required == [] (incertain — à inspecter)
    mgmt_role = "mgmt_role"  # role_level == manager (décision tranchée)


def derive_hors_perimetre(facts: ExtractedFacts) -> HorsPerimetreReason | None:
    """Dérive la raison hors-périmètre depuis les faits extraits. None = offre normale."""
    if not facts.techs_required:
        return HorsPerimetreReason.no_tech
    if facts.role_level == RoleLevel.manager:
        return HorsPerimetreReason.mgmt_role
    return None
