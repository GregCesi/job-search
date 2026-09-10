"""
Dérivation du bucket hors-périmètre — Python pur, 0 LLM (architecture.md §4).

Une offre est hors-périmètre si elle cumule une ou plusieurs causes :
- no_tech   : aucune techno exigée (techs_required == [])
- mgmt_role : rôle managérial (role_level == manager)
- contrat   : stage / alternance / MIS

Retourne une liste de causes (vide = offre dans le périmètre).
"""
from enum import Enum
import re

from orchestrator.job_search.sources.base import ExtractedFacts, RoleLevel


class HorsPerimetreCause(str, Enum):
    no_tech   = "no_tech"       # techs_required == [] (incertain — à inspecter)
    mgmt_role = "mgmt_role"     # role_level == manager (décision tranchée)
    contrat   = "contrat"        # stage/alternance/MIS


# Valeurs contract_type / nature_contract éliminatoires
_CONTRAT_TYPES_GATE = {"Internship", "MIS"}
_NATURE_CONTRACTS_GATE = {"Cont. professionnalisation", "Contrat apprentissage"}
_CONTRAT_TITRE_RE = re.compile(r"alternance|stage|apprentissage|intern", re.IGNORECASE)


# Compat : ancien nom pour les imports existants qui référencent le type
HorsPerimetreReason = HorsPerimetreCause


def derive_hors_perimetre(
    facts: ExtractedFacts,
    title: str = "",
    description: str = "",
    contract_type: str | None = None,
    nature_contract: str | None = None,
    alternance: bool = False,
) -> list[HorsPerimetreCause]:
    """Dérive les causes hors-périmètre. Liste vide = offre dans le périmètre."""
    causes: list[HorsPerimetreCause] = []

    # Règle no_tech (testée en premier — cause la plus incertaine)
    if not facts.techs_required:
        causes.append(HorsPerimetreCause.no_tech)

    # Règle mgmt_role
    if facts.role_level == RoleLevel.manager:
        causes.append(HorsPerimetreCause.mgmt_role)

    # Règle contrat — contract_type / nature_contract / alternance / titre
    if (
        (contract_type and contract_type in _CONTRAT_TYPES_GATE)
        or (nature_contract and nature_contract in _NATURE_CONTRACTS_GATE)
        or alternance
        or _CONTRAT_TITRE_RE.search(title)
    ):
        causes.append(HorsPerimetreCause.contrat)

    return causes
