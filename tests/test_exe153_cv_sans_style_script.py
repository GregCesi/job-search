"""Tests EXE-153 — la rédaction de la lettre reçoit le texte de mon CV, sans sa
feuille de style ni son éventuel script, et l'annonce dont le HTML porte un bloc de
style arrive au tamis sans aucun caractère de ce bloc.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par une
doublure programmable (reprise de test_exe147_boucle_lettre.py). Aucun test ne lit
ni n'écrit sous data/ : le CV de référence, le répertoire et les tournures
interdites sont posés dans tmp_path.

EXE-162 a retiré le critère 4 (« la lettre que l'application génère passe par le
même nettoyage ») : la génération de l'application délègue désormais entièrement à
`generer_lettre_depuis_donnees`, déjà couverte ici par les critères 1-3 — il n'y a
plus de chemin de nettoyage séparé côté `service.py` à vérifier.
"""

import json

import pytest
import yaml

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.lettre.redaction import strip_html, strip_style_and_script

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
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        if noeud == "verificateur" and not self.files["verificateur"]:
            # EXE-160 : sans programmation explicite, le vérificateur rend un
            # relevé vide et n'entre pas dans `self.appels` — les tests d'avant
            # la fiche gardent leurs index positionnels sur tamis/rédaction/juge.
            return ReponseModele(
                texte=json.dumps(
                    {"rien_a_signaler": True, "lieux": [], "affirmations": []}
                ),
                duree_s=0.01,
                cout_usd=0.01,
            )
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
        "redaction": {
            "consigne_reprise": "Consigne de reprise.",
            "consigne_verification": "Consigne de correction.",
        },
        "verificateur": {"consigne": "Consigne du vérificateur."},
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
