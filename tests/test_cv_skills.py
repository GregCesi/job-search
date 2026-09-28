"""Tests EXE-58 — calculs Python purs du module cv/skills.py (critères 3 à 21).

Niveaux profil et mappings d'alias repris de H8 (ticket EXE-58) : python=6, sql=6,
llm=5, rag=6, csharp=5, dotnet=5, rest=8, ci_cd=4, docker=7, vector_database=6,
embeddings=5, make=4, kubernetes=3, json=9 ; generative ai→llm, api/rest→rest_api,
c#→csharp, .net→dotnet, ci/cd→ci_cd, cloud exclu. `profiles/alias.yaml` est lu tel
quel (versionné, jamais modifié) ; `profiles/gregoire.yaml` n'est pas versionné,
le profil de test est construit en mémoire.
"""

from orchestrator.job_search.cv.skills import (
    Addition,
    SkillGroup,
    block_canonicals,
    clean_title,
    compute_au_cv,
    compute_permitted_additions,
    compute_requested_missing,
    detect_location,
    filter_model_groups,
    generate_cv_html,
    parse_reference_block,
)
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.paths import ALIAS_PATH
from orchestrator.job_search.scoring.aliases import load_alias_table

ALIAS_TABLE = load_alias_table(ALIAS_PATH)


def _profile(**skills_levels: int) -> Profile:
    skills = {name: {"level": lvl, "desire": 5} for name, lvl in skills_levels.items()}
    return Profile.model_validate(
        {
            "profile_id": "test",
            "role_ceiling": "ic",
            "skills": skills,
            "zones": {
                "strasbourg_area": {
                    "insee": [],
                    "dept": [],
                    "keywords": ["strasbourg", "bas-rhin"],
                },
                "belgique_area": {
                    "insee": [],
                    "dept": [],
                    "keywords": ["belgique", "belgium", "bruxelles", "brussels"],
                },
            },
            "search_criteria": {
                "keywords": ["python"],
                "domains": ["backend"],
                "locations": ["remote"],
                "contract_types": ["cdi"],
            },
        }
    )


# H8 : niveaux du profil au 28 septembre 2026, repris tels quels dans le ticket.
H8_PROFILE = _profile(
    python=6,
    sql=6,
    llm=5,
    rag=6,
    csharp=5,
    dotnet=5,
    rest=8,
    ci_cd=4,
    docker=7,
    vector_database=6,
    embeddings=5,
    make=4,
    kubernetes=3,
    json=9,
)


def _techs(*names: str) -> list[dict]:
    return [{"name": n, "importance": "required"} for n in names]


# CV de test « de même structure » que data/cv/cv_reference.html (non versionné) —
# 3 groupes de 11/10/9 items = 30 compétences (critère 7), un item composé par
# parenthèses et un par slash (H3), 3 notions dont une composée (critère 8).
REF_CV_HTML = """<!doctype html>
<html>
<body>
  <div class="page">
    <div class="role">Ancien titre</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Bruxelles, Belgique</b></div>
    </div>

    <h2>Compétences</h2>
  <div class="grp">
    <div class="grp-label">Langages &amp; Frameworks</div>
    <div class="grp-list">Python (FastAPI, Pydantic) · SQL / SQLite · Vue.js · RAG · C# · CI/CD · Docker · Git · Linux · Bash · HTML/CSS</div>
  </div>
  <div class="grp">
    <div class="grp-label">Data &amp; IA</div>
    <div class="grp-list">Pandas · NumPy · Scikit-learn · Jupyter · ETL · Airflow · Spark · Kafka · Redis · Elasticsearch</div>
  </div>
  <div class="grp">
    <div class="grp-label">Pratiques &amp; Outils</div>
    <div class="grp-list">Agile/Scrum · TDD · Jenkins · GitHub Actions · Terraform · Prometheus · Grafana · Monitoring · Documentation</div>
  </div>
  <div class="grp-notions">Notions en : environnement cloud (AWS, Azure), Svelte, GraphQL</div>

  <h2>Formation</h2>
    <div class="edu">Diplôme fictif — Université fictive</div>
  </div>
</body>
</html>
"""

_THIRTEEN_TECHS = _techs(
    "python",
    "sql",
    "generative ai",
    "llm",
    "rag",
    "c#",
    ".net",
    "api",
    "ci/cd",
    "docker",
    "cloud",
    "vector database",
    "embeddings",
)


class TestCleanTitle:
    def test_critere_3_trailing_h_f_sans_parentheses(self):
        raw = "Développeur Web Fullstack Python / FastAPI / VueJS H/F"
        assert clean_title(raw) == "Développeur Web Fullstack Python / FastAPI / VueJS"

    def test_critere_4_h_f_entre_parentheses(self):
        raw = "Consultant Technique IA Générative / AI Automation Engineer (H/F)"
        assert (
            clean_title(raw)
            == "Consultant Technique IA Générative / AI Automation Engineer"
        )


class TestDetectLocation:
    def test_critere_5_zone_belgique(self):
        assert (
            detect_location("Bruxelles (Belgique)", H8_PROFILE) == "Bruxelles, Belgique"
        )

    def test_critere_6_zone_strasbourg(self):
        assert detect_location("Strasbourg (67)", H8_PROFILE) == "Strasbourg, France"


class TestParseReferenceBlock:
    def test_critere_7_groupes_11_10_9(self):
        ref = parse_reference_block(REF_CV_HTML)
        assert [len(g.items) for g in ref.groupes] == [11, 10, 9]
        assert sum(len(g.items) for g in ref.groupes) == 30

    def test_critere_8_notions_environnement_cloud_un_seul_item(self):
        ref = parse_reference_block(REF_CV_HTML)
        assert ref.notions == [
            "environnement cloud (AWS, Azure)",
            "Svelte",
            "GraphQL",
        ]


class TestComputePermittedAdditions:
    def _covered(self):
        ref = parse_reference_block(REF_CV_HTML)
        return ref, block_canonicals(ref.groupes, ref.notions, ALIAS_TABLE)

    def test_critere_9_aucun_ajout(self):
        _ref, covered = self._covered()
        techs = _techs("python", "fastapi", "vuejs", "rest")
        additions = compute_permitted_additions(
            techs, H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert additions == []

    def test_critere_10_exactement_trois_ajouts(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _THIRTEEN_TECHS, H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert sorted(a.raw_name for a in additions) == sorted(
            [".net", "vector database", "embeddings"]
        )

    def test_critere_11_ni_generative_ai_ni_llm_ni_api(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _THIRTEEN_TECHS, H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        raw_names = {a.raw_name for a in additions}
        assert "generative ai" not in raw_names
        assert "llm" not in raw_names
        assert "api" not in raw_names

    def test_critere_12_json_non_ajoute(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _techs("json"), H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert additions == []

    def test_critere_13_make_ajoute_niveau_4(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _techs("make"), H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert [a.raw_name for a in additions] == ["make"]

    def test_critere_14_kubernetes_non_ajoute_niveau_3(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _techs("kubernetes"), H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert additions == []

    def test_critere_15_webhooks_absent_du_profil(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _techs("webhooks"), H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        assert additions == []

    def test_critere_16_seuil_6_sans_toucher_au_code(self):
        _ref, covered = self._covered()
        additions = compute_permitted_additions(
            _THIRTEEN_TECHS, H8_PROFILE, ALIAS_TABLE, covered, 6
        )
        assert {a.raw_name for a in additions} == {"vector database"}


class TestFilterModelGroups:
    def test_critere_7_items_origine_restent_dans_leur_groupe_meme_deplaces(self):
        ref = parse_reference_block(REF_CV_HTML)
        # Le modèle renvoie "RAG" déplacé du groupe 1 vers le groupe 2.
        model_groups = [
            SkillGroup(
                label=ref.groupes[0].label,
                items=[i for i in ref.groupes[0].items if i != "RAG"],
            ),
            SkillGroup(
                label=ref.groupes[1].label, items=[*ref.groupes[1].items, "RAG"]
            ),
            SkillGroup(label=ref.groupes[2].label, items=list(ref.groupes[2].items)),
        ]
        final = filter_model_groups(ref.groupes, model_groups, additions=[])
        assert final[0].items == ref.groupes[0].items
        assert final[1].items == ref.groupes[1].items
        assert final[2].items == ref.groupes[2].items
        assert sum(len(g.items) for g in final) == 30

    def test_critere_17_item_invente_par_le_modele_ignore(self):
        ref = parse_reference_block(REF_CV_HTML)
        model_groups = [
            SkillGroup(
                label=ref.groupes[0].label, items=[*ref.groupes[0].items, "Rust"]
            ),
            *[SkillGroup(label=g.label, items=list(g.items)) for g in ref.groupes[1:]],
        ]
        final = filter_model_groups(ref.groupes, model_groups, additions=[])
        assert "Rust" not in final[0].items
        assert len(final[0].items) == len(ref.groupes[0].items)

    def test_critere_18_ajout_permis_omis_par_le_modele(self):
        ref = parse_reference_block(REF_CV_HTML)
        additions = [Addition(raw_name="make", canonical="make")]
        # Le modèle ne place l'ajout autorisé dans aucun groupe.
        model_groups = [
            SkillGroup(label=g.label, items=list(g.items)) for g in ref.groupes
        ]
        final = filter_model_groups(ref.groupes, model_groups, additions)
        present = block_canonicals(final, ref.notions, ALIAS_TABLE)
        assert "make" not in present
        missing = compute_requested_missing(_techs("make"), ALIAS_TABLE, present)
        assert "make" in missing


class TestAuCvEtDemandeSansYEtre:
    def test_critere_19_au_cv_groupe_par_groupe_plus_notions(self):
        ref = parse_reference_block(REF_CV_HTML)
        au_cv = compute_au_cv(ref.groupes, ref.notions)
        expected = [i for g in ref.groupes for i in g.items] + list(ref.notions)
        assert au_cv == expected

    def test_critere_20_demande_sans_y_etre_contient_cloud_disjoint_du_cv(self):
        ref = parse_reference_block(REF_CV_HTML)
        covered = block_canonicals(ref.groupes, ref.notions, ALIAS_TABLE)
        additions = compute_permitted_additions(
            _THIRTEEN_TECHS, H8_PROFILE, ALIAS_TABLE, covered, 4
        )
        model_groups = [
            SkillGroup(
                label=ref.groupes[0].label,
                items=[*ref.groupes[0].items, *[a.raw_name for a in additions]],
            ),
            *[SkillGroup(label=g.label, items=list(g.items)) for g in ref.groupes[1:]],
        ]
        final = filter_model_groups(ref.groupes, model_groups, additions)
        present = block_canonicals(final, ref.notions, ALIAS_TABLE)
        missing = compute_requested_missing(_THIRTEEN_TECHS, ALIAS_TABLE, present)
        au_cv = set(compute_au_cv(final, ref.notions))

        assert "cloud" in missing
        assert not (set(missing) & au_cv)


class TestGenerateCvHtml:
    def test_critere_21_reste_identique_hors_titre_localisation_competences(self):
        ref = parse_reference_block(REF_CV_HTML)
        out = generate_cv_html(
            REF_CV_HTML, "Nouveau titre", "Nouvelle ville", ref.groupes, ref.notions
        )

        head_ref = REF_CV_HTML.split('<div class="role">', 1)[0]
        head_out = out.split('<div class="role">', 1)[0]
        assert head_ref == head_out

        tail_ref = REF_CV_HTML.split("<h2>Formation</h2>", 1)[1]
        tail_out = out.split("<h2>Formation</h2>", 1)[1]
        assert tail_ref == tail_out

        # Les lignes Contact non-localisation (email, téléphone) sont inchangées.
        assert '<div class="row"><b>email@example.com</b></div>' in out
        assert '<div class="row"><b>+33 6 00 00 00 00</b></div>' in out

    def test_titre_et_localisation_substitues(self):
        ref = parse_reference_block(REF_CV_HTML)
        out = generate_cv_html(
            REF_CV_HTML, "Nouveau titre", "Nouvelle ville", ref.groupes, ref.notions
        )
        assert '<div class="role">Nouveau titre</div>' in out
        assert "Nouvelle ville" in out
        assert "Bruxelles, Belgique" not in out
