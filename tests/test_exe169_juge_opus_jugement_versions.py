"""Tests EXE-169 — le juge de la lettre tourne sur opus, et chaque version
garde le jugement qui l'a accompagnée.

Couvre les critères 1, 3, 4, 5, 6, 7, 8 de la fiche (le critère 2 — choisir
opus met les quatre nœuds sur opus — était déjà vrai avant cette fiche et
reste couvert par `test_exe166_choix_modele_lettre.py`).

La boucle (`generer_lettre_depuis_donnees`) est remplacée par une doublure qui
enregistre la configuration reçue et rend un `Jugement` explicite (H6 du
ticket) — aucun test n'appelle un modèle réel, aucun test ne lit ni n'écrit
sous data/ : la DB est un fichier tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
from fastapi import Response

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    Appel,
    Jugement,
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

JUGEMENT_OK = Jugement(
    rien_a_redire=True,
    ressenti="Ça sonne vrai.",
    details="Rien à signaler.",
    reussites="L'accroche tient.",
    verdict="À envoyer.",
)


def _resultat_avec_jugement(
    texte="Voici ma lettre.",
    fait_retenu=None,
    appels=None,
    jugement=JUGEMENT_OK,
    nb_tours=1,
    raison_fin=RAISON_RIEN_A_REDIRE,
) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=fait_retenu if fait_retenu is not None else GENERIQUE_ID,
        texte_type_id="tt1",
        lettres=[
            {
                "texte": texte,
                "nb_mots": len(texte.split()),
                "tournures_signalees": [],
                "jugement": jugement,
                "releve_redaction": None,
                "releve_correction": None,
            }
        ],
        nb_tours=nb_tours,
        raison_fin=raison_fin,
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


class TestCritere1JugeOpusParDefaut:
    def test_run_lettre_sans_modele_configure_opus_sur_le_juge_seul(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_avec_jugement()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id))

        config = captured["config"]
        assert config.modele_tamis == "sonnet"
        assert config.modele_redaction == "sonnet"
        assert config.modele_verificateur_effectif() == "sonnet"
        assert config.modele_juge == "opus"


class TestCritere3EnchainementAutomatiqueSuitJugeOpus:
    def test_launch_lettre_if_ready_configure_opus_sur_le_juge(
        self, db_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            captured["config"] = config
            return _resultat_avec_jugement()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            await api_lettre.launch_lettre_if_ready(offer_id)
            await _drain()

        asyncio.run(_scenario())
        assert captured["config"].modele_tamis == "sonnet"
        assert captured["config"].modele_juge == "opus"


class TestCritere4ModeleJugeEnregistreAPart:
    def test_lettre_et_version_portent_le_modele_juge_separement(
        self, db_path, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        row = _lettre_row(db_path, offer_id)
        assert row["modele"] == "sonnet"
        assert row["modele_juge"] == "opus"

        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[-1]["modele"] == "sonnet"
        assert versions[-1]["modele_juge"] == "opus"

    def test_regeneration_met_a_jour_le_modele_juge_enregistre(
        self, db_path, monkeypatch
    ):
        offer_id = 40
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "opus"))

        row = _lettre_row(db_path, offer_id)
        assert row["modele"] == "opus"
        assert row["modele_juge"] == "opus"


class TestCritere5AppelsPortentLeModeleReellementUtilise:
    def test_appel_du_juge_porte_opus_meme_avec_sonnet_choisi(
        self, db_path, monkeypatch
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)

        def _double(titre, texte_offre, entreprise, points_fiche, config, **_etape):
            appel_tamis = Appel(
                noeud="tamis",
                modele=config.modele_tamis,
                duree_s=1.0,
                cout_usd=0.01,
                demande="d",
                reponse="r",
            )
            appel_juge = Appel(
                noeud="juge",
                modele=config.modele_juge,
                duree_s=2.0,
                cout_usd=0.03,
                demande="d",
                reponse="r",
            )
            return _resultat_avec_jugement(appels=[appel_tamis, appel_juge])

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        row = _lettre_row(db_path, offer_id)
        appels = json.loads(row["appels_json"])
        par_noeud = {a["noeud"]: a["modele"] for a in appels}
        assert par_noeud["tamis"] == "sonnet"
        assert par_noeud["juge"] == "opus"


class TestCritere6VersionGardeLeJugement:
    def test_version_generee_porte_le_jugement_et_ses_quatre_rubriques(
        self, db_path, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(
                nb_tours=2, raison_fin=RAISON_PLAFOND
            ),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        versions = api_lettre.get_lettre_versions(offer_id)
        version = versions[-1]
        assert version["jugement"] == {
            "rien_a_redire": True,
            "ressenti": "Ça sonne vrai.",
            "details": "Rien à signaler.",
            "reussites": "L'accroche tient.",
            "verdict": "À envoyer.",
        }
        assert version["nb_tours"] == 2
        assert version["raison_fin"] == RAISON_PLAFOND


class TestCritere7JugementPrecedentIntactApresRegeneration:
    def test_regeneration_ne_touche_pas_le_jugement_de_la_version_avant(
        self, db_path, monkeypatch
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        jugement_1 = Jugement(
            rien_a_redire=False,
            ressenti="Il me recopie ma propre annonce.",
            details="Détail 1.",
            reussites="Réussite 1.",
            verdict="J'hésite.",
        )
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(
                jugement=jugement_1, nb_tours=1, raison_fin=RAISON_PLAFOND
            ),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        jugement_2 = Jugement(
            rien_a_redire=True,
            ressenti="Ça sonne vrai, cette fois.",
            details="Détail 2.",
            reussites="Réussite 2.",
            verdict="À envoyer.",
        )
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(
                texte="Régénérée.", jugement=jugement_2
            ),
        )
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "sonnet"))

        versions = api_lettre.get_lettre_versions(offer_id)
        assert len(versions) == 2
        assert versions[0]["jugement"]["ressenti"] == "Il me recopie ma propre annonce."
        assert versions[0]["raison_fin"] == RAISON_PLAFOND
        assert versions[1]["jugement"]["ressenti"] == "Ça sonne vrai, cette fois."


class TestCritere8ReprisesEtVersionsAnciennesSansJugement:
    def test_reprise_a_la_main_ne_porte_aucun_jugement(self, db_path, monkeypatch):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Texte repris à la main.")
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[-1]["origine"] == "moi"
        assert versions[-1]["jugement"] is None
        assert versions[-1]["nb_tours"] is None
        assert versions[-1]["raison_fin"] is None
        assert versions[-1]["modele_juge"] is None

    def test_version_ancienne_sans_colonnes_de_jugement_se_lit_sans_erreur(
        self, db_path
    ):
        offer_id = 80
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
        assert versions[0]["jugement"] is None
        assert versions[0]["nb_tours"] is None
        assert versions[0]["raison_fin"] is None
        assert versions[0]["modele_juge"] is None


class TestBypassApiExposeModeleJugeSurLaLettre:
    def test_get_lettre_rend_modele_juge(self, db_path, monkeypatch):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_jugement(),
        )

        async def _scenario():
            response = Response()
            await api_lettre.create_lettre(offer_id, response)
            await _drain()

        asyncio.run(_scenario())
        lettre = api_lettre.get_lettre(offer_id)
        assert lettre["modele"] == "sonnet"
        assert lettre["modele_juge"] == "opus"
