"""Tests unitaires — module gate hors_perimetre (Lot G)."""
import pytest

from orchestrator.job_search.scoring.hors_perimetre import (
    HorsPerimetreCause,
    derive_hors_perimetre,
)
from orchestrator.job_search.sources.base import (
    ExtractedFacts,
    RoleLevel,
    SeniorityLevel,
    TechRequirement,
)


def _facts(
    techs: list[str] | None = None,
    role: str = "ic",
) -> ExtractedFacts:
    """Helper — crée des ExtractedFacts minimales."""
    tech_list = (
        [TechRequirement(name=t, importance="required") for t in techs]
        if techs is not None
        else [TechRequirement(name="python", importance="core")]
    )
    return ExtractedFacts(
        seniority_required=SeniorityLevel.intermediate,
        techs_required=tech_list,
        domain="backend",
        role_level=RoleLevel(role),
    )


# ── Règle no_tech ──────────────────────────────────────────────

class TestNoTech:
    def test_empty_techs_triggers(self):
        causes = derive_hors_perimetre(_facts(techs=[]))
        assert HorsPerimetreCause.no_tech in causes

    def test_with_techs_does_not_trigger(self):
        causes = derive_hors_perimetre(_facts(techs=["python"]))
        assert HorsPerimetreCause.no_tech not in causes


# ── Règle mgmt_role ────────────────────────────────────────────

class TestMgmtRole:
    def test_manager_triggers(self):
        causes = derive_hors_perimetre(_facts(role="manager"))
        assert HorsPerimetreCause.mgmt_role in causes

    def test_ic_does_not_trigger(self):
        causes = derive_hors_perimetre(_facts(role="ic"))
        assert HorsPerimetreCause.mgmt_role not in causes

    def test_lead_does_not_trigger(self):
        causes = derive_hors_perimetre(_facts(role="lead"))
        assert HorsPerimetreCause.mgmt_role not in causes


# ── Règle langue ───────────────────────────────────────────────

class TestLangue:
    @pytest.mark.parametrize("keyword", [
        "German", "allemand", "Deutsch",
        "Spanish", "espagnol",
        "Russian", "russe",
        "Portuguese", "portugais",
        "Japanese", "japonais",
        "Chinese", "chinois", "Mandarin",
        "Arabic", "arabe",
        "Polish", "polonais",
        "Italian", "italien",
        "Dutch", "néerlandais",
    ])
    def test_langue_tierce_triggers(self, keyword: str):
        causes = derive_hors_perimetre(
            _facts(),
            title=f"Software Engineer ({keyword} required)",
        )
        assert HorsPerimetreCause.langue in causes

    def test_french_does_not_trigger(self):
        causes = derive_hors_perimetre(
            _facts(),
            title="Data Analyst (French Language)",
            description="Français courant exigé",
        )
        assert HorsPerimetreCause.langue not in causes

    def test_english_does_not_trigger(self):
        causes = derive_hors_perimetre(
            _facts(),
            title="AI Engineer",
            description="English fluency required",
        )
        assert HorsPerimetreCause.langue not in causes

    def test_langue_in_description_triggers(self):
        causes = derive_hors_perimetre(
            _facts(),
            title="Data Analyst",
            description="Must speak Portuguese fluently",
        )
        assert HorsPerimetreCause.langue in causes


# ── Règle contrat ──────────────────────────────────────────────

class TestContrat:
    def test_contract_type_internship(self):
        causes = derive_hors_perimetre(
            _facts(), contract_type="Internship",
        )
        assert HorsPerimetreCause.contrat in causes

    def test_contract_type_mis(self):
        causes = derive_hors_perimetre(
            _facts(), contract_type="MIS",
        )
        assert HorsPerimetreCause.contrat in causes

    def test_contract_type_cdi_does_not_trigger(self):
        causes = derive_hors_perimetre(
            _facts(), contract_type="CDI",
        )
        assert HorsPerimetreCause.contrat not in causes

    def test_nature_contract_apprentissage(self):
        causes = derive_hors_perimetre(
            _facts(), nature_contract="Contrat apprentissage",
        )
        assert HorsPerimetreCause.contrat in causes

    def test_nature_contract_professionnalisation(self):
        causes = derive_hors_perimetre(
            _facts(), nature_contract="Cont. professionnalisation",
        )
        assert HorsPerimetreCause.contrat in causes

    def test_alternance_flag(self):
        causes = derive_hors_perimetre(
            _facts(), alternance=True,
        )
        assert HorsPerimetreCause.contrat in causes

    @pytest.mark.parametrize("title", [
        "Alternance Data Engineer",
        "Stage développeur Python",
        "Apprentissage DevOps",
        "ML Intern",
    ])
    def test_titre_pattern(self, title: str):
        causes = derive_hors_perimetre(
            _facts(), title=title,
        )
        assert HorsPerimetreCause.contrat in causes

    def test_cdi_fulltime_does_not_trigger(self):
        causes = derive_hors_perimetre(
            _facts(),
            title="Senior Python Developer",
            contract_type="CDI",
            alternance=False,
        )
        assert HorsPerimetreCause.contrat not in causes


# ── Cumul de causes ────────────────────────────────────────────

class TestCumul:
    def test_langue_plus_contrat(self):
        causes = derive_hors_perimetre(
            _facts(),
            title="Alternance développeur German-speaking",
        )
        assert HorsPerimetreCause.langue in causes
        assert HorsPerimetreCause.contrat in causes

    def test_no_tech_plus_mgmt(self):
        causes = derive_hors_perimetre(
            _facts(techs=[], role="manager"),
        )
        assert HorsPerimetreCause.no_tech in causes
        assert HorsPerimetreCause.mgmt_role in causes

    def test_all_four_causes(self):
        causes = derive_hors_perimetre(
            _facts(techs=[], role="manager"),
            title="Stage German DevOps",
            alternance=True,
        )
        assert len(causes) == 4
        assert set(causes) == {
            HorsPerimetreCause.no_tech,
            HorsPerimetreCause.mgmt_role,
            HorsPerimetreCause.langue,
            HorsPerimetreCause.contrat,
        }


# ── Non-régression ─────────────────────────────────────────────

class TestNonRegression:
    def test_cdi_fr_no_langue_returns_empty(self):
        """Offre CDI française sans langue tierce → aucune cause."""
        causes = derive_hors_perimetre(
            _facts(techs=["python", "fastapi"]),
            title="Développeur Python Senior H/F",
            description="Rejoignez notre équipe à Strasbourg. Python, FastAPI, PostgreSQL.",
            contract_type="CDI",
            alternance=False,
        )
        assert causes == []

    def test_freelance_en_returns_empty(self):
        """Offre freelance anglophone → aucune cause."""
        causes = derive_hors_perimetre(
            _facts(techs=["react", "typescript"]),
            title="Senior Frontend Engineer (Remote)",
            description="Join our team. React, TypeScript, English required.",
            contract_type="Freelance",
            alternance=False,
        )
        assert causes == []

    def test_gate_does_not_modify_facts(self):
        """Le gate ne modifie jamais les faits extraits."""
        facts = _facts(techs=["python"])
        facts_json_before = facts.model_dump_json()
        derive_hors_perimetre(
            facts,
            title="Alternance German developer",
            alternance=True,
        )
        assert facts.model_dump_json() == facts_json_before
