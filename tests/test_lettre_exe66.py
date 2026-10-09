"""Tests EXE-66 — reprise du texte de la lettre, historique des versions, régénération.

Couvre : enregistrement du texte repris (critères 1-3, 5-7), historique à 3 versions
(critère 4), régénération (critères 8-13).

Aucun test n'appelle le modèle : `generer_lettre_depuis_donnees` (EXE-162, la boucle
appelée par `service.py`) est remplacée par une doublure qui rend un résultat de
boucle déjà construit — jamais par un appel réel. Aucun test ne lit ni n'écrit sous
data/ : DB, tournures interdites et CV de référence sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from fastapi import HTTPException, Response

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_RIEN_A_REDIRE,
    Jugement,
    ResultatBoucle,
)
from orchestrator.job_search.storage.db import init_db

PREFERENCES_TON = "# Préférences de ton\n- Direct, sans emphase\n"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\ncordialement\n"


def _resultat_ok(texte: str) -> ResultatBoucle:
    lettre = {
        "texte": texte,
        "nb_mots": len(texte.split()),
        "tournures_signalees": [],
        "jugement": Jugement(
            rien_a_redire=True, ressenti="bien", details="d", reussites="r", verdict="v"
        ),
        "releve_redaction": {"tournures": [], "lieux": [], "affirmations": []},
        "releve_correction": None,
    }
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id="tt",
        lettres=[lettre],
        nb_tours=1,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
    )


def _resultat_echec(raison: str = "échec du modèle") -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id="tt",
        lettres=[],
        nb_tours=0,
        raison_fin=raison,
        appels=[],
        erreur_type="appel_echoue",
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
def lettre_fixture_paths(tmp_path, monkeypatch):
    tournures = tmp_path / "tournures_interdites.txt"
    tournures.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    cv_ref = tmp_path / "cv_reference.html"
    cv_ref.write_text("<p>Contenu CV de test</p>", encoding="utf-8")
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    return tournures, cv_ref


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, description_raw) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-28')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _points_8() -> list[dict]:
    tas_par_index = ["lettre", "lettre", "entretien", "rien", None, None, None, None]
    return [
        {
            "position": f"Point {i}",
            "citation": f"Citation {i}",
            "url": None,
            "tas": tas,
            "explication": None,
        }
        for i, tas in enumerate(tas_par_index)
    ]


def _insert_fiche(db_path, offer_id, points, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, ?, 'Présentation', ?, '2026-09-28')",
            (offer_id, statut, json.dumps(points, ensure_ascii=False)),
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


def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _generer_lettre_prete(
    db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre initiale."
):
    """Fait exister une lettre `done` pour l'offre, sans passer par la route HTTP."""
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id, _points_8())

    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_ok(texte),
    )
    asyncio.run(lettre_service.run_lettre(offer_id))


class TestCritere1TexteRepriteEtGarde:
    def test_texte_modifie_relu_tel_quel(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Mon texte à moi.")
        )
        result = api_lettre.get_lettre(offer_id)
        assert result["texte"] == "Mon texte à moi."


class TestCritere2TournureSignaleeSurMonTexte:
    def test_tournure_signalee_texte_non_corrige(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Je veux rejoindre votre équipe.")
        )
        assert result["texte"] == "Je veux rejoindre votre équipe."
        assert result["tournures_signalees"] == ["Je veux"]


class TestCritere3DepassementLongueurSignale:
    def test_420_mots_signale_avec_le_compte(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 3
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)
        texte_420 = " ".join(["mot"] * 420)

        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte=texte_420)
        )
        assert result["depasse_longueur"] is True
        assert result["nb_mots"] == 420


class TestCritere4HistoriqueTroisVersionsOrdre:
    def test_deux_modifications_rendent_trois_versions_dans_l_ordre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 4
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Version modèle.",
        )

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma première reprise.")
        )
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma deuxième reprise.")
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        assert len(versions) == 3
        assert [v["texte"] for v in versions] == [
            "Version modèle.",
            "Ma première reprise.",
            "Ma deuxième reprise.",
        ]
        assert [v["origine"] for v in versions] == ["modele", "moi", "moi"]
        for v in versions:
            assert v["created_at"]


class TestCritere5RefusTexteVide:
    def test_texte_vide_refuse_lettre_inchangee(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 5
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        with pytest.raises(HTTPException) as exc_info:
            api_lettre.put_lettre_texte(offer_id, api_lettre.LettreTexteIn(texte="   "))
        assert exc_info.value.status_code == 422
        assert exc_info.value.detail
        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Lettre initiale."
        versions = api_lettre.get_lettre_versions(offer_id)
        assert [v["texte"] for v in versions] == ["Lettre initiale."]


class TestCritere6RefusSansLettrePrete:
    def test_refuse_offre_sans_lettre(self, db_path, lettre_fixture_paths):
        offer_id = 6
        _insert_offer(db_path, offer_id)

        with pytest.raises(HTTPException) as exc_info:
            api_lettre.put_lettre_texte(
                offer_id, api_lettre.LettreTexteIn(texte="Un texte quelconque.")
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail


class TestCritere7AucunAppelModeleAEnregistrement:
    def test_save_texte_n_appelle_jamais_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 7
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)

        def _forbidden(*a, **k):
            raise AssertionError("le modèle a été appelé pour un simple enregistrement")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _forbidden)
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Texte sans modèle.")
        )
        assert _lettre_row(db_path, offer_id)["texte"] == "Texte sans modèle."


class TestCritere8Regeneration:
    def test_regenerer_appelle_le_modele_et_rend_une_nouvelle_lettre(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 8
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Ancienne lettre.",
        )

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok("Nouvelle lettre régénérée."),
        )
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))
        assert response.status_code == 202

        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Nouvelle lettre régénérée."

    def test_redemander_sans_regenerer_rend_inchange(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 80
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )

        def _forbidden(*a, **k):
            raise AssertionError("le modèle a été rappelé par un simple redemander")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _forbidden)
        response = Response()
        result = asyncio.run(api_lettre.create_lettre(offer_id, response))
        assert response.status_code == 200
        assert result["texte"] == "Lettre stable."


class TestCritere10HistoriqueApresRegeneration:
    def test_historique_garde_la_precedente_et_ajoute_la_nouvelle_en_dernier(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 10
        _generer_lettre_prete(
            db_path,
            lettre_fixture_paths,
            monkeypatch,
            offer_id,
            texte="Version modèle.",
        )
        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Ma reprise.")
        )

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok("Version régénérée."),
        )
        response = Response()
        asyncio.run(api_lettre.regenerer_lettre(offer_id, response))

        versions = api_lettre.get_lettre_versions(offer_id)
        assert [v["texte"] for v in versions] == [
            "Version modèle.",
            "Ma reprise.",
            "Version régénérée.",
        ]
        assert versions[-1]["origine"] == "modele"


class TestCritere11EchecRegenerationGardeVersionAvant:
    def test_echec_du_modele_garde_la_version_d_avant_et_signale_l_echec(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 11
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        avant = _lettre_row(db_path, offer_id)

        def _behavior(*a, **k):
            raise RuntimeError("SDK indisponible")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _behavior)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        apres = _lettre_row(db_path, offer_id)
        assert apres["texte"] == avant["texte"] == "Lettre stable."
        assert apres["tournures_signalees_json"] == avant["tournures_signalees_json"]
        assert apres["statut"] == "done"
        assert apres["regeneration_en_cours"] == 0
        assert apres["regeneration_error"]

    def test_timeout_garde_la_version_d_avant(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 110
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_echec(
                "L'appel au modèle du nœud « redaction » a dépassé son délai"
            ),
        )
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == "Lettre stable."
        assert row["regeneration_error"]


class TestCritere12LectureRegenerationEnCours:
    def test_relire_pendant_regeneration_rend_la_version_d_avant_et_le_signale(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 12
        _generer_lettre_prete(
            db_path, lettre_fixture_paths, monkeypatch, offer_id, texte="Lettre stable."
        )
        conn = _connect(db_path)
        try:
            lettre_service.mark_regenerating(conn, offer_id)
        finally:
            conn.close()

        result = api_lettre.get_lettre(offer_id)
        assert result["texte"] == "Lettre stable."
        assert result["regeneration_en_cours"] is True


class TestCritere13RefusRegenerationOffreNonRetenueOuSansLettre:
    def test_refuse_offre_non_retenue_sans_appeler_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 13
        _insert_offer(db_path, offer_id, verdict="candidaté")

        def _forbidden(*a, **k):
            raise AssertionError("le modèle a été appelé pour une offre non retenue")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _forbidden)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.regenerer_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409

    def test_refuse_sans_lettre_prete_sans_appeler_le_modele(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 130
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        def _forbidden(*a, **k):
            raise AssertionError("le modèle a été appelé sans lettre prête")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _forbidden)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.regenerer_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
