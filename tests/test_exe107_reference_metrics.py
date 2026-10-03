"""Tests EXE-107 (TCK-221) — comparaison offre par offre et agrégats du rejeu.

Critères 4 à 10 : fonctions pures, aucun appel Ollama, aucune lecture/écriture
sous data/. Le critère 10 est vérifié à la main sur un jeu fabriqué de 3
offres avec des extractions fabriquées.
"""

import pytest

from orchestrator.job_search.matching.profile import (
    Profile,
    RoleCeiling,
    SearchCriteria,
    SkillEntry,
)
from orchestrator.job_search.reference.metrics import (
    aggregate,
    compare_fields,
    compare_offer,
    compare_techs,
    compute_category,
)
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.sources.base import ExtractedFacts, TechRequirement


def _profile() -> Profile:
    return Profile(
        profile_id="test",
        role_ceiling=RoleCeiling.ic,
        skills={
            "python": SkillEntry(level=9, desire=9),
            "fastapi": SkillEntry(level=7, desire=7),
        },
        search_criteria=SearchCriteria(
            keywords=["python"],
            domains=["ai_engineering"],
            locations=["remote"],
            contract_types=["cdi"],
        ),
    )


def _table() -> AliasTable:
    return AliasTable()


# ---------------------------------------------------------------------------
# Critère 4 — technos trouvées / manquées / inventées, canonicalisées
# ---------------------------------------------------------------------------


def test_critere4_compare_techs_trouvees_manquees_inventees():
    extrait = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[
            TechRequirement(name="Python", importance="core"),
            TechRequirement(name="docker", importance="required"),
        ],
        domain="backend",
    )
    attendu = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[
            TechRequirement(name="python", importance="core"),
            TechRequirement(name="fastapi", importance="required"),
        ],
        domain="backend",
    )

    trouvees, manquees, inventees = compare_techs(extrait, attendu, _table())

    assert trouvees == ["python"]
    assert manquees == ["fastapi"]
    assert inventees == ["docker"]


# ---------------------------------------------------------------------------
# Critère 5 — séniorité / domaine / niveau de rôle
# ---------------------------------------------------------------------------


def test_critere5_compare_fields():
    extrait = ExtractedFacts(
        seniority_required="senior",
        techs_required=[],
        domain="backend",
        role_level="ic",
    )
    attendu = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[],
        domain="backend",
        role_level="lead",
    )

    result = compare_fields(extrait, attendu)

    assert result == {"seniority": False, "domain": True, "role_level": False}


# ---------------------------------------------------------------------------
# Critère 6 — catégorie extraite / attendue, avec le profil courant
# ---------------------------------------------------------------------------


def test_critere6_categorie_calculee_sur_facts_et_attendu():
    profile = _profile()
    table = _table()
    extrait = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[TechRequirement(name="python", importance="core")],
        domain="ai_engineering",
    )
    attendu = ExtractedFacts(
        seniority_required="intermediate", techs_required=[], domain="other"
    )

    comparison = compare_offer("1", extrait, attendu, profile, table, 1.0)

    assert comparison.categorie_extrait == compute_category(extrait, profile, table)
    assert comparison.categorie_attendu == compute_category(attendu, profile, table)
    assert comparison.categorie_extrait != comparison.categorie_attendu


# ---------------------------------------------------------------------------
# Critères 7, 8, 9, 10 — agrégats, calculés à la main sur un jeu fabriqué de
# 3 offres avec des extractions fabriquées
# ---------------------------------------------------------------------------


def test_critere7_8_9_10_agregats_calcules_a_la_main():
    profile = _profile()
    table = _table()

    # Offre 1 : extraction parfaite (identique à l'attendu) → catégorie parfait.
    attendu_1 = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[
            TechRequirement(name="python", importance="core"),
            TechRequirement(name="fastapi", importance="required"),
        ],
        domain="ai_engineering",
        role_level="ic",
    )
    extrait_1 = attendu_1.model_copy()

    # Offre 2 : attendu désirable mais inatteignable (rêve) ; l'extraction
    # rate tout (aucune techno, mauvais domaine) → le tri la classe
    # « atteignable », pas « rêve » : une offre manquée pour le rappel du tri.
    attendu_2 = ExtractedFacts(
        seniority_required="senior",
        techs_required=[TechRequirement(name="rust", importance="core")],
        domain="ai_engineering",
        role_level="ic",
    )
    extrait_2 = ExtractedFacts(
        seniority_required="intermediate",
        techs_required=[],
        domain="other",
        role_level="ic",
    )

    # Offre 3 : extraction échouée.
    attendu_3 = ExtractedFacts(
        seniority_required="junior",
        techs_required=[TechRequirement(name="sql", importance="core")],
        domain="data_engineering",
        role_level="ic",
    )

    c1 = compare_offer("1", extrait_1, attendu_1, profile, table, 1.0)
    c2 = compare_offer("2", extrait_2, attendu_2, profile, table, 3.0)
    c3 = compare_offer("3", None, attendu_3, profile, table, 2.0)

    metrics = aggregate([c1, c2, c3])

    # Technos : trouvées = {python, fastapi} (offre 1) = 2 ; manquées =
    # {rust} (offre 2) + {sql} (offre 3, échec) = 2 ; inventées = 0.
    assert metrics.technos_precision == pytest.approx(1.0)  # 2 / (2 + 0)
    assert metrics.technos_rappel == pytest.approx(0.5)  # 2 / (2 + 2)

    # Champs justes : séniorité (offre 1 seule) = 1/3 ; domaine (offre 1
    # seule) = 1/3 ; niveau de rôle (offres 1 et 2) = 2/3.
    assert metrics.seniorite_part_juste == pytest.approx(1 / 3)
    assert metrics.domaine_part_juste == pytest.approx(1 / 3)
    assert metrics.niveau_role_part_juste == pytest.approx(2 / 3)

    # Échecs : 1/3 (offre 3). Durée médiane de [1.0, 3.0, 2.0] = 2.0.
    assert metrics.extractions_echouees_part == pytest.approx(1 / 3)
    assert metrics.duree_mediane_s == pytest.approx(2.0)

    # Rappel du tri : offres dont l'attendu est parfait/rêve = {1 (parfait),
    # 2 (rêve)} ; le modèle en retrouve 1 (offre 1, parfait) → 1/2.
    assert metrics.rappel_tri == pytest.approx(0.5)
