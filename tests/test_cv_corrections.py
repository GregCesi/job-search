"""Tests EXE-59 — calculs Python purs du module cv/corrections.py (critères 1, 3 à 7).

Aucune DB, aucun modèle, aucun fichier sous data/ : `add_skill`/`remove_skill` ne
manipulent que des `SkillGroup`/`list[str]` en mémoire (même isolation que
test_cv_skills.py pour cv/skills.py). `profiles/alias.yaml` est lu tel quel
(versionné, jamais modifié), comme dans test_cv_skills.py.
"""

import pytest

from orchestrator.job_search.cv.corrections import (
    SkillAlreadyPresentError,
    SkillNotFoundError,
    UnknownGroupError,
    add_skill,
    remove_skill,
)
from orchestrator.job_search.cv.skills import (
    SkillGroup,
    block_canonicals,
    compute_requested_missing,
)
from orchestrator.job_search.paths import ALIAS_PATH
from orchestrator.job_search.scoring.aliases import load_alias_table

ALIAS_TABLE = load_alias_table(ALIAS_PATH)


def _groupes() -> list[SkillGroup]:
    return [
        SkillGroup(label="Langages", items=["Python", "SQL"]),
        SkillGroup(label="Data & IA", items=["Pandas"]),
        SkillGroup(label="Outils & méthodes", items=["Git", "Docker"]),
    ]


def _notions() -> list[str]:
    return ["GraphQL", "Svelte"]


def _techs(*names: str) -> list[dict]:
    return [{"name": n, "importance": "required"} for n in names]


class TestCritere1AjoutMaitriseEnFinDeGroupe:
    def test_ajoute_a_la_fin_du_groupe_declare(self):
        groupes, notions = _groupes(), _notions()
        outcome = add_skill(groupes, notions, "Kubernetes", True, "Outils & méthodes")

        assert outcome.groupes[2].items == ["Git", "Docker", "Kubernetes"]
        assert outcome.groupes[0].items == ["Python", "SQL"]
        assert outcome.groupes[1].items == ["Pandas"]
        assert outcome.notions == notions
        assert outcome.groupe == "Outils & méthodes"
        assert outcome.maitrisee is True

        # Les entrées d'origine ne sont jamais mutées en place.
        assert groupes[2].items == ["Git", "Docker"]


class TestCritere2DisparaitDeDemandeSansYEtre:
    def test_ajout_maitrise_retire_la_techno_de_la_liste(self):
        groupes, notions = _groupes(), _notions()
        techs = _techs("Kubernetes")

        before = block_canonicals(groupes, notions, ALIAS_TABLE)
        assert "kubernetes" in {
            m.lower() for m in compute_requested_missing(techs, ALIAS_TABLE, before)
        }

        outcome = add_skill(groupes, notions, "Kubernetes", True, "Outils & méthodes")
        after = block_canonicals(outcome.groupes, outcome.notions, ALIAS_TABLE)
        missing = compute_requested_missing(techs, ALIAS_TABLE, after)
        assert missing == []


class TestCritere3AjoutNonMaitriseEnFinDeNotions:
    def test_ajoute_a_la_fin_de_notions_en(self):
        groupes, notions = _groupes(), _notions()
        outcome = add_skill(groupes, notions, "Terraform", False, None)

        assert outcome.notions == ["GraphQL", "Svelte", "Terraform"]
        assert outcome.groupes == groupes
        assert outcome.groupe is None
        assert outcome.maitrisee is False


class TestCritere4AjoutLibreHorsDesDeuxListes:
    def test_competence_absente_des_deux_listes_maitrisee(self):
        groupes, notions = _groupes(), _notions()
        outcome = add_skill(groupes, notions, "Rust", True, "Langages")
        assert "Rust" in outcome.groupes[0].items

    def test_competence_absente_des_deux_listes_non_maitrisee(self):
        groupes, notions = _groupes(), _notions()
        outcome = add_skill(groupes, notions, "Rust", False, None)
        assert outcome.notions[-1] == "Rust"


class TestCritere5RetraitDuBloc:
    def test_retrait_d_un_item_de_groupe(self):
        groupes, notions = _groupes(), _notions()
        outcome = remove_skill(groupes, notions, "SQL")

        assert outcome.groupes[0].items == ["Python"]
        assert outcome.groupe == "Langages"
        assert outcome.maitrisee is True
        # Les entrées d'origine ne sont jamais mutées en place.
        assert groupes[0].items == ["Python", "SQL"]

    def test_retrait_d_une_notion(self):
        groupes, notions = _groupes(), _notions()
        outcome = remove_skill(groupes, notions, "GraphQL")

        assert outcome.notions == ["Svelte"]
        assert outcome.groupe is None
        assert outcome.maitrisee is False

    def test_retrait_insensible_a_la_casse(self):
        groupes, notions = _groupes(), _notions()
        outcome = remove_skill(groupes, notions, "sql")
        assert "SQL" not in outcome.groupes[0].items

    def test_retrait_leve_si_absente(self):
        with pytest.raises(SkillNotFoundError):
            remove_skill(_groupes(), _notions(), "Rust")


class TestCritere6RetraitRejointDemandeSansYEtre:
    def test_retrait_d_une_techno_exigee_reapparait_dans_la_liste(self):
        groupes, notions = _groupes(), _notions()
        techs = _techs("SQL")

        before = block_canonicals(groupes, notions, ALIAS_TABLE)
        assert compute_requested_missing(techs, ALIAS_TABLE, before) == []

        outcome = remove_skill(groupes, notions, "SQL")
        after = block_canonicals(outcome.groupes, outcome.notions, ALIAS_TABLE)
        missing = compute_requested_missing(techs, ALIAS_TABLE, after)
        assert missing == ["SQL"]


class TestCritere7RefusSiDejaPresente:
    def test_ajout_maitrise_d_une_competence_deja_presente_refuse(self):
        groupes, notions = _groupes(), _notions()
        with pytest.raises(SkillAlreadyPresentError):
            add_skill(groupes, notions, "python", True, "Data & IA")
        # Rien n'a changé : les groupes/notions d'origine sont intacts.
        assert groupes == _groupes()
        assert notions == _notions()

    def test_ajout_non_maitrise_d_une_notion_deja_presente_refuse(self):
        groupes, notions = _groupes(), _notions()
        with pytest.raises(SkillAlreadyPresentError):
            add_skill(groupes, notions, "svelte", False, None)

    def test_ajout_maitrise_sans_groupe_connu_leve(self):
        with pytest.raises(UnknownGroupError):
            add_skill(_groupes(), _notions(), "Rust", True, "Groupe inexistant")
