"""Tests EXE-102 — PDF téléchargeables du CV et de la lettre d'une offre retenue,
avec un nom de fichier prêt à envoyer.

Aucun test n'appelle un modèle ni le réseau : les générations CV/lettre sont soit
simulées par insertion SQL directe (`statut='done'`), soit produites par les
fonctions de service réelles avec `query` du SDK Claude Agent monkeypatché (même
convention que test_exe101_statut_piece.py). Aucun test ne lit ni n'écrit sous
data/ : DB, coordonnées et liste d'intermédiaires sont toutes sous `tmp_path`.
Le rendu PDF (Playwright/Chromium) est local, sans réseau — c'est la seule partie
non substituée, car l'objet des critères porte sur le PDF produit.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.cv as api_cv
import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.cv.service as cv_service
import orchestrator.job_search.fiche.intermediaires as intermediaires_module
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.pdf.filename import sanitize_part
from orchestrator.job_search.storage.db import init_db
from tests.pdf_inspect import extract_text, is_a4, page_count

# ---------------------------------------------------------------------------
# Fixtures communes (mêmes conventions que test_exe101_statut_piece.py)
# ---------------------------------------------------------------------------


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
def coordonnees_path(tmp_path, monkeypatch):
    path = tmp_path / "coordonnees.txt"
    path.write_text(
        "nom: Grégoire Marchand\n"
        "mail: gregoire@example.com\n"
        "telephone: +33 6 00 00 00 00\n"
        "ville: Strasbourg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", path)
    return path


@pytest.fixture
def intermediaires_path(tmp_path, monkeypatch):
    path = tmp_path / "intermediaires.yaml"
    path.write_text(
        "intermediaires:\n  - EDITX BV\n  - Mercato de l'emploi\n", encoding="utf-8"
    )
    monkeypatch.setattr(intermediaires_module, "INTERMEDIAIRES_PATH", path)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(db_path, offer_id, verdict="retenu", title="Titre", company=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, 'Texte de l offre')",
            (offer_id, str(offer_id), title, company),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, ?)",
                (offer_id, verdict, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_cv_done(db_path, offer_id, html, titre="Titre"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, html, titre, created_at) "
            "VALUES (?, 'done', ?, ?, ?)",
            (offer_id, html, titre, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre_done(db_path, offer_id, texte):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, texte, created_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, texte, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, employeur_nom=None, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, employeur_nom, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, employeur_nom, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _fake_result(result=None, structured_output=None):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
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


REF_CV_HTML = """<!doctype html>
<html><body>
  <div class="page">
    <div class="role">Ancien titre</div>
    <div class="contact">
      <div class="row"><b>email@example.com</b></div>
      <div class="row"><b>+33 6 00 00 00 00</b></div>
      <div class="row"><b>Strasbourg, France</b></div>
    </div>
    <h2>Compétences</h2>
  <div class="grp">
    <div class="grp-label">Langages</div>
    <div class="grp-list">Python · SQL</div>
  </div>
  <div class="grp-notions">Notions en : GraphQL</div>
  <h2>Formation</h2>
    <div class="edu">Diplôme fictif</div>
  </div>
</body></html>
"""

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


@pytest.fixture
def cv_fixture_paths(tmp_path, monkeypatch):
    ref = tmp_path / "cv_reference.html"
    ref.write_text(REF_CV_HTML, encoding="utf-8")
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML, encoding="utf-8")
    monkeypatch.setattr(cv_service, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_service, "PROFILE_PATH", profile)
    return ref, profile


def _run_cv(monkeypatch, offer_id):
    monkeypatch.setattr(
        cv_service,
        "query",
        _make_query(lambda p, o: [_fake_result(structured_output={"groupes": []})]),
    )
    asyncio.run(cv_service.run_cv(offer_id))


LETTRE_PARAGRAPHE = (
    "Je vous écris pour vous faire part de mon vif intérêt pour ce poste, qui "
    "correspond à mon projet professionnel et à mes compétences techniques."
)


def _lettre_texte(nb_paragraphes=1):
    return "\n\n".join([LETTRE_PARAGRAPHE] * nb_paragraphes)


# ---------------------------------------------------------------------------
# Critère 1 — PDF du CV au format A4
# ---------------------------------------------------------------------------


class TestCritere1CvPdfA4:
    def test_cv_pdf_offre_retenue_est_a4(
        self, db_path, coordonnees_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id, company="SFEIR")
        _run_cv(monkeypatch, offer_id)
        response = api_cv.get_cv_pdf(offer_id)
        assert response.media_type == "application/pdf"
        assert response.body[:5] == b"%PDF-"
        assert is_a4(response.body)


# ---------------------------------------------------------------------------
# Critère 2 — texte extractible : titre + chaque compétence
# ---------------------------------------------------------------------------


class TestCritere2CvTexteExtractible:
    def test_texte_contient_titre_et_competences(
        self, db_path, coordonnees_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _run_cv(monkeypatch, offer_id)
        response = api_cv.get_cv_pdf(offer_id)
        text = extract_text(response.body)
        assert "Ingénieur IA" in text
        assert "Python" in text
        assert "SQL" in text
        assert "GraphQL" in text


# ---------------------------------------------------------------------------
# Critère 3 — compétence ajoutée puis redemandée
# ---------------------------------------------------------------------------


class TestCritere3AjoutCompetenceVisibleDansPdf:
    def test_competence_ajoutee_apparait_dans_le_pdf(
        self, db_path, coordonnees_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id, company="SFEIR")
        _run_cv(monkeypatch, offer_id)
        with api_db.get_conn() as conn:
            cv_service.apply_correction(
                conn, offer_id, "ajout", "Rust", maitrisee=True, groupe="Langages"
            )
        response = api_cv.get_cv_pdf(offer_id)
        text = extract_text(response.body)
        assert "Rust" in text


# ---------------------------------------------------------------------------
# Critère 4 — nom de fichier du CV
# ---------------------------------------------------------------------------


class TestCritere4NomFichierCv:
    def test_nom_fichier_cv_gregoire_marchand_sfeir(
        self, db_path, coordonnees_path, cv_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id, company="SFEIR")
        _run_cv(monkeypatch, offer_id)
        response = api_cv.get_cv_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert 'filename="CV_Gregoire_Marchand_SFEIR.pdf"' in disposition


# ---------------------------------------------------------------------------
# Critère 5 — PDF de la lettre au format A4
# ---------------------------------------------------------------------------


class TestCritere5LettrePdfA4:
    def test_lettre_pdf_offre_retenue_est_a4(self, db_path, coordonnees_path):
        offer_id = 5
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        assert response.media_type == "application/pdf"
        assert response.body[:5] == b"%PDF-"
        assert is_a4(response.body)


# ---------------------------------------------------------------------------
# Critère 6 — contenu dans l'ordre : coordonnées, date, objet, texte, nom
# ---------------------------------------------------------------------------


class TestCritere6ContenuDansLOrdre:
    def test_ordre_coordonnees_date_objet_texte_nom(self, db_path, coordonnees_path):
        offer_id = 6
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        text = extract_text(response.body)

        i_nom = text.index("Grégoire Marchand")
        i_mail = text.index("gregoire@example.com")
        i_tel = text.index("+33 6 00 00 00 00")
        i_ville = text.index("Strasbourg")
        i_date_line = text.index("Strasbourg, le")
        i_objet = text.index("Objet : candidature au poste de Ingénieur IA")
        i_texte = text.index(LETTRE_PARAGRAPHE[:30])
        i_nom_fin = text.rindex("Grégoire Marchand")

        assert i_nom < i_mail < i_tel < i_ville < i_date_line < i_objet < i_texte
        assert i_nom_fin > i_texte  # le nom réapparaît après le texte (signature)


# ---------------------------------------------------------------------------
# Critère 7 — paragraphes distincts, ordre, mots intacts
# ---------------------------------------------------------------------------


class TestCritere7ParagraphesDistinctsEtIntacts:
    def test_paragraphes_dans_l_ordre_sans_alteration(self, db_path, coordonnees_path):
        offer_id = 7
        para1 = "Premier paragraphe avec un mot bien précis : xylophone."
        para2 = "Second paragraphe, distinct, avec un autre mot : trampoline."
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, f"{para1}\n\n{para2}")
        response = api_lettre.get_lettre_pdf(offer_id)
        text = extract_text(response.body)
        assert para1 in text
        assert para2 in text
        assert text.index(para1) < text.index(para2)


# ---------------------------------------------------------------------------
# Critère 8 — 400 mots tiennent sur une page
# ---------------------------------------------------------------------------


class TestCritere8QuatreCentMotsUnePage:
    def test_400_mots_tiennent_sur_une_page(self, db_path, coordonnees_path):
        offer_id = 8
        mots = ["mot"] * 400
        paragraphes = [" ".join(mots[i : i + 100]) for i in range(0, 400, 100)]
        texte = "\n\n".join(paragraphes)
        assert len(texte.split()) == 400
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, texte)
        response = api_lettre.get_lettre_pdf(offer_id)
        assert page_count(response.body) == 1


# ---------------------------------------------------------------------------
# Critère 9 — texte modifié puis redemandé
# ---------------------------------------------------------------------------


class TestCritere9TexteModifieVisibleDansPdf:
    def test_texte_modifie_apparait_dans_le_pdf(self, db_path, coordonnees_path):
        offer_id = 9
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, "Texte initial.")
        with api_db.get_conn() as conn:
            lettre_service.save_texte(conn, offer_id, "Texte modifié à la main.")
        response = api_lettre.get_lettre_pdf(offer_id)
        text = extract_text(response.body)
        assert "Texte modifié à la main." in text
        assert "Texte initial." not in text


# ---------------------------------------------------------------------------
# Critère 10 — nom de fichier de la lettre
# ---------------------------------------------------------------------------


class TestCritere10NomFichierLettre:
    def test_nom_fichier_lettre_gregoire_marchand_sfeir(
        self, db_path, coordonnees_path
    ):
        offer_id = 10
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert 'filename="Lettre_Gregoire_Marchand_SFEIR.pdf"' in disposition


# ---------------------------------------------------------------------------
# Critère 11 — entreprise du nom de fichier = celle de l'offre
# ---------------------------------------------------------------------------


class TestCritere11EntrepriseDeLOffre:
    def test_entreprise_fintensy_nv(self, db_path, coordonnees_path):
        offer_id = 11
        _insert_offer(db_path, offer_id, company="FINTENSY NV")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert 'filename="Lettre_Gregoire_Marchand_FINTENSY_NV.pdf"' in disposition


# ---------------------------------------------------------------------------
# Critère 12 — intermédiaire connu → employeur de la fiche
# ---------------------------------------------------------------------------


class TestCritere12IntermediaireUtiliseLaFiche:
    def test_editx_bv_devient_proximus_ada(
        self, db_path, coordonnees_path, intermediaires_path
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id, company="EDITX BV")
        _insert_fiche(db_path, offer_id, employeur_nom="Proximus Ada")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert 'filename="Lettre_Gregoire_Marchand_Proximus_Ada.pdf"' in disposition

    def test_company_vide_utilise_la_fiche(
        self, db_path, coordonnees_path, intermediaires_path
    ):
        offer_id = 120
        _insert_offer(db_path, offer_id, company=None)
        _insert_fiche(db_path, offer_id, employeur_nom="Proximus Ada")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert 'filename="Lettre_Gregoire_Marchand_Proximus_Ada.pdf"' in disposition


# ---------------------------------------------------------------------------
# Critère 13 — ni offre ni fiche utilisable → intitulé de l'offre
# ---------------------------------------------------------------------------


class TestCritere13AucuneEntrepriseUtilisable:
    def test_repli_sur_intitule_offre(
        self, db_path, coordonnees_path, intermediaires_path
    ):
        offer_id = 13
        _insert_offer(
            db_path, offer_id, title="Data Engineer Senior", company="EDITX BV"
        )
        _insert_fiche(db_path, offer_id, employeur_nom=None)
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        disposition = response.headers["content-disposition"]
        assert (
            'filename="Lettre_Gregoire_Marchand_Data_Engineer_Senior.pdf"'
            in disposition
        )


# ---------------------------------------------------------------------------
# Critère 14 — assainissement du nom de fichier
# ---------------------------------------------------------------------------


class TestCritere14Assainissement:
    def test_mercato_de_l_emploi(self):
        assert sanitize_part("Mercato de l'emploi") == "Mercato_de_l_emploi"

    def test_accents_retires(self):
        assert sanitize_part("Société Générale") == "Societe_Generale"

    def test_pas_de_underscore_de_bord(self):
        assert sanitize_part("  (Test)  ") == "Test"


# ---------------------------------------------------------------------------
# Critère 15 — fichier de coordonnées absent
# ---------------------------------------------------------------------------


class TestCritere15CoordonneesAbsentes:
    def test_cv_refuse_sans_coordonnees(
        self, db_path, tmp_path, monkeypatch, cv_fixture_paths
    ):
        offer_id = 150
        missing = tmp_path / "absent" / "coordonnees.txt"
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", missing)
        _insert_offer(db_path, offer_id, company="SFEIR")
        _run_cv(monkeypatch, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            api_cv.get_cv_pdf(offer_id)
        assert str(missing) in exc_info.value.detail

    def test_lettre_refuse_sans_coordonnees(self, db_path, tmp_path, monkeypatch):
        offer_id = 151
        missing = tmp_path / "absent" / "coordonnees.txt"
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", missing)
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        with pytest.raises(HTTPException) as exc_info:
            api_lettre.get_lettre_pdf(offer_id)
        assert str(missing) in exc_info.value.detail


# ---------------------------------------------------------------------------
# Critère 16 — offre non retenue, ou pièce non générée
# ---------------------------------------------------------------------------


class TestCritere16Refus:
    def test_cv_pdf_offre_non_retenue(self, db_path, coordonnees_path):
        offer_id = 160
        _insert_offer(db_path, offer_id, verdict="rejete", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_cv.get_cv_pdf(offer_id)
        assert exc_info.value.status_code == 409

    def test_cv_pdf_non_genere(self, db_path, coordonnees_path):
        offer_id = 161
        _insert_offer(db_path, offer_id, company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_cv.get_cv_pdf(offer_id)
        assert exc_info.value.status_code == 409

    def test_lettre_pdf_offre_non_retenue(self, db_path, coordonnees_path):
        offer_id = 162
        _insert_offer(db_path, offer_id, verdict="rejete", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_lettre.get_lettre_pdf(offer_id)
        assert exc_info.value.status_code == 409

    def test_lettre_pdf_non_generee(self, db_path, coordonnees_path):
        offer_id = 163
        _insert_offer(db_path, offer_id, company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_lettre.get_lettre_pdf(offer_id)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Critère 17 — aucun appel modèle
# ---------------------------------------------------------------------------


class TestCritere17AucunAppelModele:
    def test_cv_pdf_n_appelle_pas_le_sdk(self, db_path, coordonnees_path, monkeypatch):
        offer_id = 170

        def _boom(*, prompt, options):
            raise AssertionError("le SDK ne doit jamais être appelé pour un PDF")

        monkeypatch.setattr(cv_service, "query", _boom)
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_cv_done(db_path, offer_id, html="<html><body>CV</body></html>")
        response = api_cv.get_cv_pdf(offer_id)
        assert response.body[:5] == b"%PDF-"

    def test_lettre_pdf_n_appelle_pas_le_sdk(
        self, db_path, coordonnees_path, monkeypatch
    ):
        offer_id = 171

        def _boom(*, prompt, options):
            raise AssertionError("le SDK ne doit jamais être appelé pour un PDF")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _boom)
        _insert_offer(db_path, offer_id, company="SFEIR")
        _insert_lettre_done(db_path, offer_id, _lettre_texte())
        response = api_lettre.get_lettre_pdf(offer_id)
        assert response.body[:5] == b"%PDF-"
