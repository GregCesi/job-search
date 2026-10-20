"""Tests EXE-176 — le mail de candidature se génère depuis la lettre courante et
se réécrit à la main (critères 1 à 6, 8, 10, 11).

Aucun test n'appelle le modèle (`query` du SDK Claude Agent est remplacé par un
faux générateur async, même convention que test_cv_service.py). Aucun test ne
lit ni n'écrit sous data/ : DB, coordonnées et consigne sont tous sous tmp_path.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from claude_agent_sdk import ResultMessage
from fastapi import HTTPException

import api.db as api_db
import api.mail as api_mail
import orchestrator.job_search.mail.generation as generation_module
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

CONSIGNE = "Écris un mail court, professionnel, qui renvoie à la lettre jointe."


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
    """behavior(prompt, options) -> liste de messages à produire (ou lève une exception)."""

    async def _query(*, prompt, options):
        msgs = behavior(prompt, options)
        for m in msgs:
            yield m

    return _query


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
def consigne_path(tmp_path, monkeypatch):
    path = tmp_path / "mail_consigne.md"
    path.write_text(CONSIGNE, encoding="utf-8")
    monkeypatch.setattr(generation_module, "MAIL_CONSIGNE_PATH", path)
    return path


@pytest.fixture
def gabarit_path(tmp_path, monkeypatch):
    import orchestrator.job_search.mail.candidature as candidature_module

    path = tmp_path / "mail_candidature.md"
    path.write_text(
        "Objet : Candidature {chez_entreprise} au poste de {intitule}\n"
        "\n"
        "Bonjour, je candidate.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", path)
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
        if verdict == "retenu":
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        elif verdict is not None:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.ECARTER, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre_done(
    db_path, offer_id, texte="Ma lettre de candidature pour ce poste."
):
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


def _generer(offer_id):
    return asyncio.run(api_mail.post_mail_generer(offer_id))


# ---------------------------------------------------------------------------
# Critère 1 — un seul appel modèle (Sonnet), avec la consigne du fichier
# ---------------------------------------------------------------------------


class TestCritere1GenerationDepuisLaLettre:
    def test_un_seul_appel_avec_la_consigne(
        self, db_path, coordonnees_path, consigne_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, "Ma lettre pour ce poste chez SFEIR.")

        appels = []

        def behavior(prompt, options):
            appels.append((prompt, options))
            return [
                _fake_result(
                    structured_output={"objet": "Candidature", "corps": "Bonjour."}
                )
            ]

        monkeypatch.setattr(generation_module, "query", _make_query(behavior))

        mail = _generer(offer_id)
        assert len(appels) == 1
        prompt_text, options = appels[0]
        assert options.model == "sonnet"
        assert CONSIGNE in prompt_text
        assert "Ma lettre pour ce poste chez SFEIR." in prompt_text
        assert mail["objet"] == "Candidature"
        assert mail["corps"] == "Bonjour."


# ---------------------------------------------------------------------------
# Critère 2 — le mail généré devient le mail de l'offre
# ---------------------------------------------------------------------------


class TestCritere2MailGenereDevientLeMailDeLOffre:
    def test_get_mail_rend_la_version_generee(
        self, db_path, coordonnees_path, consigne_path, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id)

        def behavior(prompt, options):
            return [
                _fake_result(
                    structured_output={"objet": "Objet généré", "corps": "Corps généré"}
                )
            ]

        monkeypatch.setattr(generation_module, "query", _make_query(behavior))
        _generer(offer_id)

        mail = api_mail.get_mail_candidature(offer_id)
        assert mail["objet"] == "Objet généré"
        assert mail["corps"] == "Corps généré"
        assert mail["origine"] == "modele"


# ---------------------------------------------------------------------------
# Critère 3 — sans lettre courante, aucun appel ne part
# ---------------------------------------------------------------------------


class TestCritere3SansLettreCourante:
    def test_refuse_sans_appeler_le_modele(
        self, db_path, coordonnees_path, consigne_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")

        def _boom(*, prompt, options):
            raise AssertionError("aucun appel de modèle ne doit partir")

        monkeypatch.setattr(generation_module, "query", _boom)

        with pytest.raises(HTTPException) as exc_info:
            _generer(offer_id)
        assert exc_info.value.status_code == 409
        assert "lettre" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Critère 4 — sans fichier de consigne, arrêt avant tout appel
# ---------------------------------------------------------------------------


class TestCritere4SansConsigne:
    def test_refuse_en_nommant_le_fichier_sans_appeler_le_modele(
        self, db_path, coordonnees_path, tmp_path, monkeypatch
    ):
        offer_id = 4
        missing = tmp_path / "absent" / "mail_consigne.md"
        monkeypatch.setattr(generation_module, "MAIL_CONSIGNE_PATH", missing)
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id)

        def _boom(*, prompt, options):
            raise AssertionError("aucun appel de modèle ne doit partir")

        monkeypatch.setattr(generation_module, "query", _boom)

        with pytest.raises(HTTPException) as exc_info:
            _generer(offer_id)
        assert exc_info.value.status_code == 409
        assert str(missing) in exc_info.value.detail


# ---------------------------------------------------------------------------
# Critère 5 — réponse incomplète : le mail en place n'est pas écrasé
# ---------------------------------------------------------------------------


class TestCritere5ReponseIncomplete:
    @pytest.mark.parametrize(
        "sortie",
        [
            {"objet": "", "corps": "Corps"},
            {"objet": "Objet", "corps": ""},
            {"objet": "Objet"},
            {},
        ],
    )
    def test_ne_remplace_pas_le_mail_en_place(
        self,
        db_path,
        coordonnees_path,
        consigne_path,
        gabarit_path,
        monkeypatch,
        sortie,
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id)

        avant = api_mail.get_mail_candidature(offer_id)

        def behavior(prompt, options):
            return [_fake_result(structured_output=sortie)]

        monkeypatch.setattr(generation_module, "query", _make_query(behavior))

        with pytest.raises(HTTPException) as exc_info:
            _generer(offer_id)
        assert exc_info.value.status_code == 502

        apres = api_mail.get_mail_candidature(offer_id)
        assert apres == avant


# ---------------------------------------------------------------------------
# Critère 6 — l'appel de la génération se lit par l'API
# ---------------------------------------------------------------------------


class TestCritere6AppelLisibleParLAPI:
    def test_appel_garde_modele_duree_cout_demande_reponse(
        self, db_path, coordonnees_path, consigne_path, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, "Ma lettre pour ce poste.")

        def behavior(prompt, options):
            return [
                _fake_result(
                    structured_output={"objet": "Objet", "corps": "Corps"},
                    result='{"objet": "Objet", "corps": "Corps"}',
                )
            ]

        monkeypatch.setattr(generation_module, "query", _make_query(behavior))
        _generer(offer_id)

        appel = api_mail.get_mail_appel(offer_id)
        assert appel["modele"] == "sonnet"
        assert appel["duree_s"] >= 0
        assert appel["cout_usd"] == 0.01
        assert "Ma lettre pour ce poste." in appel["demande"]
        assert appel["reponse"]

    def test_pas_d_appel_sans_generation(self, db_path, coordonnees_path):
        offer_id = 60
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_appel(offer_id)
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Critère 8 — ma version écrite à la main est celle que je retrouve
# ---------------------------------------------------------------------------


class TestCritere8VersionManuellePersistee:
    def test_retrouvee_apres_une_nouvelle_connexion(self, db_path, coordonnees_path):
        offer_id = 8
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")

        api_mail.put_mail_candidature(
            offer_id, api_mail.MailIn(objet="Mon objet", corps="Mon corps")
        )

        # Une connexion neuve, comme après redémarrage de l'API.
        mail = api_mail.get_mail_candidature(offer_id)
        assert mail["objet"] == "Mon objet"
        assert mail["corps"] == "Mon corps"
        assert mail["origine"] == "moi"


# ---------------------------------------------------------------------------
# Critère 10 — jamais généré ni enregistré : le mail du gabarit statique
# ---------------------------------------------------------------------------


class TestCritere10JamaisGenereNiEnregistre:
    def test_affiche_le_gabarit_statique(self, db_path, coordonnees_path, gabarit_path):
        offer_id = 10
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        mail = api_mail.get_mail_candidature(offer_id)
        assert mail["origine"] is None
        assert "Ingénieur IA" in mail["objet"]


# ---------------------------------------------------------------------------
# Critère 11 — générer depuis la lettre remplace une version à la main
# ---------------------------------------------------------------------------


class TestCritere11GenerationRemplaceVersionManuelle:
    def test_remplace_la_version_a_la_main(
        self, db_path, coordonnees_path, consigne_path, monkeypatch
    ):
        offer_id = 11
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id)

        api_mail.put_mail_candidature(
            offer_id, api_mail.MailIn(objet="Ma version", corps="Écrite à la main")
        )
        avant = api_mail.get_mail_candidature(offer_id)
        assert avant["origine"] == "moi"

        def behavior(prompt, options):
            return [
                _fake_result(
                    structured_output={"objet": "Objet modèle", "corps": "Corps modèle"}
                )
            ]

        monkeypatch.setattr(generation_module, "query", _make_query(behavior))
        _generer(offer_id)

        apres = api_mail.get_mail_candidature(offer_id)
        assert apres["origine"] == "modele"
        assert apres["objet"] == "Objet modèle"
        assert apres["corps"] == "Corps modèle"
