"""Tests EXE-153 — la rédaction de la lettre reçoit le texte de mon CV, sans sa
feuille de style ni son éventuel script, et l'annonce dont le HTML porte un bloc de
style arrive au tamis sans aucun caractère de ce bloc.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par une
doublure programmable (reprise de test_exe147_boucle_lettre.py), et `query` du SDK
Claude Agent est remplacé par un faux générateur async (reprise de test_lettre.py).
Aucun test ne lit ni n'écrit sous data/ : le CV de référence, le répertoire, les
tournures interdites et la base sont posés dans tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
import yaml
from claude_agent_sdk import ResultMessage

import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.lettre.redaction import strip_html, strip_style_and_script
from orchestrator.job_search.storage.db import init_db

CV_STYLE_HTML = (
    "<html><head><style>body { color: red; font-family: Arial; }\n"
    ".titre { font-weight: bold; }</style></head>"
    "<body><h1>Gregoire Marchand</h1>"
    "<h2>Experience</h2><p>Ingenieur IA generative, cinq ans.</p>"
    "<h2>Competences</h2><p>Python, LLM, RAG.</p>"
    "</body></html>"
)
CV_SCRIPT_HTML = (
    "<html><head><script>function tracker() { envoyerStatistique('cv_vu'); }"
    "</script></head>"
    "<body><h1>Gregoire Marchand</h1>"
    "<h2>Experience</h2><p>Ingenieur IA generative, cinq ans.</p>"
    "<h2>Competences</h2><p>Python, LLM, RAG.</p>"
    "</body></html>"
)
CV_SANS_STYLE_SCRIPT_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
OFFRE_STYLE_HTML = (
    "<html><head><style>.offre { background: blue; }</style></head>"
    "<body><p>Poste de data engineer a Strasbourg.</p></body></html>"
)
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (boucle) -------------------------------------


class FakeModeles:
    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        self.appels.append((noeud, modele, prompt_text))
        valeur = self.files[noeud].pop(0)
        if isinstance(valeur, BaseException):
            raise valeur
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=0.01)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


def _config(modele="sonnet") -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis=modele, modele_redaction=modele, modele_juge=modele
    )


def _repertoire_donnees() -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "regles": ["jamais de superlatif"],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
        },
        "textes_types": [
            {
                "id": "generique",
                "sujet": "sujet générique",
                "texte": "Texte générique rédigé à la main.",
                "exemples": [],
            },
        ],
        "juge": {
            "consigne": "Consigne du juge.",
            "contexte": "Contexte du juge.",
        },
        "redaction": {"consigne_reprise": "Consigne de reprise."},
    }


@pytest.fixture
def repertoire_path(tmp_path):
    chemin = tmp_path / "repertoire.yaml"
    chemin.write_text(
        yaml.safe_dump(_repertoire_donnees(), allow_unicode=True), encoding="utf-8"
    )
    return chemin


@pytest.fixture
def tournures_path(tmp_path):
    chemin = tmp_path / "tournures_interdites.txt"
    chemin.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    return chemin


def _cv_path(tmp_path, html, nom="cv_reference.html"):
    chemin = tmp_path / nom
    chemin.write_text(html, encoding="utf-8")
    return chemin


_TAMIS_GENERIQUE = json.dumps({"point_index": None, "texte_type_id": "generique"})
_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
    }
)


def _lancer(
    repertoire_path,
    cv_path,
    tournures_path,
    modeles,
    texte_offre="Texte de l'offre.",
):
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        texte_offre,
        "Entreprise X",
        [],
        _config(),
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
    )


# --- critères 1-3 : le CV, bloc de style -----------------------------------------


def test_critere1_cv_avec_style_aucun_caractere_du_bloc_a_la_redaction(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_STYLE_HTML)
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    assert "color: red" not in demande_redaction
    assert "font-family" not in demande_redaction
    assert ".titre" not in demande_redaction
    assert "font-weight" not in demande_redaction


def test_critere3_cv_avec_style_texte_visible_entier_a_la_redaction(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_STYLE_HTML)
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    assert "Gregoire Marchand" in demande_redaction
    assert "Experience" in demande_redaction
    assert "Competences" in demande_redaction
    assert "Ingenieur IA generative, cinq ans." in demande_redaction
    assert "Python, LLM, RAG." in demande_redaction


# --- critère 2 : le CV, bloc de script -------------------------------------------


def test_critere2_cv_avec_script_aucun_caractere_du_bloc_a_la_redaction(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_SCRIPT_HTML)
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    assert "tracker" not in demande_redaction
    assert "envoyerStatistique" not in demande_redaction
    assert "function" not in demande_redaction


def test_critere2_cv_avec_script_texte_visible_entier_a_la_redaction(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_SCRIPT_HTML)
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    assert "Gregoire Marchand" in demande_redaction
    assert "Experience" in demande_redaction
    assert "Competences" in demande_redaction


# --- critère 6 : CV sans style ni script, inchangé -------------------------------


def test_critere6_cv_sans_style_ni_script_inchange(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_SANS_STYLE_SCRIPT_HTML)
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    assert "Contenu CV de test" in demande_redaction
    assert "<" not in strip_html(CV_SANS_STYLE_SCRIPT_HTML)


# --- critère 5 : annonce avec bloc de style, au tamis ----------------------------


def test_critere5_offre_avec_style_aucun_caractere_du_bloc_au_tamis(
    tmp_path, repertoire_path, tournures_path, modeles
):
    cv_path = _cv_path(tmp_path, CV_SANS_STYLE_SCRIPT_HTML)
    _lancer(
        repertoire_path,
        cv_path,
        tournures_path,
        modeles,
        texte_offre=OFFRE_STYLE_HTML,
    )

    demande_tamis = modeles.appels[0][2]
    assert "background: blue" not in demande_tamis
    assert ".offre" not in demande_tamis
    assert "Poste de data engineer a Strasbourg." in demande_tamis


# --- critère 4 : la lettre que l'application génère (service.py) ----------------


def _fake_result(result=None, is_error=False, session_id="fake-session", cost=0.02):
    return ResultMessage(
        subtype="success" if not is_error else "error_during_execution",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
        result=result,
        structured_output=None,
    )


def _make_query(behavior):
    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def app_fixture_paths(tmp_path, monkeypatch):
    prefs = tmp_path / "preferences_ton.md"
    prefs.write_text("- Ton direct\n", encoding="utf-8")
    tournures = tmp_path / "tournures_interdites.txt"
    tournures.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    cv_ref = _cv_path(tmp_path, CV_STYLE_HTML)
    monkeypatch.setattr(lettre_service, "LETTRE_PREFERENCES_PATH", prefs)
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    monkeypatch.setattr(lettre_service, "CV_REFERENCE_PATH", cv_ref)


def _insert_offer(db_path, offer_id, description_raw="Texte de l'offre X"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', ?)",
            (offer_id, str(offer_id), description_raw),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) "
            "VALUES (?, 'retenu', '2026-10-07')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, created_at) VALUES (?, 'done', 'Présentation', ?, "
            "'2026-10-07')",
            (offer_id, json.dumps([{"position": "Point 0", "tas": "lettre"}])),
        )
        conn.commit()
    finally:
        conn.close()


def _lettre_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def test_critere4_lettre_app_recoit_le_cv_nettoye_de_la_meme_facon(
    db_path, app_fixture_paths, monkeypatch
):
    offer_id = 153
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)

    def behavior(prompt, options):
        return [_fake_result(result="Lettre.")]

    monkeypatch.setattr(lettre_service, "query", _make_query(behavior))
    asyncio.run(lettre_service.run_lettre(offer_id))

    prompt_text = _lettre_row(db_path, offer_id)["prompt_text"]
    assert "color: red" not in prompt_text
    assert "font-family" not in prompt_text
    assert "Gregoire Marchand" in prompt_text


# --- unités : strip_style_and_script et strip_html -------------------------------


class TestUnitesStripHtml:
    def test_strip_style_and_script_retire_le_bloc_style_entier(self):
        texte = strip_style_and_script(
            "<style>.a { color: red; }</style><p>Bonjour</p>"
        )
        assert "color" not in texte
        assert "<p>Bonjour</p>" in texte

    def test_strip_style_and_script_retire_le_bloc_script_entier(self):
        texte = strip_style_and_script("<script>alert('x');</script><p>Bonjour</p>")
        assert "alert" not in texte
        assert "<p>Bonjour</p>" in texte

    def test_strip_style_and_script_insensible_a_la_casse(self):
        texte = strip_style_and_script("<STYLE>.a{color:red}</STYLE><p>X</p>")
        assert "color" not in texte

    def test_strip_html_retire_les_balises(self):
        assert strip_html("<p>Bonjour <b>Monde</b></p>") == "Bonjour Monde"

    def test_strip_html_retire_style_et_balises(self):
        texte = strip_html(
            "<html><head><style>body{color:red}</style></head>"
            "<body><p>Bonjour</p></body></html>"
        )
        assert texte == "Bonjour"
