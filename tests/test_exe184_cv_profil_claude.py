"""Tests EXE-184 — le profil du CV (base ou écosystème Claude) se calcule en
Python sur les technos de l'offre et la fiche entreprise, jamais produit en
bloc par un modèle (critères 1-9, 12-14).

Aucun test n'appelle le modèle (contrainte du ticket) : `query` du SDK Claude
Agent est remplacé par un faux générateur async. Aucun test ne lit ni n'écrit
sous data/ : DB, CV de référence FR/EN et fichiers de profil sont des fichiers
tmp_path (H4, H8 du ticket).
"""

import asyncio
import json
import sqlite3

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.cv as api_cv
import api.db as api_db
import api.fiche as fiche_api
import orchestrator.job_search.cv.profil as cv_profil
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db

REF_CV_HTML_FR = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Ancien titre</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Strasbourg, France</b></div>
    </div>
    <section><h2 class="m">Profil</h2><p class="lead">Profil de base, inchangé.</p></section>

    <h2>Compétences</h2>
  <div class="grp">
    <div class="grp-label">Langages</div>
    <div class="grp-list">Python · SQL</div>
  </div>

  <h2>Formation</h2>
    <div class="edu">Diplôme fictif</div>
  </div>
</body></html>
"""

REF_CV_HTML_EN = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Old title</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Strasbourg, France</b></div>
    </div>
    <section><h2 class="m">Profile</h2><p class="lead">Base profile, unchanged.</p></section>

    <h2>Skills</h2>
  <div class="grp">
    <div class="grp-label">Languages</div>
    <div class="grp-list">Python · SQL</div>
  </div>

  <h2>Education</h2>
    <div class="edu">Fake degree</div>
  </div>
</body></html>
"""

PROFIL_CLAUDE_FR = "Je travaille chaque jour avec Claude et son écosystème."
PROFIL_CLAUDE_EN = "I work every day with the Claude ecosystem."

PROFILE_YAML = """
profile_id: test
role_ceiling: ic
skills:
  python: {level: 6, desire: 8}
zones:
  strasbourg_area:
    insee: []
    dept: []
    keywords: ["strasbourg"]
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: [remote]
  contract_types: [cdi]
"""


def _fake_result(structured_output=None, is_error=False, result=None):
    return ResultMessage(
        subtype="success" if not is_error else "error_during_execution",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="fake-session",
        total_cost_usd=0.01,
        result=result,
        structured_output=structured_output,
    )


def _make_query(behavior):
    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _run_cv(monkeypatch, offer_id, model_groups=None):
    def behavior(prompt, options):
        return [_fake_result(structured_output={"groupes": model_groups or []})]

    monkeypatch.setattr(cv_service, "query", _make_query(behavior))
    asyncio.run(cv_service.run_cv(offer_id))


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def cv_fixture_paths(tmp_path, monkeypatch):
    ref = tmp_path / "cv_reference.html"
    ref.write_text(REF_CV_HTML_FR, encoding="utf-8")
    ref_en = tmp_path / "cv_reference_en.html"
    ref_en.write_text(REF_CV_HTML_EN, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML, encoding="utf-8")
    profil_claude_fr = tmp_path / "profil_claude.fr.txt"
    profil_claude_fr.write_text(PROFIL_CLAUDE_FR, encoding="utf-8")
    profil_claude_en = tmp_path / "profil_claude.en.txt"
    profil_claude_en.write_text(PROFIL_CLAUDE_EN, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "CV_REFERENCE_EN_PATH", ref_en)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_FR_PATH", profil_claude_fr)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_CLAUDE_EN_PATH", profil_claude_en)
    return ref, ref_en, profile, profil_claude_fr, profil_claude_en


def _insert_offer(
    db_path, offer_id, techs=None, verdict="retenu", ad_language=None, title="Titre H/F"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, location, "
            "extracted_facts_json, ad_language) VALUES (?, 'test', ?, 'fp', ?, "
            "'Strasbourg', ?, ?)",
            (
                offer_id,
                str(offer_id),
                title,
                json.dumps({"techs_required": techs or []}),
                ad_language,
            ),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-16')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, statut="done", presentation=None, points=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "created_at) VALUES (?, ?, ?, ?, '2026-10-16')",
            (offer_id, statut, presentation, json.dumps(points or [])),
        )
        conn.commit()
    finally:
        conn.close()


def _cvs_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


class TestCritere1TechsDeLOffreCitentClaude:
    @pytest.mark.parametrize("name", ["claude", "Claude Code", "CLAUDE AGENT SDK"])
    def test_profil_claude_quelle_que_soit_la_casse(
        self, db_path, cv_fixture_paths, monkeypatch, name
    ):
        offer_id = 1
        _insert_offer(
            db_path, offer_id, techs=[{"name": name, "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "technos_offre"
        assert PROFIL_CLAUDE_FR in row["html"]
        assert "Profil de base, inchangé." not in row["html"]


class TestCritere2VersionAnglaiseMemeProfil:
    def test_cv_anglais_porte_aussi_le_profil_claude(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _insert_offer(
            db_path,
            offer_id,
            techs=[{"name": "claude", "importance": "required"}],
            ad_language="en",
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["en_html"] is not None
        assert PROFIL_CLAUDE_EN in row["en_html"]
        assert "Base profile, unchanged." not in row["en_html"]


class TestCritere3FicheEntrepriseCiteClaude:
    def test_presentation_cite_claude(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 3
        _insert_offer(db_path, offer_id, techs=[])
        _insert_fiche(db_path, offer_id, presentation="Entreprise experte de Claude.")
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "fiche_entreprise"

    def test_position_ou_citation_d_un_point_cite_claude(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id, techs=[])
        _insert_fiche(
            db_path,
            offer_id,
            presentation="Présentation neutre.",
            points=[{"position": "Utilise Claude en interne", "citation": None}],
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "fiche_entreprise"

    def test_fiche_non_terminee_ne_compte_pas(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id, techs=[])
        _insert_fiche(
            db_path, offer_id, statut="pending", presentation="Claude partout."
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "base"
        assert row["profil_motif"] == "aucune_mention"


class TestCritere4ClaudeHorsPerimetreNeDeclencheRien:
    def test_manques_alertes_sources_prompt_text_ignores(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id, techs=[])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "manques_json, alertes_json, sources_json, points_json, created_at) "
            "VALUES (?, 'done', 'Rien à voir.', ?, ?, ?, '[]', '2026-10-16')",
            (
                offer_id,
                json.dumps(["Claude"]),
                json.dumps(["mention de Claude en alerte"]),
                json.dumps([{"titre": "Claude", "url": "https://example.com"}]),
            ),
        )
        conn.commit()
        conn.close()
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "base"
        assert row["profil_motif"] == "aucune_mention"


class TestCritere5SansMentionProfilDeBase:
    def test_profil_de_base_inchange(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 7
        _insert_offer(
            db_path, offer_id, techs=[{"name": "python", "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "base"
        assert row["profil_motif"] == "aucune_mention"
        assert "Profil de base, inchangé." in row["html"]


class TestCritere6TexteDuFichierMotPourMot:
    def test_texte_francais_identique_au_fichier(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _insert_offer(
            db_path, offer_id, techs=[{"name": "claude", "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert f'<p class="lead">{PROFIL_CLAUDE_FR}</p>' in row["html"]


class TestCritere7FicheTermineeApresLeCvBascule:
    def test_fiche_citant_claude_fait_passer_les_deux_versions(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)
        assert _cvs_row(db_path, offer_id)["profil"] == "base"

        _insert_fiche(db_path, offer_id, presentation="Nous adorons Claude.")

        with api_db.get_conn() as conn:
            cv_service.recalc_profile_after_fiche(conn, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "fiche_entreprise"
        assert PROFIL_CLAUDE_FR in row["html"]
        assert PROFIL_CLAUDE_EN in row["en_html"]


class TestCritere8MarquePreteEffacee:
    def test_la_marque_prete_s_efface_quand_la_fiche_bascule_le_profil(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        import api.pieces as api_pieces

        offer_id = 10
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        api_pieces.set_cv_pret(offer_id, api_pieces.MarquePretIn(pret=True))
        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "prete"

        _insert_fiche(db_path, offer_id, presentation="On utilise Claude.")
        with api_db.get_conn() as conn:
            cv_service.recalc_profile_after_fiche(conn, offer_id)

        assert api_pieces.get_pieces(offer_id)["cv"]["statut"] == "en_cours"


class TestCritere9FicheSansClaudeOuEnErreurNeChangeRien:
    def test_fiche_sans_mention_ne_change_rien(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        html_avant = _cvs_row(db_path, offer_id)["html"]

        _insert_fiche(db_path, offer_id, presentation="Rien à voir.")
        with api_db.get_conn() as conn:
            cv_service.recalc_profile_after_fiche(conn, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "base"
        assert row["html"] == html_avant

    def test_fiche_en_erreur_ne_change_rien(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        _insert_fiche(
            db_path, offer_id, statut="error", presentation="On utilise Claude."
        )
        with api_db.get_conn() as conn:
            cv_service.recalc_profile_after_fiche(conn, offer_id)

        assert _cvs_row(db_path, offer_id)["profil"] == "base"


class TestCritere12ChangementManuel:
    def test_les_deux_versions_changent_motif_choisi_a_la_main(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 13
        _insert_offer(db_path, offer_id, techs=[], ad_language="en")
        _run_cv(monkeypatch, offer_id)

        result = api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))
        assert result["profil"] == "claude"
        assert result["profil_motif_libelle"] == "choisi à la main"
        assert PROFIL_CLAUDE_FR in result["html"]
        assert PROFIL_CLAUDE_EN in result["en_html"]

        row = _cvs_row(db_path, offer_id)
        assert row["profil_motif"] == "manuel"


class TestCritere13ChoixManuelSurvit:
    def test_survit_a_la_fin_de_la_fiche(self, db_path, cv_fixture_paths, monkeypatch):
        offer_id = 14
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))

        _insert_fiche(db_path, offer_id, statut="done", presentation="Rien sur Claude.")
        with api_db.get_conn() as conn:
            cv_service.recalc_profile_after_fiche(conn, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "manuel"

    def test_survit_a_une_correction_de_competence(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))

        result = api_cv.correct_cv_skill(
            offer_id,
            api_cv.SkillCorrectionIn(
                action="ajout", competence="Rust", maitrisee=True, groupe="Langages"
            ),
        )
        assert PROFIL_CLAUDE_FR in result["html"]
        assert _cvs_row(db_path, offer_id)["profil_motif"] == "manuel"

    def test_survit_a_un_changement_de_titre(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 16
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))

        result = api_cv.put_cv_titre(offer_id, api_cv.CvTitreIn(titre="Nouveau titre"))
        assert PROFIL_CLAUDE_FR in result["html"]
        assert _cvs_row(db_path, offer_id)["profil_motif"] == "manuel"

    def test_survit_a_une_relance_de_la_generation(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 17
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))

        _run_cv(monkeypatch, offer_id)
        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "manuel"
        assert PROFIL_CLAUDE_FR in row["html"]


class TestCritere14FichierDuProfilAbsent:
    def test_sans_fichier_francais_le_cv_part_en_erreur_message_nomme_le_fichier(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        profil_claude_fr_path = cv_fixture_paths[3]
        profil_claude_fr_path.unlink()

        offer_id = 18
        _insert_offer(
            db_path, offer_id, techs=[{"name": "claude", "importance": "required"}]
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "error"
        assert row["html"] is None
        assert str(profil_claude_fr_path) in row["error_message"]

    def test_sans_fichier_anglais_seul_l_anglais_est_bloque(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        profil_claude_en_path = cv_fixture_paths[4]
        profil_claude_en_path.unlink()

        offer_id = 19
        _insert_offer(
            db_path,
            offer_id,
            techs=[{"name": "claude", "importance": "required"}],
            ad_language="en",
        )
        _run_cv(monkeypatch, offer_id)

        row = _cvs_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["html"] is not None
        assert row["en_html"] is None
        assert str(profil_claude_en_path) in row["en_error_message"]

    def test_bouton_manuel_refuse_si_fichier_absent_rien_ne_change(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        profil_claude_fr_path = cv_fixture_paths[3]

        offer_id = 20
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)
        html_avant = _cvs_row(db_path, offer_id)["html"]

        profil_claude_fr_path.unlink()
        with pytest.raises(HTTPException) as exc_info:
            api_cv.put_cv_profil(offer_id, api_cv.CvProfilIn(profil="claude"))
        assert exc_info.value.status_code == 409

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "base"
        assert row["html"] == html_avant


class TestWiringFicheApiAppelleLeRecalcul:
    """Vérifie que `api/fiche.py::_generate` appelle bien le recalcul de
    profil à la fin de la fiche (critère 7), sans passer par le SDK."""

    def test_fin_de_fiche_declenche_le_recalcul_sans_lettre(
        self, db_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 21
        _insert_offer(db_path, offer_id, techs=[])
        _run_cv(monkeypatch, offer_id)

        async def _fake_run_fiche(oid):
            with api_db.get_conn() as conn:
                conn.execute(
                    "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
                    "points_json, created_at) VALUES (?, 'done', 'Expert Claude.', "
                    "'[]', '2026-10-16')",
                    (oid,),
                )
                conn.commit()

        async def _fake_lettre(oid):
            return None

        monkeypatch.setattr(fiche_api, "run_fiche", _fake_run_fiche)
        monkeypatch.setattr(
            fiche_api.lettre_api, "launch_lettre_if_ready", _fake_lettre
        )

        asyncio.run(fiche_api._generate(offer_id))

        row = _cvs_row(db_path, offer_id)
        assert row["profil"] == "claude"
        assert row["profil_motif"] == "fiche_entreprise"
