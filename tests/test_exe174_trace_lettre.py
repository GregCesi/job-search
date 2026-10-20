"""Tests EXE-174 — chaque lettre générée par l'app est tracée : ses appels de
modèle restent attachés à sa version, se lisent dans l'historique et dans
MLflow.

Trois paliers. D'abord la boucle (`generer_lettre_depuis_donnees`), doublure
programmable comme test_exe147/test_exe160 — critère 1 (numéro de tour).
Ensuite le service et l'API, `generer_lettre_depuis_donnees` remplacée par une
doublure qui rend un `ResultatBoucle` explicite, base en tmp_path — critères
1 à 5. Enfin le module de suivi (`tracking/lettre_tracing.py`) seul — critères
6, 7, 9. Aucun test n'appelle un modèle réel, aucun test ne lit ni n'écrit sous
data/ ; l'isolation MLflow est globale (conftest.py) : aucun test n'écrit dans
le mlflow.db du dépôt.
"""

import asyncio
import json
import sqlite3

import mlflow
import pytest
import yaml
from mlflow.tracking import MlflowClient

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.banc import EXPERIMENT_NAME as BANC_EXPERIMENT
from orchestrator.job_search.lettre.boucle import (
    Appel,
    ConfigBoucle,
    Jugement,
    ReponseModele,
    ResultatBoucle,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage
from orchestrator.job_search.tracking.lettre_tracing import (
    EXPERIMENT_NAME,
    tracer_generation,
)
from orchestrator.job_search.tracking.mlflow_tracking import (
    EXPERIMENT_NAME as PIPELINE_EXPERIMENT,
)

# ═══════════════════════════════════════════════════════════════════════════
# Palier 1 — la boucle : numéro de tour (critère 1)
# ═══════════════════════════════════════════════════════════════════════════


class FakeModeles:
    """Doublure qui exige une réponse programmée pour chaque appel, y compris
    le vérificateur (reprise de test_exe160_verificateur_lettre.py) — nécessaire
    pour déclencher une correction à la main dans ces tests."""

    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        valeur = self.files[noeud].pop(0)
        if isinstance(valeur, BaseException):
            raise valeur
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=0.01)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


def _config(modele="sonnet") -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis=modele, modele_redaction=modele, modele_juge=modele
    )


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
            "lettre_de_reference": None,
        },
        "textes_types": [
            {
                "id": "generique",
                "sujet": "sujet générique",
                "conviction": "conviction générique",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte générique rédigé",
                "exemples": [],
            },
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
    chemin.write_text(
        "<html><body><p>Contenu CV de test</p></body></html>", encoding="utf-8"
    )
    return chemin


@pytest.fixture
def tournures_path(tmp_path):
    chemin = tmp_path / "tournures_interdites.txt"
    chemin.write_text("je veux\nn'hésitez pas\n", encoding="utf-8")
    return chemin


_TAMIS_GENERIQUE = json.dumps({"point_index": None, "texte_type_id": "generique"})
_VERIF_RIEN_A_SIGNALER = json.dumps(
    {"rien_a_signaler": True, "lieux": [], "affirmations": []}
)
_VERIF_LIEU = json.dumps(
    {
        "rien_a_signaler": False,
        "lieux": [{"lieu": "Lyon", "phrase": "phrase avec Lyon"}],
        "affirmations": [],
    }
)
_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
        "decision": "j'appelle",  # EXE-175, critère 1
    }
)


def _juge_remarques(texte="trop long") -> str:
    return json.dumps(
        {
            "rien_a_redire": False,
            "ressenti": "Ressenti mitigé.",
            "details": texte,
            "reussites": "Une accroche correcte.",
            "verdict": "À revoir.",
            "decision": "j'appelle",  # EXE-175, critère 1
        }
    )


def _lancer(repertoire_path, cv_path, tournures_path, config=None):
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        "Texte de l'offre",
        "Entreprise X",
        [],
        config or _config(),
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
    )


def test_critere1_tamis_porte_le_tour_1(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    tamis_appel = next(a for a in resultat.appels if a.noeud == "tamis")
    assert tamis_appel.tour == 1


def test_critere1_tours_suivent_les_lettres_au_plafond(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "verificateur",
        _VERIF_RIEN_A_SIGNALER,
        _VERIF_RIEN_A_SIGNALER,
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer(
        "juge",
        _juge_remarques("remarque 1"),
        _juge_remarques("remarque 2"),
        _juge_remarques("remarque 3"),
    )

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    tours = [(a.noeud, a.tour) for a in resultat.appels]
    assert tours == [
        ("tamis", 1),
        ("redaction", 1),
        ("verificateur", 1),
        ("juge", 1),
        ("redaction", 2),
        ("verificateur", 2),
        ("juge", 2),
        ("redaction", 3),
        ("verificateur", 3),
        ("juge", 3),
    ]


def test_critere1_correction_garde_le_meme_tour_que_la_redaction_initiale(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Je veux cette offre.", "Lettre corrigée.")
    modeles.programmer("verificateur", _VERIF_LIEU, _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    redactions = [a.tour for a in resultat.appels if a.noeud == "redaction"]
    assert redactions == [1, 1]  # la correction ne compte jamais un nouveau tour


# ═══════════════════════════════════════════════════════════════════════════
# Palier 2 — service et API (critères 1 à 5)
# ═══════════════════════════════════════════════════════════════════════════

FAIT_0 = {"position": "Point 0", "citation": "Citation 0", "url": "http://a"}
POINTS = [FAIT_0]

JUGEMENT_RIEN_A_REDIRE = Jugement(
    rien_a_redire=True,
    ressenti="Rien à redire.",
    details="Rien à redire.",
    reussites="Rien à redire.",
    verdict="Rien à redire.",
)
JUGEMENT_A_REDIRE = Jugement(
    rien_a_redire=False,
    ressenti="Ça sonne creux.",
    details="Détail.",
    reussites="Réussite.",
    verdict="À revoir.",
)


def _appel(noeud, tour, cout_usd=0.01, modele="sonnet") -> Appel:
    return Appel(
        noeud=noeud,
        modele=modele,
        duree_s=1.5,
        cout_usd=cout_usd,
        demande=f"demande {noeud} tour {tour}",
        reponse=f"réponse {noeud} tour {tour}",
        tour=tour,
    )


def _resultat_initial(appels=None) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=FAIT_0,
        texte_type_id="generique",
        lettres=[
            {
                "texte": "Lettre générée par le modèle.",
                "nb_mots": 5,
                "tournures_signalees": [],
                "jugement": JUGEMENT_RIEN_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
            }
        ],
        nb_tours=1,
        raison_fin="Le juge n'a rien à redire",
        appels=appels
        if appels is not None
        else [
            _appel("tamis", 1),
            _appel("redaction", 1),
            _appel("verificateur", 1),
            _appel("juge", 1, modele="opus"),
        ],
    )


MA_LETTRE = "Ma lettre écrite à la main, mot pour mot."


def _resultat_sans_reecriture() -> ResultatBoucle:
    """Juge n'a rien à redire sur ma lettre (critère 3) : un seul appel, le
    juge, aucune nouvelle version."""
    return ResultatBoucle(
        fait_retenu="generique",
        texte_type_id="generique",
        lettres=[
            {
                "texte": MA_LETTRE,
                "nb_mots": len(MA_LETTRE.split()),
                "tournures_signalees": [],
                "jugement": JUGEMENT_RIEN_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": 0,  # EXE-175 : ma lettre, jamais réécrite
            }
        ],
        nb_tours=0,
        raison_fin="Le juge n'a rien à redire",
        appels=[_appel("juge", 1, modele="opus")],
        jugement_ma_lettre=JUGEMENT_RIEN_A_REDIRE,
    )


def _resultat_avec_reecriture() -> ResultatBoucle:
    """Le juge a quelque chose à redire sur ma lettre, la rédaction la réécrit
    (critères 3, 5-10) : deux entrées, les appels couvrent le jugement initial
    plus la reprise."""
    return ResultatBoucle(
        fait_retenu="generique",
        texte_type_id="generique",
        lettres=[
            {
                "texte": MA_LETTRE,
                "nb_mots": len(MA_LETTRE.split()),
                "tournures_signalees": [],
                "jugement": JUGEMENT_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": 0,  # EXE-175 : ma lettre, jamais réécrite
            },
            {
                "texte": "Lettre réécrite par le modèle.",
                "nb_mots": 5,
                "tournures_signalees": [],
                "jugement": JUGEMENT_RIEN_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": 1,  # EXE-175 : la réécriture retenue, ce tour-ci
            },
        ],
        nb_tours=1,
        raison_fin="Le juge n'a rien à redire",
        appels=[
            _appel("juge", 1, modele="opus"),
            _appel("redaction", 1),
            _appel("verificateur", 1),
            _appel("juge", 1, modele="opus"),
        ],
        jugement_ma_lettre=JUGEMENT_A_REDIRE,
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


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'ACME', 'Texte.')",
            (offer_id, str(offer_id)),
        )
        if verdict == "retenu":
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at="2026-10-14"
            )
        elif verdict is not None:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.ECARTER, effet_at="2026-10-14"
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, points=POINTS, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, ?, 'Présentation', ?, 'ACME', '2026-10-14')",
            (offer_id, statut, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, texte_moi: str):
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    import unittest.mock as mock

    with mock.patch.object(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    ):
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        lettre_service.save_texte(conn, offer_id, texte_moi)
    finally:
        conn.close()


def test_critere1_version_garde_la_liste_complete_des_appels(db_path, monkeypatch):
    offer_id = 1
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    )

    asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

    versions = api_lettre.get_lettre_versions(offer_id)
    assert len(versions) == 1
    assert versions[0]["nb_appels"] == 4
    detail = api_lettre.get_lettre_version_appels(offer_id, versions[0]["id"])
    assert [a["noeud"] for a in detail] == [
        "tamis",
        "redaction",
        "verificateur",
        "juge",
    ]
    assert [a["tour"] for a in detail] == [1, 1, 1, 1]
    assert detail[1]["demande"] == "demande redaction tour 1"
    assert detail[1]["reponse"] == "réponse redaction tour 1"


def test_critere2_regeneration_ne_modifie_pas_les_appels_de_la_version_precedente(
    db_path, monkeypatch
):
    offer_id = 2
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    )
    asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
    versions_avant = api_lettre.get_lettre_versions(offer_id)
    detail_avant = api_lettre.get_lettre_version_appels(
        offer_id, versions_avant[0]["id"]
    )

    nouvel_appel = [_appel("tamis", 1), _appel("redaction", 1, modele="opus")]
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(appels=nouvel_appel),
    )
    lettre_service.mark_regenerating(sqlite3.connect(db_path), offer_id)
    asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "sonnet"))

    versions_apres = api_lettre.get_lettre_versions(offer_id)
    assert len(versions_apres) == 2
    # La version d'avant n'a pas bougé.
    detail_apres_premiere = api_lettre.get_lettre_version_appels(
        offer_id, versions_avant[0]["id"]
    )
    assert detail_apres_premiere == detail_avant
    # La nouvelle version porte les nouveaux appels, pas les anciens.
    detail_seconde = api_lettre.get_lettre_version_appels(
        offer_id, versions_apres[1]["id"]
    )
    assert len(detail_seconde) == 2


def test_critere3_juge_sur_ma_lettre_garde_sur_ma_version_quand_rien_a_redire(
    db_path, monkeypatch
):
    offer_id = 3
    _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_sans_reecriture(),
    )

    asyncio.run(
        lettre_service.run_lettre_regenerate_depuis_ma_lettre(offer_id, MA_LETTRE)
    )

    versions = api_lettre.get_lettre_versions(offer_id)
    ma_version = next(v for v in versions if v["origine"] == "moi")
    assert ma_version["nb_appels"] == 1
    detail = api_lettre.get_lettre_version_appels(offer_id, ma_version["id"])
    assert detail[0]["noeud"] == "juge"


def test_critere3_nouvelle_version_garde_les_appels_quand_reecriture(
    db_path, monkeypatch
):
    offer_id = 30
    _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_avec_reecriture(),
    )

    asyncio.run(
        lettre_service.run_lettre_regenerate_depuis_ma_lettre(offer_id, MA_LETTRE)
    )

    versions = api_lettre.get_lettre_versions(offer_id)
    ma_version = next(v for v in versions if v["origine"] == "moi")
    # Ma version n'a aucun appel : ses appels vont sur la nouvelle version.
    assert ma_version["nb_appels"] == 0
    derniere = versions[-1]
    assert derniere["origine"] == "modele"
    assert derniere["nb_appels"] == 4


def test_critere4_version_ecrite_a_la_main_n_a_aucun_appel(db_path):
    offer_id = 4
    _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)

    versions = api_lettre.get_lettre_versions(offer_id)
    ma_version = next(v for v in versions if v["origine"] == "moi")
    assert ma_version["nb_appels"] == 0
    assert ma_version["cout_total"] is None
    assert ma_version["trace_id"] is None
    detail = api_lettre.get_lettre_version_appels(offer_id, ma_version["id"])
    assert detail == []


def test_critere4_version_ancienne_sans_appels_se_lit_sans_erreur(db_path):
    offer_id = 40
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
    assert versions[0]["nb_appels"] == 0
    assert versions[0]["cout_total"] is None
    assert versions[0]["trace_id"] is None


def test_critere5_liste_des_versions_exclut_demande_et_reponse(db_path, monkeypatch):
    offer_id = 5
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    )
    asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

    versions = api_lettre.get_lettre_versions(offer_id)
    dump = json.dumps(versions)
    assert "demande tamis" not in dump
    assert "réponse tamis" not in dump
    assert versions[0]["nb_appels"] == 4
    # 4 appels à 0.01 chacun (fixture _appel).
    assert versions[0]["cout_total"] == pytest.approx(0.04)


def test_critere5_detail_version_rend_les_appels_complets(db_path, monkeypatch):
    offer_id = 50
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    )
    asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
    version_id = api_lettre.get_lettre_versions(offer_id)[0]["id"]

    detail = api_lettre.get_lettre_version_appels(offer_id, version_id)
    assert detail[0]["demande"] == "demande tamis tour 1"


def test_critere5_detail_version_inconnue_leve_404(db_path):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        api_lettre.get_lettre_version_appels(999, 999)
    assert exc_info.value.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Palier 3 — suivi MLflow (critères 6, 7, 9)
# ═══════════════════════════════════════════════════════════════════════════


def _appels_dicts():
    return [
        {
            "noeud": "tamis",
            "modele": "sonnet",
            "tour": 1,
            "duree_s": 0.5,
            "cout_usd": 0.01,
            "demande": "demande tamis",
            "reponse": "réponse tamis",
            "nb_jetons": None,
        },
        {
            "noeud": "redaction",
            "modele": "sonnet",
            "tour": 1,
            "duree_s": 1.2,
            "cout_usd": 0.02,
            "demande": "demande redaction",
            "reponse": "réponse redaction",
            "nb_jetons": None,
        },
    ]


def test_critere6_une_trace_avec_un_span_par_appel():
    trace_id = tracer_generation(
        _appels_dicts(),
        offer_id=42,
        mode="tamis",
        modele_redaction="sonnet",
        modele_juge="opus",
        raison_fin="Le plafond de tours est atteint",
    )
    assert trace_id is not None

    trace = mlflow.get_trace(trace_id)
    appel_spans = [s for s in trace.data.spans if s.span_type == "LLM"]
    assert len(appel_spans) == 2
    noms = {s.attributes["noeud"] for s in appel_spans}
    assert noms == {"tamis", "redaction"}
    redaction_span = next(
        s for s in appel_spans if s.attributes["noeud"] == "redaction"
    )
    assert redaction_span.attributes["modele"] == "sonnet"
    assert redaction_span.attributes["tour"] == 1
    assert redaction_span.attributes["duree_s"] == 1.2
    assert redaction_span.attributes["cout_usd"] == 0.02
    assert redaction_span.inputs == {"demande": "demande redaction"}
    assert redaction_span.outputs == {"reponse": "réponse redaction"}


def test_critere6_experience_distincte_du_banc_et_de_la_pipeline():
    assert EXPERIMENT_NAME not in (BANC_EXPERIMENT, PIPELINE_EXPERIMENT)

    tracer_generation(
        _appels_dicts(),
        offer_id=1,
        mode="tamis",
        modele_redaction="sonnet",
        modele_juge="opus",
        raison_fin="Le juge n'a rien à redire",
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(EXPERIMENT_NAME)
    assert experiment is not None
    assert client.get_experiment_by_name(BANC_EXPERIMENT) is None
    assert client.get_experiment_by_name(PIPELINE_EXPERIMENT) is None


def test_critere7_la_trace_porte_offre_mode_modeles_et_raison():
    trace_id = tracer_generation(
        _appels_dicts(),
        offer_id=77,
        mode="angle",
        modele_redaction="opus",
        modele_juge="opus",
        raison_fin="Le plafond de tours est atteint",
    )

    trace = mlflow.get_trace(trace_id)
    racine = next(s for s in trace.data.spans if s.parent_id is None)
    assert racine.attributes["offer_id"] == "77"
    assert racine.attributes["mode"] == "angle"
    assert racine.attributes["modele_redaction"] == "opus"
    assert racine.attributes["modele_juge"] == "opus"
    assert racine.attributes["raison_fin"] == "Le plafond de tours est atteint"


def test_critere9_mlflow_indisponible_rend_none_sans_lever(monkeypatch, capsys):
    import orchestrator.job_search.tracking.lettre_tracing as lettre_tracing

    def _boom(*a, **k):
        raise RuntimeError("stockage verrouillé")

    monkeypatch.setattr(lettre_tracing.MlflowClient, "start_trace", _boom)

    trace_id = tracer_generation(
        _appels_dicts(),
        offer_id=1,
        mode="tamis",
        modele_redaction="sonnet",
        modele_juge="opus",
        raison_fin="Le juge n'a rien à redire",
    )

    assert trace_id is None
    assert "suivi MLflow a échoué" in capsys.readouterr().out


def test_critere9_generation_va_au_bout_si_mlflow_indisponible(db_path, monkeypatch):
    import orchestrator.job_search.tracking.lettre_tracing as lettre_tracing

    offer_id = 9
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    monkeypatch.setattr(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _resultat_initial(),
    )
    monkeypatch.setattr(
        lettre_tracing.MlflowClient,
        "start_trace",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stockage verrouillé")),
    )

    asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))  # ne lève pas

    versions = api_lettre.get_lettre_versions(offer_id)
    assert versions[0]["nb_appels"] == 4  # les appels sont gardés malgré tout
    assert versions[0]["trace_id"] is None
