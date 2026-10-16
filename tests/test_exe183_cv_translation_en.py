"""Tests EXE-183 — traduction pure du bloc compétences anglais (critères 4 à 10).

Calculs 100% Python sur `orchestrator/job_search/cv/translation_en.py` et la
paramétrisation FR/EN de `cv/skills.py` : aucun appel modèle, aucune DB, aucun
fichier sous data/ (H3, H6 du ticket).
"""

from orchestrator.job_search.cv.skills import SkillGroup, generate_cv_html
from orchestrator.job_search.cv.translation_en import (
    SKILL_TRANSLATIONS_EN,
    build_cv_html_en,
    translate_groupes_en,
    translate_location_en,
    translate_notions_en,
)

REF_CV_HTML_EN = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Old title</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Brussels, Belgium</b></div>
    </div>

    <h2>Skills</h2>
  <div class="grp">
    <div class="grp-label">AI &amp; LLM</div>
    <div class="grp-list">RAG</div>
  </div>

  <h2>Education</h2>
    <div class="edu">Fake degree</div>
  </div>
</body></html>
"""


class TestCritere6NomsDeGroupesEtPrefixeNotions:
    def test_trois_groupes_traduits(self):
        groupes = [
            SkillGroup(label="IA & LLM", items=[]),
            SkillGroup(label="Développement", items=[]),
            SkillGroup(label="Outils & méthodes", items=[]),
        ]
        out = translate_groupes_en(groupes)
        assert [g.label for g in out] == ["AI & LLM", "Development", "Tools & methods"]

    def test_prefixe_notions_basic_knowledge(self):
        html = build_cv_html_en(
            REF_CV_HTML_EN, "Titre", "Strasbourg, France", [], ["GraphQL"]
        )
        assert "Basic knowledge: GraphQL" in html
        assert "Notions en" not in html


class TestCritere7LesSeptCompetencesTraduites:
    def test_table_complete(self):
        attendu = {
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
        assert SKILL_TRANSLATIONS_EN == attendu

    def test_skill_dans_un_groupe_est_traduite(self):
        groupes = [SkillGroup(label="IA & LLM", items=["Systèmes agentiques", "SQL"])]
        out = translate_groupes_en(groupes)
        assert out[0].items == ["Agentic systems", "SQL"]

    def test_skill_dans_les_notions_est_traduite(self):
        notions = ["environnement cloud (AWS, Azure, Google Cloud)", "LiteLLM"]
        out = translate_notions_en(notions)
        assert out == ["cloud environments (AWS, Azure, Google Cloud)", "LiteLLM"]


class TestCritere8CompetenceAbsenteDeLaTableInchangee:
    def test_item_non_reference_identique(self):
        groupes = [SkillGroup(label="Développement", items=["Rust", "Elixir"])]
        out = translate_groupes_en(groupes)
        assert out[0].items == ["Rust", "Elixir"]

    def test_notion_non_reference_identique(self):
        assert translate_notions_en(["Kubernetes"]) == ["Kubernetes"]


class TestCritere9Localisation:
    def test_bruxelles_devient_brussels(self):
        assert translate_location_en("Bruxelles, Belgique") == "Brussels, Belgium"

    def test_strasbourg_inchange(self):
        assert translate_location_en("Strasbourg, France") == "Strasbourg, France"

    def test_autre_lieu_inchange(self):
        assert translate_location_en("Lyon, France") == "Lyon, France"


class TestCritere4ResteDuCvAnglaisInchange:
    def test_hors_role_lieu_competences_identique(self):
        groupes = [SkillGroup(label="IA & LLM", items=["Systèmes agentiques"])]
        html = build_cv_html_en(
            REF_CV_HTML_EN, "Mon titre", "Strasbourg, France", groupes, []
        )
        assert "Fake degree" in html
        assert "email@example.com" in html
        assert "+33 6 00 00 00 00" in html

    def test_titre_et_lieu_et_competences_substitues(self):
        groupes = [SkillGroup(label="IA & LLM", items=["Systèmes agentiques"])]
        html = build_cv_html_en(
            REF_CV_HTML_EN, "Mon titre", "Bruxelles, Belgique", groupes, []
        )
        assert '<div class="role">Mon titre</div>' in html
        assert "Old title" not in html
        assert "Brussels, Belgium" in html
        assert "Agentic systems" in html
        assert "<h2>Skills</h2>" in html
        assert "<h2>AI" not in html  # le header reste "Skills", pas le groupe


class TestParametrisationGenerateCvHtml:
    """`generate_cv_html` garde son comportement français par défaut (critère 25)."""

    def test_defaut_francais_inchange(self):
        ref = REF_CV_HTML_EN.replace("Skills", "Compétences").replace(
            "Education", "Formation"
        )
        groupes = [SkillGroup(label="Langages", items=["Python"])]
        html = generate_cv_html(ref, "Titre FR", "Strasbourg, France", groupes, ["Go"])
        assert "<h2>Compétences</h2>" in html
        assert "Notions en : Go" in html

    def test_headers_parametrables(self):
        groupes = [SkillGroup(label="AI & LLM", items=["Rust"])]
        html = generate_cv_html(
            REF_CV_HTML_EN,
            "Title",
            "Brussels, Belgium",
            groupes,
            ["GraphQL"],
            header_label="Skills",
            next_header_label="Education",
            notions_label="Basic knowledge:",
        )
        assert "<h2>Skills</h2>" in html
        assert "Basic knowledge: GraphQL" in html
