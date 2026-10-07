"""Tests EXE-150 — trois manques de la boucle de la lettre (relecture du jet 27) :
la rédaction ne recevait pas mon texte générique, le tamis ne voyait ni la famille
ni la date des points et lisait « None » derrière un sujet interdit sans motif, et
ni la rédaction ni le juge ne connaissaient mes sujets interdits.

Aucun test n'appelle un modèle : `boucle.appeler_modele` est remplacé par une
doublure programmable. Aucun test ne lit ni n'écrit sous data/ : la base, le
répertoire, le CV de référence et les tournures interdites sont posés dans
tmp_path.
"""

import json
import sqlite3

import pytest
import yaml

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_boucle,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\n"


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


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"sujet de {identifiant}",
        "conviction": f"conviction de {identifiant}",
        "ce_que_j_ai_fait": f"ce que j'ai fait pour {identifiant}",
        "s_applique_si": f"condition d'usage de {identifiant}",
        "texte": f"texte rédigé de {identifiant}",
        "exemples": [],
    }
    base.update(overrides)
    return base


def _repertoire_donnees(
    generique_texte: str | None = "Texte générique rédigé à la main, en entier.",
    sujets_interdits: list | None = None,
) -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "quatre_temps": ["accroche", "preuve", "offre", "cta"],
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "sujets_interdits": (
            sujets_interdits
            if sujets_interdits is not None
            else [
                {
                    "sujet": "Claude / Anthropic",
                    "motif": "l'entreprise visée n'en parle pas",
                    "exception": "sauf si l'offre nomme Claude elle-même",
                }
            ]
        ),
        "conditions_generales": ["lettre en français"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": None,
        },
        "textes_types": [
            _texte_type("prototyper"),
            _texte_type("generique", texte=generique_texte, exemples=[]),
        ],
    }


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(**kwargs):
        chemin = tmp_path / "repertoire.yaml"
        donnees = _repertoire_donnees(**kwargs)
        chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
        return chemin

    return _ecrire


@pytest.fixture
def cv_path(tmp_path):
    chemin = tmp_path / "cv_reference.html"
    chemin.write_text(CV_HTML, encoding="utf-8")
    return chemin


@pytest.fixture
def tournures_path(tmp_path):
    chemin = tmp_path / "tournures_interdites.txt"
    chemin.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    return chemin


@pytest.fixture
def db_path(tmp_path):
    chemin = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(chemin)
    init_db(conn)
    conn.close()
    return chemin


def _poser_offre_et_fiche(
    db_path, offer_id=1, points=None, employeur_nom="Entreprise X"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre de l''offre', "
            "'Entreprise X SAS', 'Texte de l''offre')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, ?, '2026-10-07')",
            (offer_id, json.dumps(points or []), employeur_nom),
        )
        conn.commit()
    finally:
        conn.close()


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _lancer(
    db_path,
    repertoire_path,
    cv_path,
    tournures_path,
    config=None,
    offer_id=1,
    **repertoire_kwargs,
):
    conn = _conn(db_path)
    try:
        return generer_lettre_boucle(
            conn,
            offer_id,
            config or _config(),
            repertoire_path=repertoire_path(**repertoire_kwargs),
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
        )
    finally:
        conn.close()


_JUGE_RIEN_A_REDIRE = json.dumps({"rien_a_redire": True, "remarques": None})


# --- critères 1-2 : le texte générique arrive (ou non) à la rédaction ----------


def test_critere1_generique_rend_texte_generique_entier_a_la_redaction(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer(
        "tamis", json.dumps({"point_index": None, "texte_type_id": "generique"})
    )
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Texte générique rédigé à la main, en entier." in demande_redaction


def test_critere2_autre_texte_type_ne_recoit_pas_texte_generique(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Texte générique rédigé à la main, en entier." not in demande_redaction


# --- critères 3-4 : famille et date d'un point, reçues par le tamis ------------


def test_critere3_tamis_recoit_famille_et_date_du_point(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
                "famille": "preuve_ia",
                "date": "2026-09-01",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_tamis = modeles.appels[0][2]
    assert "preuve_ia" in demande_tamis
    assert "2026-09-01" in demande_tamis


def test_critere4_point_sans_famille_ni_date_pas_de_mention_vide_ni_none_ni_aucune(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_tamis = modeles.appels[0][2]
    assert "None" not in demande_tamis
    assert "aucune" not in demande_tamis.lower()
    assert "famille :" not in demande_tamis
    assert "date :" not in demande_tamis


# --- critères 5-6 : motif d'un sujet interdit, absent ou présent ---------------


def test_critere5_sujet_interdit_sans_motif_pas_de_parenthese_vide_ni_none(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        sujets_interdits=[{"sujet": "Sujet sans motif"}],
    )

    demande_tamis = modeles.appels[0][2]
    assert "Sujet sans motif" in demande_tamis
    assert "None" not in demande_tamis
    assert "Sujet sans motif ()" not in demande_tamis


def test_critere6_sujet_interdit_avec_motif_present(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        sujets_interdits=[{"sujet": "Sujet avec motif", "motif": "raison précise"}],
    )

    demande_tamis = modeles.appels[0][2]
    assert "Sujet avec motif (raison précise)" in demande_tamis


# --- critères 7-8 : rédaction et juge reçoivent les sujets interdits -----------


def test_critere7_redaction_recoit_sujets_interdits_motif_et_exception(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        sujets_interdits=[
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
                "exception": "sauf si l'offre nomme Claude elle-même",
            }
        ],
    )

    demande_redaction = modeles.appels[1][2]
    assert "Claude / Anthropic" in demande_redaction
    assert "l'entreprise visée n'en parle pas" in demande_redaction
    assert "sauf si l'offre nomme Claude elle-même" in demande_redaction


def test_critere8_juge_recoit_sujets_interdits_motif_et_exception(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        sujets_interdits=[
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
                "exception": "sauf si l'offre nomme Claude elle-même",
            }
        ],
    )

    demande_juge = modeles.appels[2][2]
    assert "Claude / Anthropic" in demande_juge
    assert "l'entreprise visée n'en parle pas" in demande_juge
    assert "sauf si l'offre nomme Claude elle-même" in demande_juge


# --- critères 9-10 : famille et date du fait retenu ----------------------------


def test_critere9_redaction_recoit_famille_et_date_du_fait_retenu(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
                "famille": "preuve_ia",
                "date": "2026-09-01",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "preuve_ia" in demande_redaction
    assert "2026-09-01" in demande_redaction


def test_critere10_resultat_fait_retenu_porte_famille_et_date(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(
        db_path,
        points=[
            {
                "position": "Point 0",
                "citation": "Citation 0",
                "url": "https://exemple.test/0",
                "famille": "preuve_ia",
                "date": "2026-09-01",
            }
        ],
    )
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.fait_retenu["famille"] == "preuve_ia"
    assert resultat.fait_retenu["date"] == "2026-09-01"
