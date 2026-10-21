"""Tests EXE-195 — retenir ne lance plus la lettre : elle attend mon geste
« Générer la lettre » ou « Ne pas faire de lettre pour cette annonce ».

Aucun test n'appelle un modèle réel : `lettre_service.generer_lettre_depuis_donnees`
est remplacé par une doublure qui compte ses appels (comme EXE-132/166/169).
Aucun test ne lit ni n'écrit sous data/ : DB sous `tmp_path` (fixture `db_path`,
comme EXE-101).
"""

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException, Response

import api.db as api_db
import api.lettre as api_lettre
import api.pieces as api_pieces
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.pieces as pieces_mod
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_RIEN_A_REDIRE,
    Jugement,
    ResultatBoucle,
)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(db_path, offer_id, retenue=True):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        if retenue:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, statut="done", error_message=None, points=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, error_message, created_at) VALUES (?, ?, 'Présentation', ?, ?, ?)",
            (
                offer_id,
                statut,
                json.dumps(points or [], ensure_ascii=False),
                error_message,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(
    db_path,
    offer_id,
    statut="aucune",
    decision="a_decider",
    marque_pret_at=None,
    regeneration_en_cours=0,
    texte=None,
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, "
            "regeneration_en_cours, texte, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                offer_id,
                statut,
                decision,
                marque_pret_at,
                regeneration_en_cours,
                texte,
                _now(),
            ),
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


def _fiche_statut(db_path, offer_id, statut, error_message=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE fiches_entreprise SET statut = ?, error_message = ? WHERE offer_id = ?",
            (statut, error_message, offer_id),
        )
        conn.commit()
    finally:
        conn.close()


def _resultat_ok(texte="Voici ma lettre de motivation.") -> ResultatBoucle:
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


def _jamais_appele(*a, **k):
    raise AssertionError("aucun appel de modèle n'est attendu dans ce scénario")


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


class TestCritere1RetenirNeLancePasLaLettre:
    def test_fin_de_fiche_sans_demande_ne_lance_pas_la_lettre(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _jamais_appele
        )

        async def _scenario():
            task = await api_lettre.launch_lettre_if_ready(offer_id)
            if task is not None:
                await task
            await _drain()

        asyncio.run(_scenario())

        row = _lettre_row(db_path, offer_id)
        assert row is None or row["statut"] == "aucune"


class TestCritere3GenererQuandFicheTerminee:
    def test_generer_lance_tout_de_suite_quand_fiche_terminee(
        self, db_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )

        async def _scenario():
            await api_lettre.create_lettre(offer_id, Response())
            await _drain()

        asyncio.run(_scenario())

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["decision"] == pieces_mod.DECISION_DEMANDEE


class TestCritere4GenererPendantFicheEnCoursAttendPuisPart:
    def test_demande_pendant_la_fiche_part_toute_seule_a_la_fin(
        self, db_path, monkeypatch
    ):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _jamais_appele
        )

        response = Response()
        resultat = asyncio.run(api_lettre.create_lettre(offer_id, response))
        assert response.status_code == 202
        assert resultat["statut"] == "pending"

        row = _lettre_row(db_path, offer_id)
        assert row["decision"] == pieces_mod.DECISION_DEMANDEE
        assert row["statut"] == "aucune"  # pas encore lancée

        # La fiche se termine : la lettre part d'elle-même.
        _fiche_statut(db_path, offer_id, "done")
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )

        async def _fin_de_fiche():
            task = await api_lettre.launch_lettre_if_ready(offer_id)
            if task is not None:
                await task
            await _drain()

        asyncio.run(_fin_de_fiche())

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


class TestCritere5FicheEnErreurApresDemande:
    def test_fiche_en_erreur_apres_demande_ne_lance_pas_et_la_carte_le_dit(
        self, db_path, monkeypatch
    ):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _jamais_appele
        )

        asyncio.run(api_lettre.create_lettre(offer_id, Response()))

        _fiche_statut(db_path, offer_id, "error", error_message="Boum.")

        async def _fin_de_fiche():
            task = await api_lettre.launch_lettre_if_ready(offer_id)
            if task is not None:
                await task
            await _drain()

        asyncio.run(_fin_de_fiche())

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "aucune"

        pieces = api_pieces.get_pieces(offer_id)
        assert pieces["lettre_carte"]["statut"] == pieces_mod.CARTE_DEMANDEE
        assert pieces["lettre_carte"]["message"] == "Boum."


class TestCritere7NePasFaireDeLettre:
    def test_choisir_sans_lettre_aucun_appel_et_la_carte_le_dit(
        self, db_path, monkeypatch
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _jamais_appele
        )

        asyncio.run(api_lettre.ne_pas_faire_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["decision"] == pieces_mod.DECISION_SANS_LETTRE

        pieces = api_pieces.get_pieces(offer_id)
        assert pieces["lettre_carte"]["statut"] == pieces_mod.CARTE_SANS_LETTRE


class TestCritere8RevenirSansLettreJamaisGeneree:
    def test_revenir_quand_jamais_generee_remet_a_decider(self, db_path):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="aucune", decision="sans_lettre")

        asyncio.run(api_lettre.revenir_sur_choix_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["decision"] == pieces_mod.DECISION_A_DECIDER


class TestCritere9RevenirSurLettreDejaGeneree:
    def test_revenir_sur_lettre_generee_garde_texte_et_versions(self, db_path):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _insert_lettre(
            db_path,
            offer_id,
            statut="done",
            decision="sans_lettre",
            texte="Ma lettre déjà écrite.",
        )
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettre_versions (offer_id, texte, origine, created_at) "
            "VALUES (?, 'Ma lettre déjà écrite.', 'modele', ?)",
            (offer_id, _now()),
        )
        conn.commit()
        conn.close()

        asyncio.run(api_lettre.revenir_sur_choix_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["decision"] == pieces_mod.DECISION_DEMANDEE
        assert row["texte"] == "Ma lettre déjà écrite."

        conn = sqlite3.connect(db_path)
        n_versions = conn.execute(
            "SELECT COUNT(*) FROM lettre_versions WHERE offer_id = ?", (offer_id,)
        ).fetchone()[0]
        conn.close()
        assert n_versions == 1


class TestCritere10EffaceLaMarquePrete:
    def test_sans_lettre_efface_la_marque_prete(self, db_path):
        offer_id = 10
        _insert_offer(db_path, offer_id)
        _insert_lettre(
            db_path,
            offer_id,
            statut="done",
            decision="demandee",
            marque_pret_at=_now(),
        )

        asyncio.run(api_lettre.ne_pas_faire_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["marque_pret_at"] is None


class TestCritere11RefusePendantGeneration:
    def test_sans_lettre_refuse_pendant_une_regeneration_en_cours(self, db_path):
        offer_id = 11
        _insert_offer(db_path, offer_id)
        _insert_lettre(
            db_path,
            offer_id,
            statut="done",
            decision="demandee",
            regeneration_en_cours=1,
        )

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.ne_pas_faire_lettre(offer_id))
        assert exc_info.value.status_code == 409

        row = _lettre_row(db_path, offer_id)
        assert row["decision"] == pieces_mod.DECISION_DEMANDEE

    def test_sans_lettre_refuse_pendant_une_premiere_generation_en_cours(self, db_path):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="pending", decision="demandee")
        api_lettre._running.add(offer_id)
        try:
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(api_lettre.ne_pas_faire_lettre(offer_id))
            assert exc_info.value.status_code == 409
        finally:
            api_lettre._running.discard(offer_id)


class TestCritere12PersisteApresNouvelleConnexion:
    def test_decision_survit_a_une_nouvelle_lecture(self, db_path):
        offer_id = 13
        _insert_offer(db_path, offer_id)
        asyncio.run(api_lettre.ne_pas_faire_lettre(offer_id))

        # Simule un redémarrage de l'API : nouvelle connexion, rien en mémoire.
        pieces = api_pieces.get_pieces(offer_id)
        assert pieces["lettre_carte"]["statut"] == pieces_mod.CARTE_SANS_LETTRE


def _creer_base_avant_exe195(path):
    """Schéma `lettres` de 2f2d553 (avant la colonne `decision`, EXE-195) —
    identique à `db.py` avant ce ticket, vérifié par `git diff 2f2d553 HEAD --
    orchestrator/job_search/storage/db.py` (aucune différence)."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE offers (
            id          INTEGER PRIMARY KEY,
            source      TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            title       TEXT
        );
        CREATE TABLE lettres (
            id                        INTEGER PRIMARY KEY,
            offer_id                  INTEGER NOT NULL REFERENCES offers(id),
            statut                    TEXT NOT NULL DEFAULT 'aucune',
            points_choisis_json       TEXT,
            points_choisis_origine    TEXT,
            texte                     TEXT,
            tournures_signalees_json  TEXT,
            nb_mots                   INTEGER,
            depasse_longueur          INTEGER,
            modele                    TEXT,
            modele_juge               TEXT,
            session_id                TEXT,
            cost_usd                  REAL,
            prompt_text               TEXT,
            error_message             TEXT,
            created_at                TEXT NOT NULL,
            regeneration_en_cours     INTEGER NOT NULL DEFAULT 0,
            regeneration_error        TEXT,
            marque_pret_at            TEXT,
            fait_retenu_json          TEXT,
            texte_type_id             TEXT,
            nb_tours                  INTEGER,
            raison_fin                TEXT,
            jugement_json             TEXT,
            releve_json               TEXT,
            appels_json               TEXT,
            faits_ecartes_json        TEXT NOT NULL DEFAULT '[]',
            angle                     TEXT,
            UNIQUE(offer_id)
        );
    """)
    conn.commit()
    return conn


def _offer_195(conn, offer_id):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title) "
        "VALUES (?, 'test', ?, ?, ?)",
        (offer_id, str(offer_id), f"fp{offer_id}", "Titre"),
    )


def _lettre_195(conn, offer_id, statut, marque_pret_at=None):
    conn.execute(
        "INSERT INTO lettres (offer_id, statut, marque_pret_at, created_at) "
        "VALUES (?, ?, ?, ?)",
        (offer_id, statut, marque_pret_at, "2026-10-21T16:28:00+00:00"),
    )


# EXE-195, H2 : base de Grégoire relue le 21 octobre 2026 à 16:28 — 10 lettres,
# 9 à `done` dont 5 marquées Prêtes, une à `pending`.
_OFFRES_PRETES = [3962, 3974, 3981, 4181, 4182]
_OFFRES_DONE_NON_PRETES = [5001, 5002, 5003, 5004]
_OFFRE_PENDING = 4183


class TestCritere15BaseDAujourdhuiSOuvreSansGesteManuel:
    def test_dix_lettres_dune_base_avant_exe195_gardent_leur_etat(self, tmp_path):
        path = tmp_path / "grégoire.sqlite"
        conn = _creer_base_avant_exe195(path)
        for offer_id in _OFFRES_PRETES:
            _offer_195(conn, offer_id)
            _lettre_195(
                conn, offer_id, "done", marque_pret_at="2026-10-20T08:00:00+00:00"
            )
        for offer_id in _OFFRES_DONE_NON_PRETES:
            _offer_195(conn, offer_id)
            _lettre_195(conn, offer_id, "done")
        _offer_195(conn, _OFFRE_PENDING)
        _lettre_195(conn, _OFFRE_PENDING, "pending")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)

        rows = {
            row["offer_id"]: row
            for row in conn.execute("SELECT * FROM lettres").fetchall()
        }
        conn.close()

        assert len(rows) == 10
        for offer_id in _OFFRES_PRETES:
            assert rows[offer_id]["statut"] == "done"
            assert rows[offer_id]["marque_pret_at"] is not None
            assert rows[offer_id]["decision"] == pieces_mod.DECISION_DEMANDEE
        for offer_id in _OFFRES_DONE_NON_PRETES:
            assert rows[offer_id]["statut"] == "done"
            assert rows[offer_id]["marque_pret_at"] is None
            assert rows[offer_id]["decision"] == pieces_mod.DECISION_DEMANDEE
        assert rows[_OFFRE_PENDING]["statut"] == "pending"
        assert rows[_OFFRE_PENDING]["decision"] == pieces_mod.DECISION_DEMANDEE

        for row in rows.values():
            assert row["decision"] != pieces_mod.DECISION_A_DECIDER
            assert row["decision"] != pieces_mod.DECISION_SANS_LETTRE


class TestCritere16OuvrirDeuxFoisNeRetoucheRien:
    def test_deuxieme_ouverture_garde_une_decision_changee_depuis(self, tmp_path):
        path = tmp_path / "grégoire.sqlite"
        conn = _creer_base_avant_exe195(path)
        _offer_195(conn, 1)
        _lettre_195(conn, 1, "done")
        conn.commit()
        conn.close()

        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        conn.execute("UPDATE lettres SET decision = 'sans_lettre' WHERE offer_id = 1")
        conn.commit()
        conn.close()

        # Deuxième démarrage de l'API sur la même base.
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        init_db(conn)
        row = conn.execute("SELECT * FROM lettres WHERE offer_id = 1").fetchone()
        conn.close()

        assert row["decision"] == "sans_lettre"


OFFER_PAGE = (
    Path(__file__).resolve().parent.parent
    / "web"
    / "app"
    / "pages"
    / "offers"
    / "[id].vue"
)


class TestCritere14FrontNeDecidePlusLesBoutonsDeLaCarteLettre:
    def test_boutons_generer_ne_pas_faire_revenir_lus_depuis_lettre_carte(self):
        texte = OFFER_PAGE.read_text(encoding="utf-8")
        # Ancien calcul fautif : le bouton « Générer la lettre » était montré
        # et activé par comparaison directe de `lettre.statut`.
        assert "lettre.statut === 'error' || lettre.statut === 'aucune'" not in texte
        # Les trois boutons sont rendus depuis la carte Lettre de l'API —
        # visible/actif/libellé/raison, jamais recalculés ici.
        assert "lettreCarte" in texte
        assert not re.search(r"v-if=\"!lettre \|\| lettre\.statut", texte)
        assert "bouton.actif" in texte
        assert "bouton.libelle" in texte
        assert (
            "bouton.visible" not in texte
        )  # filtré une fois, en amont (lettreCarteBoutonsVisibles)
