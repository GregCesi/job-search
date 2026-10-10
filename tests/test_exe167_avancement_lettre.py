"""Tests EXE-167 — je vois la lettre se générer ou se régénérer : l'avancement
lit « en cours » pendant une régénération (critère 1), la boucle signale son
étape (critères 2, 3, 6), et l'API l'expose pendant la génération seulement
(critères 2, 4).

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par
une doublure programmable (comme EXE-147/160), et `generer_lettre_depuis_donnees`
par une doublure synchrone pour les tests d'API/service (comme EXE-66/127).
Aucun test ne lit ni n'écrit sous data/ : base, répertoire, CV de référence et
tournures interdites sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3
import threading

import pytest
import yaml
from fastapi import Response

import api.avancement as api_avancement
import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.avancement as avancement
import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    ConfigBoucle,
    Jugement,
    ReponseModele,
    ResultatBoucle,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (reprise d'EXE-147/160) ---------------------


class FakeModeles:
    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        if noeud == "verificateur" and not self.files["verificateur"]:
            return ReponseModele(
                texte=json.dumps(
                    {"rien_a_signaler": True, "lieux": [], "affirmations": []}
                ),
                duree_s=0.01,
                cout_usd=0.01,
            )
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


def _config() -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis="sonnet", modele_redaction="sonnet", modele_juge="sonnet"
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


def _repertoire_donnees() -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "quatre_temps": ["accroche", "preuve", "offre", "cta"],
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "sujets_interdits": [],
        "conditions_generales": ["lettre en français"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": "lettre envoyée à Entreprise X",
        },
        "textes_types": [
            _texte_type("prototyper"),
            _texte_type("generique", texte="texte générique rédigé"),
        ],
        "juge": {"consigne": "Consigne du juge.", "contexte": "Contexte du juge."},
        "redaction": {
            "consigne_reprise": "Consigne de reprise.",
            "consigne_verification": "Consigne de correction.",
        },
        "verificateur": {"consigne": "Consigne du vérificateur."},
    }


@pytest.fixture
def repertoire_path(tmp_path):
    chemin = tmp_path / "repertoire.yaml"
    chemin.write_text(
        yaml.safe_dump(_repertoire_donnees(), allow_unicode=True), encoding="utf-8"
    )
    return chemin


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


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
    }
)


def _juge_json(rien_a_redire: bool) -> str:
    return json.dumps(
        {
            "rien_a_redire": rien_a_redire,
            "ressenti": "Ressenti.",
            "details": "Détails.",
            "reussites": "Réussites.",
            "verdict": "Verdict.",
        }
    )


def _verif_json(rien_a_signaler=False, lieux=None) -> str:
    return json.dumps(
        {"rien_a_signaler": rien_a_signaler, "lieux": lieux or [], "affirmations": []}
    )


def _lancer(repertoire_path, cv_path, tournures_path, on_etape=None):
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        "Texte de l'offre",
        "Entreprise X",
        [{"position": "Point 0", "citation": "Citation 0", "url": "https://x.test/0"}],
        _config(),
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        on_etape=on_etape,
    )


# === Critères 2, 3, 6 : signal d'étape de la boucle =============================


class TestSignalEtapeBoucle:
    def test_critere6_aucun_signal_sans_ecouteur(
        self, repertoire_path, cv_path, tournures_path, modeles
    ):
        """Red avant la fiche : `on_etape` n'existait pas, l'appel levait un
        TypeError. Sans écouteur (défaut), la boucle tourne normalement."""
        modeles.programmer("tamis", _TAMIS_POINT_0)
        modeles.programmer("redaction", "Lettre.")
        modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

        resultat = _lancer(repertoire_path, cv_path, tournures_path)

        assert resultat.raison_fin == RAISON_RIEN_A_REDIRE

    def test_critere2_sequence_des_etapes_avec_correction(
        self, repertoire_path, cv_path, tournures_path, modeles
    ):
        """Un tour avec correction : le vérificateur tourne deux fois, la
        correction a son propre nom d'étape, jamais « redaction »."""
        modeles.programmer("tamis", _TAMIS_POINT_0)
        modeles.programmer("redaction", "Je veux cette offre.", "Lettre corrigée.")
        modeles.programmer(
            "verificateur",
            _verif_json(lieux=[{"lieu": "Lyon", "phrase": "x"}]),
            _verif_json(rien_a_signaler=True),
        )
        modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)
        signaux = []

        _lancer(repertoire_path, cv_path, tournures_path, on_etape=signaux.append)

        etapes = [(s["etape"], s["tour"], s["fin"]) for s in signaux]
        assert etapes == [
            ("choix_du_fait", 1, False),
            ("redaction", 1, False),
            ("verification", 1, False),
            ("correction", 1, False),
            ("verification", 1, False),
            ("lecture_du_juge", 1, True),
        ]
        assert all(s["max_tours"] == boucle.MAX_TOURS for s in signaux)

    def test_critere3_fin_anticipee_signalee_sur_le_dernier_juge(
        self, repertoire_path, cv_path, tournures_path, modeles
    ):
        modeles.programmer("tamis", _TAMIS_POINT_0)
        modeles.programmer("redaction", "Lettre.")
        modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)
        signaux = []

        _lancer(repertoire_path, cv_path, tournures_path, on_etape=signaux.append)

        assert signaux[-1]["etape"] == "lecture_du_juge"
        assert signaux[-1]["fin"] is True

    def test_critere3_plafond_trois_tours_fin_sur_le_dernier_juge_seulement(
        self, repertoire_path, cv_path, tournures_path, modeles
    ):
        modeles.programmer("tamis", _TAMIS_POINT_0)
        modeles.programmer("redaction", "L1.", "L2.", "L3.")
        modeles.programmer(
            "verificateur",
            _verif_json(rien_a_signaler=True),
            _verif_json(rien_a_signaler=True),
            _verif_json(rien_a_signaler=True),
        )
        modeles.programmer(
            "juge", _juge_json(False), _juge_json(False), _juge_json(False)
        )
        signaux = []

        resultat = _lancer(
            repertoire_path, cv_path, tournures_path, on_etape=signaux.append
        )

        assert resultat.raison_fin == RAISON_PLAFOND
        fins = [s["fin"] for s in signaux]
        assert fins == [False] * (len(signaux) - 1) + [True]
        juges = [s for s in signaux if s["etape"] == "lecture_du_juge"]
        assert [j["tour"] for j in juges] == [1, 2, 3]

    def test_etape_jamais_signalee_pour_un_noeud_en_echec(
        self, repertoire_path, cv_path, tournures_path, modeles
    ):
        """Pas d'étape inventée : un nœud qui échoue ne signale rien — le
        dernier signal reste celui du nœud précédent, réussi."""
        modeles.programmer("tamis", _TAMIS_POINT_0)
        modeles.programmer("redaction", "Lettre.")
        modeles.programmer("juge", boucle.AppelModeleError("panne"))
        signaux = []

        resultat = _lancer(
            repertoire_path, cv_path, tournures_path, on_etape=signaux.append
        )

        assert resultat.erreur_type == "appel_echoue"
        assert [s["etape"] for s in signaux] == [
            "choix_du_fait",
            "redaction",
            "verification",
        ]


# === Critère 3 : calcul du pourcentage (ProgressionLettre) ======================


class TestProgressionLettre:
    def test_critere3_pourcentage_avance_par_dixieme_jamais_au_dela_de_99(self):
        tracker = avancement.ProgressionLettre()
        tracker.signaler(
            {"etape": "choix_du_fait", "tour": 1, "max_tours": 3, "fin": False}
        )
        assert tracker.pourcentage == 10
        tracker.signaler(
            {"etape": "redaction", "tour": 1, "max_tours": 3, "fin": False}
        )
        assert tracker.pourcentage == 20
        tracker.signaler(
            {"etape": "verification", "tour": 1, "max_tours": 3, "fin": False}
        )
        assert tracker.pourcentage == 30

    def test_critere3_correction_ni_seconde_verification_ne_font_avancer(self):
        tracker = avancement.ProgressionLettre()
        for etape in ("choix_du_fait", "redaction", "verification"):
            tracker.signaler({"etape": etape, "tour": 1, "max_tours": 3, "fin": False})
        assert tracker.pourcentage == 30
        tracker.signaler(
            {"etape": "correction", "tour": 1, "max_tours": 3, "fin": False}
        )
        assert tracker.pourcentage == 30
        # Second passage du vérificateur après correction, même tour : déjà compté.
        tracker.signaler(
            {"etape": "verification", "tour": 1, "max_tours": 3, "fin": False}
        )
        assert tracker.pourcentage == 30

    def test_critere3_fin_anticipee_passe_a_100(self):
        tracker = avancement.ProgressionLettre()
        tracker.signaler(
            {"etape": "choix_du_fait", "tour": 1, "max_tours": 3, "fin": False}
        )
        tracker.signaler(
            {"etape": "redaction", "tour": 1, "max_tours": 3, "fin": False}
        )
        tracker.signaler(
            {"etape": "verification", "tour": 1, "max_tours": 3, "fin": False}
        )
        tracker.signaler(
            {"etape": "lecture_du_juge", "tour": 1, "max_tours": 3, "fin": True}
        )
        assert tracker.pourcentage == 100
        assert tracker.as_dict() == {
            "etape": "lecture_du_juge",
            "tour": 1,
            "max_tours": 3,
            "pourcentage": 100,
        }


# === Critère 1 : avancement pendant/après une régénération =====================


class TestLettreAvancementRegeneration:
    def _row(self, **overrides) -> dict:
        base = {
            "statut": "done",
            "error_message": None,
            "regeneration_en_cours": 0,
            "regeneration_error": None,
        }
        base.update(overrides)
        return base

    def test_regeneration_en_cours_et_en_fonctionnement_lit_en_cours(self):
        row = self._row(regeneration_en_cours=1)
        assert avancement.lettre_avancement(row, True, None) == {
            "etat": avancement.EN_COURS,
            "raison": None,
        }

    def test_regeneration_reussie_revient_a_terminee_sans_raison(self):
        row = self._row(regeneration_en_cours=0, regeneration_error=None)
        assert avancement.lettre_avancement(row, False, None) == {
            "etat": avancement.TERMINEE,
            "raison": None,
        }

    def test_regeneration_echouee_revient_a_terminee_avec_la_raison(self):
        row = self._row(regeneration_en_cours=0, regeneration_error="panne du modèle")
        assert avancement.lettre_avancement(row, False, None) == {
            "etat": avancement.TERMINEE,
            "raison": "panne du modèle",
        }

    def test_regeneration_orpheline_api_redemarree_revient_a_terminee(self):
        row = self._row(regeneration_en_cours=1)
        assert avancement.lettre_avancement(row, False, None) == {
            "etat": avancement.TERMINEE,
            "raison": avancement.RAISON_ORPHELINE,
        }


# === Critères 1, 2, 4 : intégration service + API ==============================


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
    monkeypatch.setattr(lettre_service, "LETTRE_TOURNURES_PATH", tournures)
    return tournures


def _insert_offer(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, description_raw) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', '2026-10-10')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        points = [{"position": "Point 0", "citation": "Citation 0", "url": None}]
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, 'done', 'Présentation', ?, '2026-10-10')",
            (offer_id, json.dumps(points)),
        )
        conn.commit()
    finally:
        conn.close()


def _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id):
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_ok("Lettre initiale."),
    )
    asyncio.run(lettre_service.run_lettre(offer_id))


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


class TestServiceTransmetOnEtape:
    def test_run_lettre_transmet_on_etape_a_la_boucle(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 1
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        recus = {}

        def _double(*a, **k):
            recus["on_etape"] = k.get("on_etape")
            return _resultat_ok("Lettre.")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        marqueur = object()

        asyncio.run(lettre_service.run_lettre(offer_id, on_etape=marqueur))

        assert recus["on_etape"] is marqueur

    def test_run_lettre_regenerate_transmet_on_etape_a_la_boucle(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 2
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)
        recus = {}

        def _double(*a, **k):
            recus["on_etape"] = k.get("on_etape")
            return _resultat_ok("Nouvelle lettre.")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        marqueur = object()

        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, on_etape=marqueur))

        assert recus["on_etape"] is marqueur


class TestApiEtapeVisiblePendantRegeneration:
    def test_etape_et_avancement_en_cours_pendant_puis_disparaissent(
        self, db_path, lettre_fixture_paths, monkeypatch
    ):
        offer_id = 3
        _generer_lettre_prete(db_path, lettre_fixture_paths, monkeypatch, offer_id)
        gate = threading.Event()

        def _double(*a, **k):
            on_etape = k.get("on_etape")
            on_etape(
                {"etape": "choix_du_fait", "tour": 1, "max_tours": 3, "fin": False}
            )
            gate.wait(timeout=5)
            return _resultat_ok("Nouvelle lettre régénérée.")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)

        async def _scenario():
            response = Response()
            await api_lettre.regenerer_lettre(offer_id, response)
            assert response.status_code == 202

            lettre = None
            for _ in range(200):
                await asyncio.sleep(0.01)
                lettre = api_lettre.get_lettre(offer_id)
                if lettre["etape"] is not None:
                    break
            assert lettre["etape"] == {
                "etape": "choix_du_fait",
                "tour": 1,
                "max_tours": 3,
                "pourcentage": 10,
            }

            # Critère 1 : l'avancement se lit « en cours » comme une première
            # génération, malgré une pièce déjà `done` en base.
            av = api_avancement.get_avancement(offer_id)
            assert av["lettre"]["etat"] == "en_cours"

            gate.set()
            await _drain()

            # Critère 4 : plus d'étape une fois la lettre enregistrée.
            lettre_finale = api_lettre.get_lettre(offer_id)
            assert lettre_finale["etape"] is None
            assert lettre_finale["texte"] == "Nouvelle lettre régénérée."

            av_fin = api_avancement.get_avancement(offer_id)
            assert av_fin["lettre"] == {"etat": "terminee", "raison": None}

        asyncio.run(_scenario())
