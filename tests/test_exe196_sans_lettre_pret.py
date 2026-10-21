"""Tests EXE-196 — une candidature sans lettre est prête avec le CV seul : le
téléchargement ne donne que le CV, et le mail ne parle plus de lettre.

Aucun test n'appelle un modèle réel : `generation_module.query` est remplacé
par une doublure qui lève si on l'appelle (critère 12). Aucun test ne lit ni
n'écrit sous data/ : DB sous `tmp_path` (fixture `db_path`, comme EXE-101), et
les deux gabarits de mail sous `tmp_path` (fixture `_isolate_mail_gabarit_paths`
de `conftest.py`, critère 16).
"""

import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.db as api_db
import api.mail as api_mail
import orchestrator.job_search.mail.candidature as candidature_module
import orchestrator.job_search.paths as paths
import orchestrator.job_search.pieces as pieces_mod
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.mail.candidature import GabaritAbsentError
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage


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
def client(db_path):
    import api.main as api_main

    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _no_real_cascade(monkeypatch):
    import api.cascade as cascade

    async def _noop(offer_id):
        return []

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(db_path, offer_id, title="Titre", company="Acme"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, 'Texte de l offre')",
            (offer_id, str(offer_id), title, company),
        )
        suivi_storage.appliquer_geste(
            conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
        )
        conn.commit()
    finally:
        conn.close()


def _insert_cv(db_path, offer_id, pret: bool):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO cvs (offer_id, statut, marque_pret_at, created_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, _now() if pret else None, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(
    db_path,
    offer_id,
    *,
    decision="a_decider",
    statut="aucune",
    pret=False,
    texte=None,
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, "
            "texte, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (offer_id, statut, decision, _now() if pret else None, texte, _now()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Critères 1-5 — la condition unique, en Python pur (module d'états)
# ---------------------------------------------------------------------------


class TestCriteres1A5PreteALEnvoiCasParCas:
    def test_critere1_cv_pret_et_sans_lettre_est_prete(self):
        assert (
            suivi_etats.pieces_pretes_pour_envoi(
                cv_pret=True, lettre_pret=False, lettre_sans=True
            )
            is True
        )

    def test_critere2_cv_pret_et_lettre_a_decider_reste_retenue(self):
        assert (
            suivi_etats.pieces_pretes_pour_envoi(
                cv_pret=True, lettre_pret=False, lettre_sans=False
            )
            is False
        )

    def test_critere3_cv_pret_et_lettre_generee_sans_marque_reste_retenue(self):
        # lettre générée (statut done) mais pas marquée Prête : lettre_pret=False.
        assert (
            suivi_etats.pieces_pretes_pour_envoi(
                cv_pret=True, lettre_pret=False, lettre_sans=False
            )
            is False
        )

    def test_critere4_cv_pas_pret_et_sans_lettre_reste_retenue(self):
        assert (
            suivi_etats.pieces_pretes_pour_envoi(
                cv_pret=False, lettre_pret=False, lettre_sans=True
            )
            is False
        )

    def test_critere5_cv_pret_et_lettre_prete_est_prete(self):
        assert (
            suivi_etats.pieces_pretes_pour_envoi(
                cv_pret=True, lettre_pret=True, lettre_sans=False
            )
            is True
        )


class TestPreteALEnvoiPiecesPy:
    """Même condition lue depuis `orchestrator.job_search.pieces.prete_a_l_envoi`
    (H4 : un seul endroit l'écrit, les autres la lisent)."""

    def test_sans_lettre_et_cv_pret(self):
        assert (
            pieces_mod.prete_a_l_envoi(pieces_mod.PRETE, pieces_mod.A_FAIRE, True)
            is True
        )

    def test_a_decider_et_cv_pret(self):
        assert (
            pieces_mod.prete_a_l_envoi(pieces_mod.PRETE, pieces_mod.A_FAIRE, False)
            is False
        )


# ---------------------------------------------------------------------------
# Critère 6 — les trois lectures (liste, détail, pièces) d'accord sur les cinq cas
# ---------------------------------------------------------------------------

CAS_PRETE_A_L_ENVOI = [
    # (nom, cv_pret, decision, lettre_pret, prete_attendue)
    ("critere1_sans_lettre_cv_pret", True, "sans_lettre", False, True),
    ("critere2_a_decider_cv_pret", True, "a_decider", False, False),
    ("critere3_lettre_generee_non_marquee", True, "demandee", False, False),
    ("critere4_cv_pas_pret_sans_lettre", False, "sans_lettre", False, False),
    ("critere5_les_deux_pretes", True, "demandee", True, True),
]


class TestCritere6TroisLecturesCoherentes:
    @pytest.mark.parametrize(
        "nom,cv_pret,decision,lettre_pret,attendue", CAS_PRETE_A_L_ENVOI
    )
    def test_liste_detail_et_pieces_disent_la_meme_chose(
        self, client, db_path, nom, cv_pret, decision, lettre_pret, attendue
    ):
        offer_id = abs(hash(nom)) % 100000 + 1
        _insert_offer(db_path, offer_id)
        _insert_cv(db_path, offer_id, pret=cv_pret)
        statut_lettre = "done" if decision != "a_decider" else "aucune"
        _insert_lettre(
            db_path, offer_id, decision=decision, statut=statut_lettre, pret=lettre_pret
        )

        detail = client.get(f"/offers/{offer_id}").json()
        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        liste = client.get("/offers", params={"verdict": "retenu"}).json()
        ligne = next(o for o in liste if o["id"] == offer_id)

        detail_prete = detail["etape"] == "prete_a_l_envoi"
        liste_prete = ligne["etape"] == "prete_a_l_envoi"
        pieces_prete = pieces["prete_a_l_envoi"]

        assert detail_prete is attendue, f"détail, cas {nom}"
        assert liste_prete is attendue, f"liste, cas {nom}"
        assert pieces_prete is attendue, f"pieces, cas {nom}"


# ---------------------------------------------------------------------------
# Critères 7-10 — pièces qui partent, libellé, API comme source unique
# ---------------------------------------------------------------------------


class TestCriteres7A10PiecesEtLibelle:
    def test_critere7_sans_lettre_le_cv_seul(self):
        assert pieces_mod.pieces_a_envoyer(True) == ["cv"]

    def test_critere7_avec_lettre_cv_et_lettre(self):
        assert pieces_mod.pieces_a_envoyer(False) == ["cv", "lettre"]

    def test_critere8_libelle_sans_lettre(self):
        assert pieces_mod.libelle_tout_telecharger(True) == "Télécharger le CV"

    def test_critere8_et_9_api_rend_les_pieces_et_le_libelle(self, client, db_path):
        offer_sans = 201
        _insert_offer(db_path, offer_sans)
        _insert_cv(db_path, offer_sans, pret=True)
        _insert_lettre(db_path, offer_sans, decision="sans_lettre", statut="aucune")

        detail = client.get(f"/offers/{offer_sans}").json()
        assert detail["tout_telecharger_pieces"] == ["cv"]
        assert detail["tout_telecharger_libelle"] == "Télécharger le CV"
        assert detail["tout_telecharger_possible"] is True

        offer_avec = 202
        _insert_offer(db_path, offer_avec)
        _insert_cv(db_path, offer_avec, pret=True)
        _insert_lettre(
            db_path, offer_avec, decision="demandee", statut="done", pret=True
        )

        detail2 = client.get(f"/offers/{offer_avec}").json()
        # Critère 9 : comme avant ce ticket, les deux PDF avec une lettre Prête.
        assert detail2["tout_telecharger_pieces"] == ["cv", "lettre"]
        assert detail2["tout_telecharger_libelle"] == "Tout télécharger"
        assert detail2["tout_telecharger_possible"] is True


# ---------------------------------------------------------------------------
# Critères 11-16 — le mail de candidature
# ---------------------------------------------------------------------------


@pytest.fixture
def gabarit_avec_lettre(tmp_path, monkeypatch):
    path = tmp_path / "gabarit_avec.md"
    path.write_text(
        "Objet : Candidature {chez_entreprise} au poste de {intitule}\n"
        "\n"
        "Bonjour,\n\nVous trouverez mon CV et ma lettre de motivation en "
        "pièces jointes.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_PATH", path)
    return path


@pytest.fixture
def gabarit_sans_lettre(tmp_path, monkeypatch):
    path = tmp_path / "gabarit_sans.md"
    path.write_text(
        "Objet : Candidature {chez_entreprise} au poste de {intitule}\n"
        "\n"
        "Bonjour,\n\nVous trouverez mon CV en pièce jointe.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(candidature_module, "MAIL_CANDIDATURE_SANS_LETTRE_PATH", path)
    return path


class TestCritere11MailSansLettreGabaritDistinct:
    def test_rend_le_gabarit_sans_lettre(
        self, db_path, gabarit_avec_lettre, gabarit_sans_lettre
    ):
        offer_id = 301
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre(db_path, offer_id, decision="sans_lettre", statut="aucune")

        mail = api_mail.get_mail_candidature(offer_id)
        assert "en pièce jointe" in mail["corps"]
        assert "lettre de motivation" not in mail["corps"]
        assert "SFEIR" in mail["objet"]


class TestCritere12GenerationMailRefuseeSansLettre:
    def test_refuse_avant_tout_appel_de_modele(self, db_path, monkeypatch):
        import orchestrator.job_search.mail.generation as generation_module

        offer_id = 302
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, decision="sans_lettre", statut="aucune")

        def _boom(*, prompt, options):
            raise AssertionError("aucun appel de modèle ne doit partir")

        monkeypatch.setattr(generation_module, "query", _boom)

        import asyncio

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_mail.post_mail_generer(offer_id))
        assert exc_info.value.status_code == 409
        assert "n'a pas de lettre" in exc_info.value.detail


class TestCritere13ReecritureMailResteMailCourant:
    def test_ma_version_reste_le_mail_courant_sans_lettre(
        self, db_path, gabarit_sans_lettre
    ):
        offer_id = 303
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, decision="sans_lettre", statut="aucune")

        api_mail.put_mail_candidature(
            offer_id, api_mail.MailIn(objet="Mon objet", corps="Mon corps à la main.")
        )
        mail = api_mail.get_mail_candidature(offer_id)
        assert mail["objet"] == "Mon objet"
        assert mail["corps"] == "Mon corps à la main."
        assert mail["origine"] == "moi"


class TestCritere14GabaritSansLettreAbsentNommeLeFichier:
    def test_409_nomme_le_fichier_manquant(self, db_path, gabarit_avec_lettre):
        offer_id = 304
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, decision="sans_lettre", statut="aucune")

        # Le gabarit sans lettre n'existe pas (seul gabarit_avec_lettre est posé) :
        # pointe vers un chemin tmp_path qui n'a jamais été écrit.
        missing_path = paths.MAIL_CANDIDATURE_SANS_LETTRE_PATH
        assert not missing_path.exists()

        with pytest.raises(HTTPException) as exc_info:
            api_mail.get_mail_candidature(offer_id)
        assert exc_info.value.status_code == 409
        assert str(missing_path) in exc_info.value.detail

    def test_erreur_sous_jacente_nomme_bien_le_fichier(self):
        with pytest.raises(GabaritAbsentError) as exc_info:
            raise GabaritAbsentError(paths.MAIL_CANDIDATURE_SANS_LETTRE_PATH)
        assert "mail_candidature_sans_lettre.md" in str(exc_info.value)


class TestCritere15AvecLettreMailInchange:
    def test_get_mail_rend_le_gabarit_normal(
        self, db_path, gabarit_avec_lettre, gabarit_sans_lettre
    ):
        offer_id = 305
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre(db_path, offer_id, decision="demandee", statut="done", pret=True)

        mail = api_mail.get_mail_candidature(offer_id)
        assert "lettre de motivation" in mail["corps"]

    def test_generer_appelle_le_modele_normalement(
        self, db_path, monkeypatch, tmp_path
    ):
        import orchestrator.job_search.mail.generation as generation_module
        import orchestrator.job_search.pdf.coordonnees as coordonnees_module

        offer_id = 306
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre(
            db_path,
            offer_id,
            decision="demandee",
            statut="done",
            texte="Ma lettre pour ce poste.",
        )

        coordonnees_path = tmp_path / "coordonnees.txt"
        coordonnees_path.write_text(
            "nom: Grégoire Marchand\nmail: g@example.com\n"
            "telephone: +33 6 00 00 00 00\nville: Strasbourg\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", coordonnees_path)

        consigne_path = tmp_path / "mail_consigne.md"
        consigne_path.write_text("Écris un mail court.", encoding="utf-8")
        monkeypatch.setattr(generation_module, "MAIL_CONSIGNE_PATH", consigne_path)

        from claude_agent_sdk import ResultMessage

        appels = []

        async def _query(*, prompt, options):
            appels.append((prompt, options))
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake-session",
                total_cost_usd=0.01,
                result=None,
                structured_output={"objet": "Objet généré", "corps": "Corps généré"},
            )

        monkeypatch.setattr(generation_module, "query", _query)

        import asyncio

        mail = asyncio.run(api_mail.post_mail_generer(offer_id))
        assert len(appels) == 1
        assert mail["objet"] == "Objet généré"


class TestCritere16CheminsDesGabaritsIsolesPourChaqueTest:
    def test_les_deux_chemins_pointent_hors_de_data_sans_fixture_dediee(self):
        """Aucune fixture de ce test ne pose de chemin : l'isolation vient de
        l'autouse `_isolate_mail_gabarit_paths` de conftest.py."""
        repo_data = paths.REPO_ROOT / "data"
        assert repo_data not in paths.MAIL_CANDIDATURE_PATH.parents
        assert repo_data not in paths.MAIL_CANDIDATURE_SANS_LETTRE_PATH.parents
        assert repo_data not in candidature_module.MAIL_CANDIDATURE_PATH.parents
        assert (
            repo_data
            not in candidature_module.MAIL_CANDIDATURE_SANS_LETTRE_PATH.parents
        )
