"""Tests EXE-103 — mail de candidature d'une offre retenue, préparé depuis un
gabarit.

Aucun test n'appelle un modèle ni le réseau. Aucun test ne lit ni n'écrit sous
data/ : DB, intermédiaires et gabarit sont tous sous `tmp_path` (même convention
que test_exe102_pdf_pieces.py). Le gabarit des tests est le leur, jamais celui du
dépôt réel (H3 du ticket).
"""

import sqlite3
from datetime import datetime, timezone

import claude_agent_sdk
import pytest
from fastapi import HTTPException

import api.db as api_db
import api.mail as api_mail
import orchestrator.job_search.fiche.intermediaires as intermediaires_module
import orchestrator.job_search.mail.candidature as candidature_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db

GABARIT_DEFAUT = (
    "Objet : Candidature {chez_entreprise} au poste de {intitule}\n"
    "\n"
    "Bonjour,\n"
    "\n"
    "Je me permets de vous contacter {chez_entreprise} pour le poste de "
    "{intitule}.\n"
    "Je me présente en deux lignes, et je veux travailler dans l'IA.\n"
    "\n"
    "Cordialement,\n"
    "Grégoire Marchand\n"
)


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
def gabarit_path(tmp_path, monkeypatch):
    path = tmp_path / "mail_candidature.md"
    path.write_text(GABARIT_DEFAUT, encoding="utf-8")
    monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", path)
    return path


@pytest.fixture
def intermediaires_path(tmp_path, monkeypatch):
    path = tmp_path / "intermediaires.yaml"
    path.write_text("intermediaires:\n  - EDITX BV\n", encoding="utf-8")
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


# ---------------------------------------------------------------------------
# Critères 1-2 — l'app rend un objet et un corps suivant le gabarit
# ---------------------------------------------------------------------------


class TestCritere1Et2ObjetEtCorpsDuGabarit:
    def test_rend_objet_et_corps_avec_intitule_substitue(self, db_path, gabarit_path):
        offer_id = 1
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        mail = api_mail.get_mail_candidature(offer_id)
        assert "objet" in mail
        assert "corps" in mail
        assert "Ingénieur IA" in mail["objet"]
        assert "Ingénieur IA" in mail["corps"]
        assert "{intitule}" not in mail["objet"]
        assert "{intitule}" not in mail["corps"]


# ---------------------------------------------------------------------------
# Critère 3 — entreprise choisie par la même règle que les PDF
# ---------------------------------------------------------------------------


class TestCritere3ChezEntreprise:
    def test_entreprise_de_loffre(self, db_path, gabarit_path):
        offer_id = 3
        _insert_offer(db_path, offer_id, title="Data Engineer", company="FINTENSY NV")
        mail = api_mail.get_mail_candidature(offer_id)
        assert "chez FINTENSY NV" in mail["objet"]
        assert "chez FINTENSY NV" in mail["corps"]

    def test_intermediaire_connu_utilise_la_fiche(
        self, db_path, gabarit_path, intermediaires_path
    ):
        offer_id = 30
        _insert_offer(db_path, offer_id, title="Data Engineer", company="EDITX BV")
        _insert_fiche(db_path, offer_id, employeur_nom="Proximus Ada")
        mail = api_mail.get_mail_candidature(offer_id)
        assert "chez Proximus Ada" in mail["objet"]
        assert "chez Proximus Ada" in mail["corps"]
        assert "EDITX BV" not in mail["objet"]
        assert "EDITX BV" not in mail["corps"]


# ---------------------------------------------------------------------------
# Critère 4 — aucune entreprise utilisable : le repère disparaît proprement
# ---------------------------------------------------------------------------


class TestCritere4AucuneEntrepriseUtilisable:
    def test_repere_disparait_sans_double_espace_ni_espace_avant_ponctuation(
        self, db_path, gabarit_path, intermediaires_path
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id, title="Data Engineer", company="EDITX BV")
        _insert_fiche(db_path, offer_id, employeur_nom=None)
        mail = api_mail.get_mail_candidature(offer_id)
        assert "chez" not in mail["objet"]
        assert "chez" not in mail["corps"]
        assert "{chez_entreprise}" not in mail["objet"]
        assert "{chez_entreprise}" not in mail["corps"]
        assert "  " not in mail["objet"]
        assert "  " not in mail["corps"]
        for ponctuation in ",.;:!?":
            assert f" {ponctuation}" not in mail["objet"]
            assert f" {ponctuation}" not in mail["corps"]
        assert mail["objet"] == "Candidature au poste de Data Engineer"
        assert (
            "Je me permets de vous contacter pour le poste de Data Engineer."
            in mail["corps"]
        )


# ---------------------------------------------------------------------------
# Critère 5 — hors des deux repères, le texte est celui du gabarit au caractère près
# ---------------------------------------------------------------------------


class TestCritere5TexteInchangeHorsReperes:
    def test_texte_du_gabarit_conserve_au_caractere_pres(self, db_path, gabarit_path):
        offer_id = 5
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        mail = api_mail.get_mail_candidature(offer_id)
        assert "Bonjour," in mail["corps"]
        assert (
            "Je me présente en deux lignes, et je veux travailler dans l'IA."
            in (mail["corps"])
        )
        assert "Cordialement,\nGrégoire Marchand" in mail["corps"]


# ---------------------------------------------------------------------------
# Critère 6 — gabarit modifié sans toucher au code
# ---------------------------------------------------------------------------


class TestCritere6GabaritModifiable:
    def test_mail_suit_le_nouveau_gabarit(self, db_path, gabarit_path):
        offer_id = 6
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        premier = api_mail.get_mail_candidature(offer_id)
        assert "Bonjour," in premier["corps"]

        gabarit_path.write_text(
            "Objet : Nouveau gabarit pour {intitule}\n\nNouveau corps {chez_entreprise}.\n",
            encoding="utf-8",
        )
        second = api_mail.get_mail_candidature(offer_id)
        assert second["objet"] == "Nouveau gabarit pour Ingénieur IA"
        assert second["corps"] == "Nouveau corps chez SFEIR.\n"
        assert "Bonjour," not in second["corps"]


# ---------------------------------------------------------------------------
# Critère 7 — gabarit absent
# ---------------------------------------------------------------------------


class TestCritere7GabaritAbsent:
    def test_refuse_en_nommant_le_fichier(self, db_path, tmp_path, monkeypatch):
        offer_id = 7
        missing = tmp_path / "absent" / "mail_candidature.md"
        monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", missing)
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_candidature(offer_id)
        assert str(missing) in exc_info.value.detail


# ---------------------------------------------------------------------------
# Critère 8 — repère inconnu dans le gabarit
# ---------------------------------------------------------------------------


class TestCritere8RepereInconnu:
    def test_refuse_en_citant_le_repere(self, db_path, gabarit_path):
        offer_id = 8
        gabarit_path.write_text(
            "Objet : Candidature {inconnu}\n\nCorps {intitule}.\n", encoding="utf-8"
        )
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_candidature(offer_id)
        assert "{inconnu}" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Critère 9 — offre non retenue
# ---------------------------------------------------------------------------


class TestCritere9OffreNonRetenue:
    def test_refuse_pour_offre_non_retenue(self, db_path, gabarit_path):
        offer_id = 9
        _insert_offer(db_path, offer_id, verdict="rejete", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_candidature(offer_id)
        assert exc_info.value.status_code == 409

    def test_refuse_pour_offre_sans_verdict(self, db_path, gabarit_path):
        offer_id = 90
        _insert_offer(db_path, offer_id, verdict=None, company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_candidature(offer_id)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Critère 10 — aucun appel modèle
# ---------------------------------------------------------------------------


class TestCritere10AucunAppelModele:
    def test_mail_n_appelle_pas_le_sdk(self, db_path, gabarit_path, monkeypatch):
        def _boom(*, prompt, options):
            raise AssertionError("le mail ne doit jamais appeler le modèle")

        monkeypatch.setattr(claude_agent_sdk, "query", _boom)
        offer_id = 10
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        mail = api_mail.get_mail_candidature(offer_id)
        assert "Ingénieur IA" in mail["objet"]
