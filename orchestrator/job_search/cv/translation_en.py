"""Traduction du bloc compétences et du lieu vers le CV anglais (EXE-183).

Table figée, écrite à la main depuis le CV anglais de référence (H3 du ticket) :
aucun mot traduit hors de cette table, par le code ou par un modèle — c'est une
substitution pure, jamais un appel LLM (architecture.md §4 : zéro recalcul modèle
depuis un geste qui ne touche pas à l'extraction).
"""

from __future__ import annotations

from orchestrator.job_search.cv.skills import SkillGroup, generate_cv_html

GROUP_LABELS_EN: dict[str, str] = {
    "IA & LLM": "AI & LLM",
    "Développement": "Development",
    "Outils & méthodes": "Tools & methods",
}

SKILL_TRANSLATIONS_EN: dict[str, str] = {
    "Systèmes agentiques": "Agentic systems",
    "Évaluation & tracing d'appels LLM": "LLM call evaluation & tracing",
    "LLM local (Ollama)": "Local LLM (Ollama)",
    "API Anthropic": "Anthropic API",
    "API Notion": "Notion API",
    "Revues de code": "Code reviews",
    "environnement cloud (AWS, Azure, Google Cloud)": (
        "cloud environments (AWS, Azure, Google Cloud)"
    ),
}

LOCATION_TRANSLATIONS_EN: dict[str, str] = {
    "Bruxelles, Belgique": "Brussels, Belgium",
}

NOTIONS_LABEL_EN = "Basic knowledge:"
SKILLS_HEADER_EN = "Skills"
EDUCATION_HEADER_EN = "Education"


def translate_groupes_en(groupes: list[SkillGroup]) -> list[SkillGroup]:
    """Groupe par groupe : libellé traduit s'il est dans la table (critère 6),
    chaque item traduit s'il est l'une des 7 compétences de la table (critère 7),
    inchangé sinon (critère 8)."""
    return [
        SkillGroup(
            label=GROUP_LABELS_EN.get(g.label, g.label),
            items=[SKILL_TRANSLATIONS_EN.get(i, i) for i in g.items],
        )
        for g in groupes
    ]


def translate_notions_en(notions: list[str]) -> list[str]:
    """Une notion traduite si elle est l'une des 7 compétences de la table
    (critère 7, ex. « environnement cloud... »), inchangée sinon (critère 8)."""
    return [SKILL_TRANSLATIONS_EN.get(n, n) for n in notions]


def translate_location_en(location: str) -> str:
    """« Bruxelles, Belgique » devient « Brussels, Belgium » ; tout autre lieu,
    y compris « Strasbourg, France », reste tel quel (critère 9)."""
    return LOCATION_TRANSLATIONS_EN.get(location, location)


def build_cv_html_en(
    cv_html_ref_en: str,
    title: str,
    location_fr: str,
    groupes: list[SkillGroup],
    notions: list[str],
) -> str:
    """CV anglais : même titre que le français (critère 10), lieu et bloc
    compétences traduits par la table figée, reste du CV anglais de référence
    repris tel quel (critère 4). Aucun appel modèle."""
    return generate_cv_html(
        cv_html_ref_en,
        title,
        translate_location_en(location_fr),
        translate_groupes_en(groupes),
        translate_notions_en(notions),
        header_label=SKILLS_HEADER_EN,
        next_header_label=EDUCATION_HEADER_EN,
        notions_label=NOTIONS_LABEL_EN,
    )
