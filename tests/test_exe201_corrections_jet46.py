"""Tests EXE-201 — correction du jet 46 : une lettre en erreur se relance, la
lettre n'est jamais lancée sur une offre qui n'est plus retenue, la frise et
l'historique suivent l'API, et Suivi compte les offres filtrées à
l'ingestion mais retenues.

DB sous `tmp_path` (fixture `db_path`), aucun appel modèle réel — toute
génération est remplacée par une doublure qui compte ses appels ou refuse
d'être appelée (`_jamais_appele`), comme EXE-132/166/169/195.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

import api.db as api_db
import api.lettre as api_lettre
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


def _insert_offer(db_path, offer_id, retenue=True, filtered_out=False):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, filtered_out) VALUES (?, 'test', ?, 'fp', 'Titre', "
            "'Texte de l offre', ?)",
            (offer_id, str(offer_id), 1 if filtered_out else 0),
        )
        if retenue:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, statut="done", error_message=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, error_message, created_at) VALUES (?, ?, 'Présentation', "
            "'[]', ?, ?)",
            (offer_id, statut, error_message, _now()),
        )
        conn.commit()
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


def _insert_lettre(
    db_path,
    offer_id,
    statut="aucune",
    decision="a_decider",
    marque_pret_at=None,
    regeneration_en_cours=0,
    error_message=None,
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, "
            "regeneration_en_cours, error_message, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?)",
            (
                offer_id,
                statut,
                decision,
                marque_pret_at,
                regeneration_en_cours,
                error_message,
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


def _geste(client, offer_id, geste, **kwargs):
    body = {"geste": geste, **kwargs}
    return client.post(f"/offers/{offer_id}/geste", json=body)


# ---------------------------------------------------------------------------
# F1 / critères 1, 2, 4, 5 — la lettre en erreur
# ---------------------------------------------------------------------------


class TestCritere1LettreEnErreurApresGeneration:
    def test_statut_brut_error_rend_en_erreur_avec_message_et_generer_actif(self):
        carte = pieces_mod.carte_lettre(
            pieces_mod.DECISION_DEMANDEE,
            "error",
            None,
            False,
            "done",
            None,
            lettre_error_message="Le modèle a timeout.",
        )
        assert carte["statut"] == pieces_mod.CARTE_EN_ERREUR
        assert carte["message"] == "Le modèle a timeout."
        generer = next(
            b for b in carte["boutons"] if b["bouton"] == pieces_mod.BOUTON_GENERER
        )
        assert generer["actif"] is True
        assert generer["visible"] is True


class TestCritere2LettreOrphelineApresRedemarrage:
    def test_pending_sans_generation_en_cours_rend_en_erreur(self):
        carte = pieces_mod.carte_lettre(
            pieces_mod.DECISION_DEMANDEE,
            "pending",
            None,
            False,
            "done",
            None,
            lettre_error_message=None,
        )
        assert carte["statut"] == pieces_mod.CARTE_EN_ERREUR
        assert carte["message"] == pieces_mod.RAISON_GENERATION_INTERROMPUE
        generer = next(
            b for b in carte["boutons"] if b["bouton"] == pieces_mod.BOUTON_GENERER
        )
        assert generer["actif"] is True

    def test_pending_avec_generation_en_cours_reste_en_generation(self):
        """Non-régression : une génération réellement en cours ne doit pas
        basculer en erreur."""
        carte = pieces_mod.carte_lettre(
            pieces_mod.DECISION_DEMANDEE, "pending", None, True, "done", None
        )
        assert carte["statut"] == pieces_mod.CARTE_EN_GENERATION


class TestCritere3GenererRelanceDepuisErreurOuOrpheline:
    @pytest.mark.parametrize("statut_initial", ["error", "pending"])
    def test_generer_relance_et_la_carte_passe_en_generation(
        self, db_path, monkeypatch, statut_initial
    ):
        offer_id = 30 if statut_initial == "error" else 31
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(db_path, offer_id, statut=statut_initial, decision="demandee")
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )

        async def _scenario():
            await api_lettre.create_lettre(offer_id, Response())
            assert api_lettre.is_running(offer_id)
            with api_db.get_conn() as conn:
                carte = api_lettre.carte_lettre_for_offer(conn, offer_id)
            assert carte["statut"] == pieces_mod.CARTE_EN_GENERATION
            await _drain()

        asyncio.run(_scenario())
        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


class TestCritere4RevenirSurSansLettreQuandLettreEnErreur:
    def test_revenir_rend_en_erreur_avec_generer_actif(self, db_path):
        offer_id = 40
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(
            db_path,
            offer_id,
            statut="error",
            decision="sans_lettre",
            error_message="Boum.",
        )

        async def _scenario():
            return await api_lettre.revenir_sur_choix_lettre(offer_id)

        carte = asyncio.run(_scenario())
        assert carte["statut"] == pieces_mod.CARTE_EN_ERREUR
        assert carte["message"] == "Boum."
        generer = next(
            b for b in carte["boutons"] if b["bouton"] == pieces_mod.BOUTON_GENERER
        )
        assert generer["actif"] is True


class TestCritere5MiniCarteEtOngletDisentLeMemeEtat:
    def test_les_sept_etats_sont_distincts_et_coherents(self):
        """Non-régression de contrat : `carte_lettre` doit pouvoir produire
        chacun des sept statuts affichés — la mini-carte (front) ne lit que
        ce champ, jamais une logique à elle (critère 5)."""
        cas = [
            (
                pieces_mod.DECISION_A_DECIDER,
                "aucune",
                None,
                False,
                None,
                None,
                None,
                pieces_mod.CARTE_A_DECIDER,
            ),
            (
                pieces_mod.DECISION_DEMANDEE,
                "aucune",
                None,
                False,
                "pending",
                None,
                None,
                pieces_mod.CARTE_DEMANDEE,
            ),
            (
                pieces_mod.DECISION_DEMANDEE,
                "pending",
                None,
                True,
                "done",
                None,
                None,
                pieces_mod.CARTE_EN_GENERATION,
            ),
            (
                pieces_mod.DECISION_DEMANDEE,
                "done",
                None,
                False,
                "done",
                None,
                None,
                pieces_mod.CARTE_GENEREE,
            ),
            (
                pieces_mod.DECISION_DEMANDEE,
                "done",
                "2026-10-22T10:00:00+00:00",
                False,
                "done",
                None,
                None,
                pieces_mod.CARTE_PRETE,
            ),
            (
                pieces_mod.DECISION_SANS_LETTRE,
                "aucune",
                None,
                False,
                None,
                None,
                None,
                pieces_mod.CARTE_SANS_LETTRE,
            ),
            (
                pieces_mod.DECISION_DEMANDEE,
                "error",
                None,
                False,
                "done",
                None,
                "Boum.",
                pieces_mod.CARTE_EN_ERREUR,
            ),
        ]
        statuts = set()
        for (
            decision,
            statut_brut,
            marque,
            en_cours,
            fiche_statut,
            fiche_err,
            lettre_err,
            attendu,
        ) in cas:
            carte = pieces_mod.carte_lettre(
                decision,
                statut_brut,
                marque,
                en_cours,
                fiche_statut,
                fiche_err,
                lettre_error_message=lettre_err,
            )
            assert carte["statut"] == attendu
            statuts.add(carte["statut"])
        assert len(statuts) == 7


# ---------------------------------------------------------------------------
# F8 / critère 6 — la lettre ne part pas si l'offre n'est plus retenue
# ---------------------------------------------------------------------------


class TestCritere6LettreNePartPasSiLoffreNestPlusRetenue:
    def test_fin_de_fiche_ne_lance_pas_si_loffre_a_ete_annulee_entretemps(
        self, db_path, monkeypatch
    ):
        offer_id = 60
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _jamais_appele
        )

        asyncio.run(api_lettre.create_lettre(offer_id, Response()))

        _fiche_statut(db_path, offer_id, "done")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # L'offre n'est plus retenue : on annule le geste « retenir ».
            suivi_storage.annuler_dernier_geste(conn, offer_id)
        finally:
            conn.close()

        async def _fin_de_fiche():
            task = await api_lettre.launch_lettre_if_ready(offer_id)
            if task is not None:
                await task
            await _drain()

        asyncio.run(_fin_de_fiche())

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "aucune"

    def test_fin_de_fiche_lance_toujours_quand_loffre_reste_retenue(
        self, db_path, monkeypatch
    ):
        """Non-régression : le cas nominal (offre toujours retenue) part
        toujours à la fin de la fiche (critères 3-4 d'EXE-195)."""
        offer_id = 61
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )

        asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        _fiche_statut(db_path, offer_id, "done")

        async def _fin_de_fiche():
            task = await api_lettre.launch_lettre_if_ready(offer_id)
            if task is not None:
                await task
            await _drain()

        asyncio.run(_fin_de_fiche())

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"


# ---------------------------------------------------------------------------
# F4 / critère 13 — la frise finit par l'étape de fin, montrée acquise
# ---------------------------------------------------------------------------


class TestCritere13FriseFinitParLetapeDeFinAcquise:
    def test_offre_recue_est_acquise_et_termine_la_frise(self, client, db_path):
        offer_id = 130
        _insert_offer(db_path, offer_id)
        for g in ["marquer_envoyee", "entretien", "offre_recue"]:
            assert _geste(client, offer_id, g).status_code == 200, g
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etapes_affichees"][-1] == "offre_recue"
        assert detail["etapes_acquises"][-1] == "offre_recue"
        assert "entretien" in detail["etapes_acquises"]
        assert "candidature_envoyee" in detail["etapes_acquises"]

    def test_abandon_depuis_retenue_finit_par_abandonnee_acquise(self, client, db_path):
        offer_id = 131
        _insert_offer(db_path, offer_id)
        assert _geste(client, offer_id, "abandonner").status_code == 200
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etapes_acquises"] == ["retenue", "abandonnee"]

    def test_refusee_depuis_candidature_envoyee_finit_par_refusee_acquise(
        self, client, db_path
    ):
        offer_id = 132
        _insert_offer(db_path, offer_id)
        for g in ["marquer_envoyee", "refuser"]:
            assert _geste(client, offer_id, g).status_code == 200, g
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["etapes_acquises"] == [
            "retenue",
            "prete_a_l_envoi",
            "candidature_envoyee",
            "refusee",
        ]
        assert "entretien" not in detail["etapes_acquises"]


# ---------------------------------------------------------------------------
# F5 / critère 14 — l'historique classe par jour de Bruxelles, pas par
# l'instant brut d'effet
# ---------------------------------------------------------------------------


class TestCritere14HistoriqueParJourPuisParInsertion:
    def test_retenir_puis_marquer_envoyee_le_meme_jour_affiche_envoyee_en_premier(
        self, client, db_path, monkeypatch
    ):
        offer_id = 140
        _insert_offer(db_path, offer_id, retenue=False)
        fixe = datetime(2026, 10, 20, 15, 0, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(suivi_etats, "maintenant", lambda: fixe)
        # Retenir garde l'heure réelle reçue (H3) : fixée ici à 15:00 UTC le
        # même jour calendaire que Marquer envoyée ci-dessous.
        assert (
            _geste(
                client, offer_id, "retenir", effet_at="2026-10-20T15:00:00+00:00"
            ).status_code
            == 200
        )
        # `marquer_envoyee` est normalisé à midi heure de Bruxelles (10:00 UTC)
        # du même jour calendaire — donc *avant* le Retenir de 15:00 en valeur
        # brute, mais enregistré après.
        assert (
            _geste(
                client,
                offer_id,
                "marquer_envoyee",
                effet_at="2026-10-20",
            ).status_code
            == 200
        )

        detail = client.get(f"/offers/{offer_id}").json()
        libelles = [h["libelle"] for h in detail["historique"]]
        assert libelles[0] == "Marquer envoyée"
        assert libelles[1] == "Retenir"


# ---------------------------------------------------------------------------
# Critère 15 — le libellé d'annulation date le geste au jour de Bruxelles
# ---------------------------------------------------------------------------


class TestCritere15LibelleAnnulerDateAuJourDeBruxelles:
    def test_effet_tard_le_soir_utc_date_au_jour_suivant_a_bruxelles(self):
        # 22:30 UTC le 20 octobre = 00:30 heure de Bruxelles le 21 octobre
        # (CEST, +2h) : le libellé doit dire 21, pas 20.
        ev = suivi_etats.EvenementHistorique(
            id=1,
            geste="marquer_envoyee",
            etat_depart="retenue",
            etat_arrivee="candidature_envoyee",
            effet_at="2026-10-20T22:30:00+00:00",
            enregistre_at="x",
            motif=None,
            annule_at=None,
        )
        assert (
            suivi_etats.libelle_annuler(ev) == "Annuler Marquer envoyée du 21 octobre"
        )


# ---------------------------------------------------------------------------
# Critère 16 — Suivi compte les offres que le filtre d'ingestion avait
# écartées mais qui ont ensuite été retenues
# ---------------------------------------------------------------------------


class TestCritere16SuiviCompteLesOffresFiltreesMaisRetenues:
    def test_offre_filtree_puis_retenue_apparait_dans_la_liste_suivi(
        self, client, db_path
    ):
        offer_id = 160
        _insert_offer(db_path, offer_id, filtered_out=True)
        detail = client.get(f"/offers/{offer_id}").json()
        assert detail["tri"] == "retenue"

        resp = client.get("/offers", params={"verdict": "retenu"})
        ids = {row["id"] for row in resp.json()}
        assert offer_id in ids

    def test_la_liste_et_le_compte_par_etape_comptent_les_memes_offres(
        self, client, db_path
    ):
        offer_id = 161
        _insert_offer(db_path, offer_id, filtered_out=True)

        resp = client.get("/offers", params={"verdict": "retenu"})
        ids = {row["id"] for row in resp.json()}
        assert offer_id in ids

        comptes = client.get("/offers/suivi/compte-etapes").json()
        assert comptes["retenue"] == 1


# ---------------------------------------------------------------------------
# Critère 12 — la date la plus tardive acceptée vient de l'API, par geste
# ---------------------------------------------------------------------------


class TestCritere12DateMaxParGeste:
    def test_gestes_dates_portent_la_date_du_jour_sauf_entretien(self, client, db_path):
        offer_id = 120
        _insert_offer(db_path, offer_id)
        detail = client.get(f"/offers/{offer_id}").json()
        gestes = {g["geste"]: g for g in detail["gestes"]}
        aujourd_hui = suivi_etats.aujourd_hui_bruxelles()
        # `.get(..., "MANQUANT")` : une clé absente (comme au code d'avant ce
        # ticket) doit faire échouer l'assertion, pas lever un KeyError (H8).
        assert gestes["marquer_envoyee"].get("date_max", "MANQUANT") == aujourd_hui
        assert gestes["abandonner"].get("date_max", "MANQUANT") == aujourd_hui
        assert gestes["entretien"].get("date_max", "MANQUANT") is None
        assert gestes["retenir"].get("date_max", "MANQUANT") is None


# ---------------------------------------------------------------------------
# Critères 10, 11 — le bloc d'envoi suit une décision rendue par l'API,
# jamais `envoyee_le` lu directement dans une condition
# ---------------------------------------------------------------------------


class TestCriteres10Et11DejaEnvoyeeDecideParLApi:
    def test_deja_envoyee_faux_avant_tout_envoi(self, client, db_path):
        offer_id = 100
        _insert_offer(db_path, offer_id)
        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        assert pieces.get("deja_envoyee", "MANQUANT") is False

    def test_deja_envoyee_vrai_apres_marquer_envoyee_et_faux_apres_annulation(
        self, client, db_path
    ):
        offer_id = 101
        _insert_offer(db_path, offer_id)
        assert _geste(client, offer_id, "marquer_envoyee").status_code == 200
        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        assert pieces.get("deja_envoyee", "MANQUANT") is True

        client.put(f"/offers/{offer_id}/envoyee", json={"envoyee": False})
        pieces = client.get(f"/offers/{offer_id}/pieces").json()
        assert pieces.get("deja_envoyee", "MANQUANT") is False

    def test_une_offre_filtree_non_retenue_reste_exclue_par_defaut(
        self, client, db_path
    ):
        offer_id = 162
        _insert_offer(db_path, offer_id, retenue=False, filtered_out=True)

        resp = client.get("/offers")
        ids = {row["id"] for row in resp.json()}
        assert offer_id not in ids
