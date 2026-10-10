"""Tests EXE-166 — je choisis le modèle de la lettre dans l'app : sonnet par
défaut, opus si je veux.

Couvre les critères 1 à 7. La boucle (`generer_lettre_depuis_donnees`) est
remplacée par une doublure qui enregistre la configuration reçue (H6 du
ticket) — aucun test n'appelle un modèle réel, aucun test ne lit ni n'écrit
sous data/ : la DB est un fichier tmp_path.

Les doublures acceptent `**_etape` depuis EXE-167 : l'API passe toujours un
signal d'étape (`on_etape`) à cette fonction, que ces tests n'observent pas.
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
    Appel,
    ResultatBoucle,
)
from orchestrator.job_search.storage.db import init_db

FAIT_0 = {
    "position": "Point 0",
    "citation": "Citation 0",
    "url": "http://a",
    "tas": None,
}
POINTS = [FAIT_0]


def _resultat_ok(
    texte="Voici ma lettre.", fait_retenu=None, appels=None
) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=fait_retenu if fait_retenu is not None else GENERIQUE_ID,
        texte_type_id="tt1",
        lettres=[
            {
                "texte": texte,
                "nb_mots": len(texte.split()),
                "tournures_signalees": [],
                "jugement": None,
                "releve_redaction": None,
                "releve_correction": None,
            }
        ],
        nb_tours=1,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=appels if appels is not None else [],
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


def _insert_offer(
    db_path, offer_id, verdict="retenu", description_raw="Texte de l'offre."
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'ACME', ?)",
            (offer_id, str(offer_id), description_raw),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-10')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, points=POINTS, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, ?, 'Présentation', ?, 'ACME', '2026-10-10')",
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


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


def _jamais(*a, **k):
    raise AssertionError("la boucle a été appelée alors que le modèle est invalide")


class TestCritere1DefautSonnet:
    def test_run_lettre_sans_modele_configure_sonnet_sur_les_quatre_noeuds(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id))

        config = captured["config"]
        assert config.modele_tamis == "sonnet"
        assert config.modele_redaction == "sonnet"
        assert config.modele_juge == "sonnet"
        assert config.modele_verificateur_effectif() == "sonnet"

    def test_create_lettre_sans_corps_lance_sur_sonnet(self, db_path, monkeypatch):
        offer_id = 10
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            response = Response()
            result = await api_lettre.create_lettre(offer_id, response)
            assert response.status_code == 202
            assert result == {"statut": "pending"}
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "sonnet"


class TestCritere2ChoixOpus:
    def test_run_lettre_opus_configure_opus_sur_les_quatre_noeuds(
        self, db_path, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))

        config = captured["config"]
        assert config.modele_tamis == "opus"
        assert config.modele_redaction == "opus"
        assert config.modele_juge == "opus"
        assert config.modele_verificateur_effectif() == "opus"

    def test_create_lettre_avec_opus_dans_le_corps(self, db_path, monkeypatch):
        offer_id = 20
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            response = Response()
            await api_lettre.create_lettre(
                offer_id, response, api_lettre.ModeleLettreIn(modele="opus")
            )
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "opus"

    def test_regenerer_avec_opus(self, db_path, monkeypatch):
        offer_id = 21
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok("Régénérée.")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            response = Response()
            await api_lettre.regenerer_lettre(
                offer_id, response, api_lettre.ModeleLettreIn(modele="opus")
            )
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "opus"

    def test_ecarter_avec_opus(self, db_path, monkeypatch):
        offer_id = 22
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=FAIT_0),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok("Nouvelle accroche.", fait_retenu=None)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            response = Response()
            await api_lettre.ecarter_fait(
                offer_id, response, api_lettre.ModeleLettreIn(modele="opus")
            )
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "opus"


class TestCritere3ModeleInvalideRefuse:
    def test_create_lettre_refuse_modele_inconnu_sans_appeler_le_modele(
        self, db_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _jamais)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                api_lettre.create_lettre(
                    offer_id, Response(), api_lettre.ModeleLettreIn(modele="mistral")
                )
            )
        assert exc_info.value.status_code == 422
        assert "sonnet" in exc_info.value.detail
        assert "opus" in exc_info.value.detail
        assert _lettre_row(db_path, offer_id) is None

    def test_regenerer_refuse_modele_inconnu_et_garde_la_lettre_en_place(
        self, db_path, monkeypatch
    ):
        offer_id = 30
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok("Lettre stable."),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))
        avant = _lettre_row(db_path, offer_id)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _jamais)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                api_lettre.regenerer_lettre(
                    offer_id, Response(), api_lettre.ModeleLettreIn(modele="llama3")
                )
            )
        assert exc_info.value.status_code == 422
        assert "sonnet" in exc_info.value.detail
        assert "opus" in exc_info.value.detail

        apres = _lettre_row(db_path, offer_id)
        assert apres["texte"] == avant["texte"] == "Lettre stable."
        assert apres["regeneration_en_cours"] == 0

    def test_ecarter_refuse_modele_inconnu_et_garde_le_fait_retenu(
        self, db_path, monkeypatch
    ):
        offer_id = 31
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=FAIT_0),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _jamais)

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                api_lettre.ecarter_fait(
                    offer_id, Response(), api_lettre.ModeleLettreIn(modele="gpt4")
                )
            )
        assert exc_info.value.status_code == 422

        row = _lettre_row(db_path, offer_id)
        assert json.loads(row["faits_ecartes_json"]) == []
        assert row["regeneration_en_cours"] == 0

    def test_service_valider_modele_leve_pour_un_modele_hors_liste(self):
        with pytest.raises(lettre_service.ModeleInvalideError) as exc_info:
            lettre_service.valider_modele("ollama")
        assert "sonnet" in str(exc_info.value)
        assert "opus" in str(exc_info.value)


class TestCritere4EnchainementAutomatiqueSonnet:
    def test_launch_lettre_if_ready_configure_toujours_sonnet(
        self, db_path, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            await api_lettre.launch_lettre_if_ready(offer_id)
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "sonnet"


class TestCritere5LettrePorteLeModele:
    def test_lettre_enregistree_porte_opus(self, db_path, monkeypatch):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))
        row = _lettre_row(db_path, offer_id)
        assert row["modele"] == "opus"

    def test_regeneration_met_a_jour_le_modele_enregistre(self, db_path, monkeypatch):
        offer_id = 50
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "opus"))
        row = _lettre_row(db_path, offer_id)
        assert row["modele"] == "opus"


class TestCritere6VersionsPortentLeModele:
    def test_version_generee_porte_le_modele(self, db_path, monkeypatch):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))
        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[-1]["modele"] == "opus"
        assert versions[-1]["origine"] == "modele"

    def test_reprise_a_la_main_ne_porte_aucun_modele(self, db_path, monkeypatch):
        offer_id = 60
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Texte repris à la main.")
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[-1]["origine"] == "moi"
        assert versions[-1]["modele"] is None

    def test_version_ancienne_sans_colonne_remplie_se_lit_sans_erreur(self, db_path):
        offer_id = 61
        _insert_offer(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettre_versions (offer_id, texte, origine, created_at) "
            "VALUES (?, 'Ancienne version.', 'modele', '2026-09-01')",
            (offer_id,),
        )
        conn.commit()
        conn.close()

        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[0]["modele"] is None
        assert versions[0]["texte"] == "Ancienne version."


class TestCritere7AppelsPortentLeModeleUtilise:
    def test_appels_enregistres_portent_le_modele_choisi(self, db_path, monkeypatch):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            appel = Appel(
                noeud="tamis",
                modele=config.modele_tamis,
                duree_s=1.0,
                cout_usd=0.02,
                demande="demande",
                reponse="réponse",
            )
            return _resultat_ok(appels=[appel])

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))

        row = _lettre_row(db_path, offer_id)
        appels = json.loads(row["appels_json"])
        assert appels[0]["modele"] == "opus"
