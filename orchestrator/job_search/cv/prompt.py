"""Prompt de placement des ajouts autorisés dans le bloc compétences (EXE-58).

Le LLM ne choisit PAS quelles compétences ajouter — ça, c'est le calcul Python de
`skills.compute_permitted_additions`. Il décide seulement dans quel groupe existant
placer chaque ajout autorisé, en reprenant son libellé exact sans le modifier.
"""

import json

from orchestrator.job_search.cv.skills import Addition, SkillGroup

SCHEMA = {
    "type": "object",
    "properties": {
        "groupes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "items"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["groupes"],
    "additionalProperties": False,
}


def build_prompt(
    offer_title: str, groupes: list[SkillGroup], additions: list[Addition]
) -> str:
    groupes_json = json.dumps(
        [{"label": g.label, "items": g.items} for g in groupes],
        ensure_ascii=False,
        indent=2,
    )
    additions_lines = (
        "\n".join(f"  - {a.raw_name}" for a in additions) if additions else "  aucune"
    )
    return (
        "Tu places des compétences autorisées dans le bloc compétences d'un CV, "
        "pour l'offre suivante.\n\n"
        f"**Offre** : {offer_title}\n\n"
        "**Groupes actuels du CV (à conserver tels quels, dans l'ordre) :**\n"
        f"{groupes_json}\n\n"
        "**Compétences autorisées à ajouter (libellé exact, à reprendre sans le modifier) :**\n"
        f"{additions_lines}\n\n"
        "**Instructions :**\n"
        "1. Rends TOUS les groupes existants avec TOUS leurs items d'origine, dans l'ordre.\n"
        "2. Pour chaque compétence autorisée listée ci-dessus, ajoute-la — avec son "
        "libellé exact, sans le modifier — dans le groupe existant le plus pertinent.\n"
        "3. N'invente, ne retire, ne renomme et ne déplace aucun autre item.\n"
        "4. N'ajoute aucune compétence absente de la liste ci-dessus.\n"
    )
