"""Tests EXE-162 — la lettre de l'app sort de la boucle (tamis/rédaction/
vérificateur/juge), montre le fait retenu et le verdict du juge, et un bouton
écarte une accroche pour en tenter une autre.

Couvre les critères 1 à 17. La boucle (`generer_lettre_depuis_donnees`) est
remplacée par une doublure qui rend un résultat de boucle déjà construit
(critère 24) — aucun test n'appelle un modèle réel, aucun test ne lit ni
n'écrit sous data/ : la DB est un fichier tmp_path.
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
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    Appel,
    Jugement,
    ResultatBoucle,
)
from orchestrator.job_search.lettre.redaction import (
    RAISON_FICHE_NON_TERMINEE,
    RAISON_RIEN_A_ECARTER,
    RAISON_TEXTE_MANQUANT,
)
from orchestrator.job_search.storage.db import init_db

FAIT_0 = {
    "position": "Point 0",
    "citation": "Citation 0",
    "url": "http://a",
    "tas": None,
}
FAIT_1 = {
    "position": "Point 1",
    "citation": "Citation 1",
    "url": "http://b",
    "tas": None,
}
POINTS = [FAIT_0, FAIT_1]


def _jugement(rien_a_redire=True) -> Jugement:
    return Jugement(
        rien_a_redire=rien_a_redire,
        ressenti="Lettre convaincante.",
        details="Le fait choisi est précis.",
        reussites="Le ton est direct.",
        verdict="Envoyable.",
    )


def _releve_vide() -> dict:
    return {"tournures": [], "lieux": [], "affirmations": []}


def _lettre_entry(texte="Voici ma lettre.", jugement=None, releve=None) -> dict:
    return {
        "texte": texte,
        "nb_mots": len(texte.split()),
        "tournures_signalees": [],
        "jugement": jugement if jugement is not None else _jugement(),
        "releve_redaction": releve if releve is not None else _releve_vide(),
        "releve_correction": None,
    }


def _resultat_ok(
    texte="Voici ma lettre.",
    fait_retenu=None,
    texte_type_id="tt1",
    nb_tours=1,
    raison_fin=RAISON_RIEN_A_REDIRE,
    jugement=None,
    releve=None,
    appels=None,
) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=fait_retenu if fait_retenu is not None else GENERIQUE_ID,
        texte_type_id=texte_type_id,
        lettres=[_lettre_entry(texte, jugement, releve)],
        nb_tours=nb_tours,
        raison_fin=raison_fin,
        appels=appels if appels is not None else [],
    )


def _resultat_echec(
    raison="L'appel au modèle du nœud « tamis » a échoué : panne",
) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
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
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-09')",
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
            "employeur_nom, created_at) VALUES (?, ?, 'Présentation', ?, 'ACME', '2026-10-09')",
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


class TestCritere1LettreFinaleDeLaBoucle:
    def test_lettre_enregistree_est_la_lettre_finale_de_la_boucle(
        self, db_path, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok("Voici la lettre finale, courte."),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert row["texte"] == "Voici la lettre finale, courte."
        assert row["nb_mots"] == 5
        assert json.loads(row["tournures_signalees_json"]) == []


class TestCritere2BoucleEnThread:
    def test_la_boucle_ne_bloque_pas_la_boucle_d_evenements(self, db_path, monkeypatch):
        import time

        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)

        def _lent(*a, **k):
            time.sleep(0.2)
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _lent)

        compteur = {"n": 0}

        async def _compter_pendant():
            while compteur["n"] < 5:
                compteur["n"] += 1
                await asyncio.sleep(0.02)

        async def _scenario():
            await asyncio.gather(
                lettre_service.run_lettre(offer_id), _compter_pendant()
            )

        asyncio.run(_scenario())

        # Le compteur a progressé pendant les 0.2s du faux appel bloquant :
        # preuve que l'event loop n'a pas été gelé par la boucle.
        assert compteur["n"] == 5


class TestCritere3RefusReduitsATroisRaisons:
    def test_blocage_sans_point_choisi_part_quand_meme(self, db_path, monkeypatch):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )

        response = Response()
        asyncio.run(api_lettre.create_lettre(offer_id, response))
        assert response.status_code == 202

    def test_refuse_fiche_non_terminee(self, db_path):
        offer_id = 30
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == RAISON_FICHE_NON_TERMINEE

    def test_refuse_texte_manquant(self, db_path):
        offer_id = 31
        _insert_offer(db_path, offer_id, description_raw="   ")
        _insert_fiche(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == RAISON_TEXTE_MANQUANT

    def test_refuse_offre_non_retenue(self, db_path):
        offer_id = 32
        _insert_offer(db_path, offer_id, verdict="candidaté")
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.create_lettre(offer_id, Response()))
        assert exc_info.value.status_code == 409


class TestCritere4PointsMoinsEcartesSansChoixNiDesignation:
    def test_boucle_recoit_points_moins_ecartes(self, db_path, monkeypatch):
        offer_id = 4
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0, FAIT_1])
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, faits_ecartes_json, created_at) "
            "VALUES (?, 'aucune', ?, '2026-10-09')",
            (offer_id, json.dumps([FAIT_0])),
        )
        conn.commit()
        conn.close()

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config):
            captured["points_fiche"] = points_fiche
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id))

        assert captured["points_fiche"] == [FAIT_1]


class TestCritere5FaitsEtVerdictEnregistres:
    def test_lettre_porte_fait_tours_raison_jugement_releve(self, db_path, monkeypatch):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(
                fait_retenu=FAIT_0, nb_tours=2, jugement=_jugement()
            ),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        lettre = api_lettre.get_lettre(offer_id)

        assert lettre["fait_retenu"] == FAIT_0
        assert lettre["nb_tours"] == 2
        assert lettre["raison_fin"] == RAISON_RIEN_A_REDIRE
        assert lettre["jugement"]["rien_a_redire"] is True
        assert lettre["jugement"]["ressenti"]
        assert lettre["jugement"]["details"]
        assert lettre["jugement"]["reussites"]
        assert lettre["jugement"]["verdict"]
        assert lettre["releve"] == _releve_vide()

    def test_lettre_generique_ne_porte_aucun_fait_invente(self, db_path, monkeypatch):
        offer_id = 50
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=None),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        lettre = api_lettre.get_lettre(offer_id)

        assert lettre["fait_retenu"] is None


class TestCritere6AppelsEnregistresAvecLaLettre:
    def test_demandes_et_reponses_de_chaque_appel_sont_la(self, db_path, monkeypatch):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        appels = [
            Appel(
                noeud="tamis",
                modele="sonnet",
                duree_s=1.0,
                cout_usd=0.01,
                demande="demande du tamis",
                reponse="réponse du tamis",
            )
        ]
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(appels=appels),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        row = _lettre_row(db_path, offer_id)
        stored = json.loads(row["appels_json"])

        assert stored == [
            {
                "noeud": "tamis",
                "modele": "sonnet",
                "duree_s": 1.0,
                "cout_usd": 0.01,
                "demande": "demande du tamis",
                "reponse": "réponse du tamis",
                "nb_jetons": None,
            }
        ]


class TestCritere7VersionPorteLeFaitRetenu:
    def test_chaque_generation_ajoute_une_version_avec_le_fait(
        self, db_path, monkeypatch
    ):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=FAIT_0),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        versions = api_lettre.get_lettre_versions(offer_id)

        assert len(versions) == 1
        assert versions[0]["origine"] == "modele"
        assert versions[0]["fait_retenu"] == FAIT_0


class TestCritere8LongueurA250Mots:
    def test_251_mots_signale_le_depassement_lettre_et_version(
        self, db_path, monkeypatch
    ):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        texte_251 = " ".join(["mot"] * 251)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(texte_251),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        lettre = api_lettre.get_lettre(offer_id)
        versions = api_lettre.get_lettre_versions(offer_id)

        assert lettre["nb_mots"] == 251
        assert lettre["depasse_longueur"] is True
        assert versions[0]["depasse_longueur"] is True

    def test_reprise_a_la_main_suit_la_meme_borne(self, db_path, monkeypatch):
        offer_id = 80
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        texte_251 = " ".join(["mot"] * 251)
        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte=texte_251)
        )
        assert result["depasse_longueur"] is True


class TestCritere9EchecSansTexteEtRegenerationGardeAvant:
    def test_echec_de_la_boucle_laisse_la_lettre_en_erreur_sans_texte(
        self, db_path, monkeypatch
    ):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        raison = "L'appel au modèle du nœud « tamis » a échoué : panne"
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_echec(raison),
        )

        asyncio.run(lettre_service.run_lettre(offer_id))
        row = _lettre_row(db_path, offer_id)

        assert row["statut"] == "error"
        assert row["texte"] is None
        assert raison in row["error_message"]

    def test_regeneration_echouee_garde_la_version_d_avant(self, db_path, monkeypatch):
        offer_id = 90
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok("Lettre stable."),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))
        avant = _lettre_row(db_path, offer_id)

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_echec(),
        )
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        apres = _lettre_row(db_path, offer_id)
        assert apres["texte"] == avant["texte"] == "Lettre stable."
        assert apres["regeneration_error"]


class TestCritere11PreferencesTonNonLues:
    def test_lettre_service_ne_porte_plus_les_preferences_de_ton(self):
        assert not hasattr(lettre_service, "LETTRE_PREFERENCES_PATH")

    def test_generation_reussit_sans_fichier_de_preferences(self, db_path, monkeypatch):
        offer_id = 110
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))
        assert _lettre_row(db_path, offer_id)["statut"] == "done"


class TestCritere12ReprisePdfMailFonctionnentSurLaBoucle:
    def test_reprise_a_la_main_fonctionne_sur_la_lettre_de_la_boucle(
        self, db_path, monkeypatch
    ):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        result = api_lettre.put_lettre_texte(
            offer_id, api_lettre.LettreTexteIn(texte="Texte repris à la main.")
        )
        assert result["texte"] == "Texte repris à la main."


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


class TestCritere13EcarterRegenereAussitot:
    def test_ecarter_le_fait_retenu_lance_une_regeneration(self, db_path, monkeypatch):
        offer_id = 13
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0, FAIT_1])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=FAIT_0),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(
                fait_retenu=FAIT_1, texte="Nouvelle accroche."
            ),
        )

        async def _scenario():
            response = Response()
            result = await api_lettre.ecarter_fait(offer_id, response)
            assert response.status_code == 202
            assert result == {"regeneration_en_cours": True}
            await _drain()

        asyncio.run(_scenario())

        row = _lettre_row(db_path, offer_id)
        ecartes = json.loads(row["faits_ecartes_json"])
        assert ecartes == [FAIT_0]
        assert row["regeneration_en_cours"] == 0
        assert row["texte"] == "Nouvelle accroche."
        assert json.loads(row["fait_retenu_json"]) == FAIT_1


class TestCritere14BoucleSuivanteSansFaitsEcartes:
    def test_regeneration_ne_recoit_aucun_fait_ecarte(self, db_path, monkeypatch):
        offer_id = 14
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0, FAIT_1])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, faits_ecartes_json, created_at) "
            "VALUES (?, 'done', ?, '2026-10-09')",
            (offer_id, json.dumps([FAIT_0])),
        )
        conn.commit()
        conn.close()

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config):
            captured["points_fiche"] = points_fiche
            return _resultat_ok(fait_retenu=FAIT_1)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        assert captured["points_fiche"] == [FAIT_1]

    def test_tous_les_points_ecartes_donne_une_lettre_generique(
        self, db_path, monkeypatch
    ):
        offer_id = 140
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, faits_ecartes_json, created_at) "
            "VALUES (?, 'done', ?, '2026-10-09')",
            (offer_id, json.dumps([FAIT_0])),
        )
        conn.commit()
        conn.close()

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config):
            captured["points_fiche"] = points_fiche
            return _resultat_ok(fait_retenu=None)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        assert captured["points_fiche"] == []
        assert api_lettre.get_lettre(offer_id)["fait_retenu"] is None


class TestCritere15RemettreSansRegenerer:
    def test_remettre_un_fait_ecarte_le_retire_sans_regenerer(
        self, db_path, monkeypatch
    ):
        offer_id = 15
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, faits_ecartes_json, created_at) "
            "VALUES (?, 'done', ?, '2026-10-09')",
            (offer_id, json.dumps([FAIT_0])),
        )
        conn.commit()
        conn.close()

        def _jamais(*a, **k):
            raise AssertionError(
                "la boucle a été relancée alors que ce n'était pas demandé"
            )

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _jamais)

        result = api_lettre.remettre_fait(
            offer_id, api_lettre.FaitEcarteIn(citation="Citation 0", url="http://a")
        )
        assert result["faits_ecartes"] == []


class TestCritere16FaitsEcartesPersistentALaFiche:
    def test_fait_toujours_ecarte_apres_une_nouvelle_fiche_meme_citation_lien(
        self, db_path, monkeypatch
    ):
        offer_id = 16
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[FAIT_0, FAIT_1])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, faits_ecartes_json, created_at) "
            "VALUES (?, 'done', ?, '2026-10-09')",
            (offer_id, json.dumps([FAIT_0])),
        )
        conn.commit()
        conn.close()

        # Nouvelle fiche : même citation/lien pour le point 0, un nouveau point en plus.
        nouveau_point = {
            "position": "Point 0 bis",
            "citation": "Citation 0",
            "url": "http://a",
            "tas": None,
        }
        autre = {
            "position": "Point 2",
            "citation": "Citation 2",
            "url": "http://c",
            "tas": None,
        }
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE fiches_entreprise SET points_json = ? WHERE offer_id = ?",
            (json.dumps([nouveau_point, FAIT_1, autre]), offer_id),
        )
        conn.commit()
        conn.close()

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config):
            captured["points_fiche"] = points_fiche
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id))

        assert captured["points_fiche"] == [FAIT_1, autre]


class TestCritere17EcarterSurGeneriqueRefuse:
    def test_ecarter_sur_lettre_generique_est_refuse(self, db_path, monkeypatch):
        offer_id = 17
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, points=[])
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(fait_retenu=None),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.ecarter_fait(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == RAISON_RIEN_A_ECARTER

    def test_ecarter_sans_lettre_est_refuse(self, db_path):
        offer_id = 170
        _insert_offer(db_path, offer_id)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.ecarter_fait(offer_id, Response()))
        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == RAISON_RIEN_A_ECARTER


def test_raison_plafond_est_aussi_une_fin_reussie(db_path, monkeypatch):
    """`raison_fin` peut aussi être le plafond de tours atteint, pas seulement
    « rien à redire » (ResultatBoucle.raison_fin) — toujours une lettre finale
    exploitable, jamais une erreur."""
    offer_id = 18
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_ok(
            raison_fin=RAISON_PLAFOND, jugement=_jugement(False)
        ),
    )

    asyncio.run(lettre_service.run_lettre(offer_id))
    lettre = api_lettre.get_lettre(offer_id)

    assert lettre["statut"] == "done"
    assert lettre["raison_fin"] == RAISON_PLAFOND
