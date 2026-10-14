"""Tests EXE-175 — la décision du juge, la lettre la mieux jugée (plutôt que la
dernière), et l'interprète du banc qui réécrit depuis le ressenti du juge.

Trois paliers. D'abord la boucle (`generer_lettre_boucle`/
`generer_lettre_depuis_donnees`), `boucle.appeler_modele` remplacé par une
doublure programmable (reprise de test_exe147_boucle_lettre.py, étendue au
nœud « interprete »). Ensuite le répertoire (`repertoire.py`) et le banc
(`banc.py`), sur le même principe. Enfin le service (`service.py`), avec
`generer_lettre_depuis_donnees` elle-même remplacée par une doublure qui rend
un `ResultatBoucle` explicite (reprise de test_exe162_boucle_app.py). Aucun
test n'appelle un modèle réel, aucun test ne lit ni n'écrit sous data/.
L'isolation MLflow est globale (conftest.py) : aucun test n'écrit dans le
mlflow.db du dépôt, y compris ceux du palier banc qui laissent `lancer_banc`
écrire un run réel dans la base isolée.
"""

import asyncio
import json
import sqlite3

import pytest
import yaml

import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    ConfigBoucle,
    Jugement,
    ReponseModele,
    ResultatBoucle,
    generer_lettre_boucle,
    raison_reponse_illisible,
)
from orchestrator.job_search.lettre.repertoire import (
    RepertoireError,
    charger_repertoire,
    valider_interprete,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\n"

# ═══════════════════════════════════════════════════════════════════════════
# Palier 1 — la boucle, modèles doublés (critères 1-16)
# ═══════════════════════════════════════════════════════════════════════════


class FakeModeles:
    """Même doublure que test_exe147_boucle_lettre.py, étendue au nœud
    « interprete » (EXE-175, critère 16)."""

    def __init__(self):
        self.files = {
            "tamis": [],
            "redaction": [],
            "juge": [],
            "verificateur": [],
            "interprete": [],
        }
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


def _config(modele="sonnet", interprete=None) -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis=modele,
        modele_redaction=modele,
        modele_juge=modele,
        modele_interprete=interprete,
    )


def _repertoire_donnees(*, avec_interprete=True) -> dict:
    donnees = {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [{"texte": "passionné", "motif": "trop vu"}],
        },
        "ce_qui_est_vrai_sur_moi": ["je code depuis 10 ans"],
        "forme": {"blocs": ["accroche", "preuve", "offre", "cta"]},
        "sujets_interdits": [],
        "textes_types": [
            {
                "id": "prototyper",
                "sujet": "sujet de prototyper",
                "conviction": "conviction de prototyper",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte rédigé de prototyper",
                "exemples": [],
            },
            {
                "id": "generique",
                "sujet": "sujet générique",
                "conviction": "conviction générique",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte générique rédigé",
                "exemples": [],
            },
        ],
        "juge": {
            "consigne": "Consigne du juge.",
            "contexte": "Contexte du juge.",
        },
        "redaction": {
            "consigne_reprise": "Consigne de reprise.",
            "consigne_verification": "Consigne de correction.",
        },
        "verificateur": {"consigne": "Consigne du vérificateur."},
    }
    if avec_interprete:
        donnees["interprete"] = {"consigne": "Consigne de l'interprète."}
    return donnees


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(avec_interprete=True):
        chemin = tmp_path / "repertoire.yaml"
        chemin.write_text(
            yaml.safe_dump(
                _repertoire_donnees(avec_interprete=avec_interprete),
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        return chemin

    return _ecrire


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


@pytest.fixture
def db_path(tmp_path):
    chemin = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(chemin)
    init_db(conn)
    conn.close()
    return chemin


def _points_fiche() -> list[dict]:
    return [
        {"position": "Point 0", "citation": "Citation 0", "url": "https://ex.test/0"}
    ]


def _poser_offre_et_fiche(db_path, offer_id=1):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'Entreprise X', "
            "'Texte de l''offre')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, employeur_nom, created_at) VALUES (?, 'done', 'P', ?, "
            "'Entreprise X', '2026-10-14')",
            (offer_id, json.dumps(_points_fiche())),
        )
        conn.commit()
    finally:
        conn.close()


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _lancer(db_path, repertoire_path, cv_path, tournures_path, config=None, offer_id=1):
    conn = _conn(db_path)
    try:
        return generer_lettre_boucle(
            conn,
            offer_id,
            config or _config(),
            repertoire_path=repertoire_path(),
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
        )
    finally:
        conn.close()


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})


def _juge(decision="j'appelle", rien_a_redire=False, details="remarques") -> str:
    return json.dumps(
        {
            "rien_a_redire": rien_a_redire,
            "ressenti": "Ressenti.",
            "details": details,
            "reussites": "Réussites.",
            "verdict": "Verdict.",
            "decision": decision,
        }
    )


_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
        "decision": "j'appelle",
    }
)


# --- critères 1-3 : la décision du juge ----------------------------------------


def test_critere1_le_jugement_porte_la_decision_du_juge(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _juge(decision="j'hésite", rien_a_redire=True))

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.lettres[0]["jugement"].decision == "j'hésite"


@pytest.mark.parametrize("champ_absent", ["decision"])
def test_critere2_juge_sans_decision_est_illisible(
    db_path, repertoire_path, cv_path, tournures_path, modeles, champ_absent
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    reponse = json.loads(_JUGE_RIEN_A_REDIRE)
    del reponse[champ_absent]
    modeles.programmer("juge", json.dumps(reponse))

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == raison_reponse_illisible("juge")
    assert resultat.erreur_type == "reponse_illisible"


def test_critere2_juge_avec_decision_hors_vocabulaire_est_illisible(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _juge(decision="peut-être", rien_a_redire=True))

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == raison_reponse_illisible("juge")


def test_critere3_jugement_sans_decision_se_lit_sans_erreur_par_l_api(db_path):
    """Un jugement déjà enregistré avant ce ticket (sans la clé « decision »)
    se relit sans erreur — l'API ne reconstruit jamais un `Jugement`, elle
    rend le JSON brut tel quel."""
    import api.db as api_db
    import api.lettre as api_lettre

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    jugement_sans_decision = json.dumps(
        {
            "rien_a_redire": True,
            "ressenti": "r",
            "details": "d",
            "reussites": "re",
            "verdict": "v",
        }
    )
    conn.execute(
        "INSERT INTO lettres (offer_id, statut, texte, jugement_json, created_at) "
        "VALUES (1, 'done', 'Lettre.', ?, '2026-01-01')",
        (jugement_sans_decision,),
    )
    conn.commit()
    conn.close()

    import orchestrator.job_search.storage.db as storage_db2

    storage_db2.DB_PATH = db_path
    api_db.DB_PATH = db_path

    lettre = api_lettre.get_lettre(1)
    assert lettre["jugement"]["rien_a_redire"] is True
    assert "decision" not in lettre["jugement"]


# --- critères 4-5 : la lettre la mieux jugée, pas la dernière ------------------


def test_critere4_au_plafond_la_decision_la_plus_forte_est_retenue(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge(decision="j'appelle", details="tour 1"),
        _juge(decision="je passe", details="tour 2"),
        _juge(decision="j'hésite", details="tour 3"),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == RAISON_PLAFOND + " — lettre du tour 1 retenue"
    assert resultat.lettre_retenue["texte"] == "Lettre 1."
    assert resultat.lettre_retenue["tour"] == 1


def test_critere4_a_egalite_la_plus_recente_est_retenue(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge(decision="j'appelle", details="tour 1"),
        _juge(decision="j'appelle", details="tour 2"),
        _juge(decision="j'hésite", details="tour 3"),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.lettre_retenue["texte"] == "Lettre 2."
    assert resultat.raison_fin == RAISON_PLAFOND + " — lettre du tour 2 retenue"


def test_critere5_rien_a_redire_retient_la_lettre_qui_vient_d_etre_jugee(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer(
        "juge",
        _juge(decision="je passe", details="tour 1"),
        _JUGE_RIEN_A_REDIRE,
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == RAISON_RIEN_A_REDIRE
    assert resultat.lettre_retenue["texte"] == "Lettre 2."


def test_plafond_sans_ecart_de_decision_ne_change_pas_la_raison(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    """Ce qui ne doit pas arriver : une boucle sans interprète, où toutes les
    décisions sont égales, retient la dernière lettre et garde la raison de
    fin inchangée (pas de suffixe) — comportement identique à avant ce ticket."""
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge(decision="j'appelle", details="tour 1"),
        _juge(decision="j'appelle", details="tour 2"),
        _juge(decision="j'appelle", details="tour 3"),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == RAISON_PLAFOND
    assert resultat.lettre_retenue["texte"] == "Lettre 3."


# --- critères 9-16 : l'interprète, au banc seulement ---------------------------


def test_critere9_sans_interprete_la_boucle_tourne_comme_avant(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path, config=_config())

    assert modeles.files["interprete"] == []
    assert not any(n == "interprete" for n, _, _ in modeles.appels)


def test_critere10_avec_interprete_il_ecrit_le_tour_suivant(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles.programmer(
        "interprete",
        json.dumps(
            {
                "ce_que_je_veux_lire": "Plus concret.",
                "lettre": "Lettre réécrite par l'interprète.",
            }
        ),
    )

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    assert [n for n, _, _ in modeles.appels] == [
        "tamis",
        "redaction",
        "juge",
        "interprete",
        "juge",
    ]
    assert resultat.lettres[1]["texte"] == "Lettre réécrite par l'interprète."
    assert resultat.lettres[1]["ce_que_je_veux_lire"] == "Plus concret."
    assert not any(
        n == "redaction" and i >= 2 for i, (n, _, _) in enumerate(modeles.appels)
    )


def test_critere11_lettre_de_l_interprete_traverse_le_verificateur_et_le_juge(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )
    rien_a_signaler = json.dumps(
        {"rien_a_signaler": True, "lieux": [], "affirmations": []}
    )
    modeles.programmer("verificateur", rien_a_signaler, rien_a_signaler)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    noeuds = [n for n, _, _ in modeles.appels]
    index_interprete = noeuds.index("interprete")
    assert "verificateur" in noeuds[index_interprete + 1 :]
    assert noeuds[-1] == "juge"


def test_critere12_interprete_recoit_lettre_jugee_rubriques_decision_et_consigne(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer(
        "juge",
        _juge(decision="je passe", details="Détail du tour 1."),
        _JUGE_RIEN_A_REDIRE,
    )
    modeles.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    demande_interprete = next(p for n, _, p in modeles.appels if n == "interprete")
    assert "Lettre 1." in demande_interprete
    assert "Détail du tour 1." in demande_interprete
    assert "je passe" in demande_interprete
    assert "Consigne de l'interprète." in demande_interprete
    assert "jamais de superlatif" in demande_interprete
    assert "Contenu CV de test" in demande_interprete
    assert "Citation 0" in demande_interprete


def test_critere13_reponse_de_l_interprete_sans_une_rubrique_est_illisible(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _juge(decision="je passe"))
    modeles.programmer(
        "interprete", json.dumps({"lettre": "Lettre réécrite, sans l'autre rubrique."})
    )

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    assert resultat.raison_fin == raison_reponse_illisible("interprete")
    assert resultat.erreur_type == "reponse_illisible"


def test_critere14_le_juge_ne_sait_pas_qui_a_ecrit_la_lettre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    demande_juge_2 = [p for n, _, p in modeles.appels if n == "juge"][1]
    assert "interprete" not in demande_juge_2
    assert "Plus concret." not in demande_juge_2
    assert "Lettre réécrite." in demande_juge_2


def test_critere16_appel_de_l_interprete_est_trace_comme_les_autres(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        config=_config(interprete="opus"),
    )

    appel_interprete = next(a for a in resultat.appels if a.noeud == "interprete")
    assert appel_interprete.modele == "opus"
    assert appel_interprete.tour == 2
    assert appel_interprete.duree_s >= 0
    assert appel_interprete.demande
    assert appel_interprete.reponse


# ═══════════════════════════════════════════════════════════════════════════
# Palier 2 — le répertoire (critère 15)
# ═══════════════════════════════════════════════════════════════════════════


def test_critere15_repertoire_sans_consigne_interprete_refuse_avant_tout_appel(
    repertoire_path,
):
    chemin = repertoire_path(avec_interprete=False)
    charge = charger_repertoire(chemin)

    with pytest.raises(RepertoireError):
        valider_interprete(charge.repertoire)


def test_critere15_repertoire_avec_consigne_interprete_passe(repertoire_path):
    chemin = repertoire_path(avec_interprete=True)
    charge = charger_repertoire(chemin)

    valider_interprete(charge.repertoire)  # ne lève pas


# ═══════════════════════════════════════════════════════════════════════════
# Palier 3 — le service (app) : critères 6, 7
# ═══════════════════════════════════════════════════════════════════════════


def _jugement(decision="j'appelle", rien_a_redire=True) -> Jugement:
    return Jugement(
        rien_a_redire=rien_a_redire,
        ressenti="r",
        details="d",
        reussites="re",
        verdict="v",
        decision=decision,
    )


def _lettre_entry(texte, tour, decision) -> dict:
    return {
        "texte": texte,
        "nb_mots": len(texte.split()),
        "tournures_signalees": [],
        "jugement": _jugement(decision=decision, rien_a_redire=False),
        "releve_redaction": {"tournures": [], "lieux": [], "affirmations": []},
        "releve_correction": None,
        "tour": tour,
    }


@pytest.fixture
def db_path_service(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    import api.db as api_db

    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


def _insert_offer_et_fiche(db_path, offer_id=1):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, "
            "'retenu', '2026-10-14')",
            (offer_id,),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, created_at) VALUES (?, 'done', 'P', '[]', '2026-10-14')",
            (offer_id,),
        )
        conn.commit()
    finally:
        conn.close()


def test_critere6_app_retient_la_lettre_la_mieux_jugee_pas_la_derniere(
    db_path_service, monkeypatch
):
    """La lettre courante (statut done) porte le texte et le jugement de la
    lettre la mieux jugée, et la raison de fin nomme le tour retenu."""
    import api.lettre as api_lettre

    offer_id = 1
    _insert_offer_et_fiche(db_path_service, offer_id)

    resultat = ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
        lettres=[
            _lettre_entry("Lettre 1.", 1, "j'appelle"),
            _lettre_entry("Lettre 2.", 2, "je passe"),
            _lettre_entry("Lettre 3.", 3, "j'hésite"),
        ],
        nb_tours=3,
        raison_fin=RAISON_PLAFOND + " — lettre du tour 1 retenue",
        appels=[],
        lettre_retenue={
            "texte": "Lettre 1.",
            "nb_mots": 2,
            "tournures_signalees": [],
            "jugement": _jugement(decision="j'appelle", rien_a_redire=False),
            "releve_redaction": {"tournures": [], "lieux": [], "affirmations": []},
            "releve_correction": None,
            "tour": 1,
        },
    )
    monkeypatch.setattr(
        lettre_service, "generer_lettre_depuis_donnees", lambda *a, **k: resultat
    )

    asyncio.run(lettre_service.run_lettre(offer_id))

    lettre = api_lettre.get_lettre(offer_id)
    assert lettre["texte"] == "Lettre 1."
    assert lettre["jugement"]["decision"] == "j'appelle"
    assert lettre["raison_fin"] == RAISON_PLAFOND + " — lettre du tour 1 retenue"


def test_critere7_regeneration_depuis_ma_lettre_retenue_au_tour_0_ne_cree_pas_de_version(
    db_path_service, monkeypatch
):
    """Même au plafond (plusieurs reprises), si la lettre retenue est ma
    propre lettre (tour 0), aucune version n'est créée — comme sur
    « rien à redire »."""
    import api.lettre as api_lettre

    offer_id = 2
    _insert_offer_et_fiche(db_path_service, offer_id)
    conn = sqlite3.connect(db_path_service)
    conn.execute(
        "INSERT INTO lettres (offer_id, statut, texte, created_at) VALUES (?, "
        "'done', 'Ma lettre écrite à la main.', '2026-10-14')",
        (offer_id,),
    )
    conn.execute(
        "INSERT INTO lettre_versions (offer_id, texte, origine, created_at) "
        "VALUES (?, 'Ma lettre écrite à la main.', 'moi', '2026-10-14')",
        (offer_id,),
    )
    conn.commit()
    conn.close()

    ma_lettre_entry = _lettre_entry("Ma lettre écrite à la main.", 0, "j'appelle")
    jugement_ma_lettre = ma_lettre_entry["jugement"]
    resultat = ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
        lettres=[
            ma_lettre_entry,
            _lettre_entry("Reprise 1.", 1, "je passe"),
            _lettre_entry("Reprise 2.", 2, "je passe"),
            _lettre_entry("Reprise 3.", 3, "j'hésite"),
        ],
        nb_tours=3,
        raison_fin=RAISON_PLAFOND + " — lettre du tour 0 retenue",
        appels=[],
        jugement_ma_lettre=jugement_ma_lettre,
        lettre_retenue=ma_lettre_entry,
    )
    monkeypatch.setattr(
        lettre_service, "generer_lettre_depuis_donnees", lambda *a, **k: resultat
    )

    asyncio.run(
        lettre_service.run_lettre_regenerate_depuis_ma_lettre(
            offer_id, "Ma lettre écrite à la main."
        )
    )

    versions = api_lettre.get_lettre_versions(offer_id)
    assert len(versions) == 1  # aucune version créée
    lettre = api_lettre.get_lettre(offer_id)
    assert lettre["texte"] == "Ma lettre écrite à la main."


# ═══════════════════════════════════════════════════════════════════════════
# Palier 4 — le banc : critères 9, 17, 21
# ═══════════════════════════════════════════════════════════════════════════


class FakeModelesBanc(FakeModeles):
    pass


@pytest.fixture
def modeles_banc(monkeypatch):
    fake = FakeModelesBanc()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


def _jeu_banc(*offer_ids) -> dict:
    return {
        "nom": "essai",
        "prepare_le": "2026-10-14T00:00:00Z",
        "offres": [
            {
                "offer_id": i,
                "intitule": "Titre",
                "entreprise": "Entreprise X",
                "texte_offre": "Texte de l'offre.",
                "faits": [
                    {
                        "position": "Point 0",
                        "citation": "Citation 0",
                        "url": "https://ex.test/0",
                        "famille": None,
                        "date": None,
                    }
                ],
                "raison_echec_recherche": None,
            }
            for i in offer_ids
        ],
    }


def test_critere9_le_banc_accepte_le_role_interprete(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1)
    modeles_banc.programmer("tamis", _TAMIS_POINT_0)
    modeles_banc.programmer("redaction", "Lettre 1.")
    modeles_banc.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles_banc.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )

    resultat = banc.lancer_banc(
        jeu,
        [1],
        ["sonnet,interprete=opus"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    passage = resultat.passages[0]
    assert passage.resultat.lettres[1]["texte"] == "Lettre réécrite."


def test_critere15_banc_refuse_avant_tout_appel_si_interprete_nomme_sans_consigne(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1)
    # Aucune réponse programmée : si un appel partait, la file vide lèverait.

    with pytest.raises(RepertoireError):
        banc.lancer_banc(
            jeu,
            [1],
            ["sonnet,interprete=opus"],
            repertoire_path=repertoire_path(avec_interprete=False),
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
            banc_dir=tmp_path / "banc",
        )
    assert modeles_banc.appels == []


def test_critere21_deux_configurations_differant_par_l_interprete_tournent_ensemble(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1)
    for _ in range(2):
        modeles_banc.programmer("tamis", _TAMIS_POINT_0)
        modeles_banc.programmer("redaction", "Lettre 1.")
        modeles_banc.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = banc.lancer_banc(
        jeu,
        [1],
        ["sonnet,juge=opus", "sonnet,juge=opus,interprete=opus"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    assert {r.config_nommee.label for r in resultat.resumes} == {
        "sonnet,juge=opus",
        "sonnet,juge=opus,interprete=opus",
    }


def test_critere17_tableau_compte_les_lettres_finales_par_decision(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1, 2)
    for offer_id, decision in ((1, "j'appelle"), (2, "je passe")):
        modeles_banc.programmer("tamis", _TAMIS_POINT_0)
        modeles_banc.programmer("redaction", f"Lettre offre {offer_id}.")
        modeles_banc.programmer("juge", _juge(decision=decision, rien_a_redire=True))

    resultat = banc.lancer_banc(
        jeu,
        [1, 2],
        ["sonnet"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    resume = resultat.resumes[0]
    assert resume.finales_j_appelle == 1
    assert resume.finales_je_passe == 1
    assert resume.finales_j_hesite == 0


def test_critere18_rapport_montre_la_lettre_retenue_avec_son_tour(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1)
    modeles_banc.programmer("tamis", _TAMIS_POINT_0)
    modeles_banc.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles_banc.programmer(
        "juge",
        _juge(decision="j'appelle", details="tour 1"),
        _juge(decision="je passe", details="tour 2"),
        _juge(decision="j'hésite", details="tour 3"),
    )

    resultat = banc.lancer_banc(
        jeu,
        [1],
        ["sonnet"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    texte_rapport = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Lettre 1." in texte_rapport
    assert "tour 1 retenu" in texte_rapport
    # La lettre non retenue (tour 3) ne figure pas comme « lettre finale ».
    section_lettres_finales = texte_rapport.split("### Lettres finales")[1].split(
        "## Annexe"
    )[0]
    assert "Lettre 3." not in section_lettres_finales


def test_critere19_annexe_montre_decision_a_chaque_tour_et_ce_que_je_veux_lire(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    jeu = _jeu_banc(1)
    modeles_banc.programmer("tamis", _TAMIS_POINT_0)
    modeles_banc.programmer("redaction", "Lettre 1.")
    modeles_banc.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles_banc.programmer(
        "interprete",
        json.dumps(
            {
                "ce_que_je_veux_lire": "Plus concret, moins de superlatifs.",
                "lettre": "Lettre réécrite par l'interprète.",
            }
        ),
    )

    resultat = banc.lancer_banc(
        jeu,
        [1],
        ["sonnet,interprete=opus"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    texte_rapport = resultat.rapport_path.read_text(encoding="utf-8")
    annexe = texte_rapport.split("## Annexe")[1]
    assert "Décision : je passe" in annexe
    assert "Décision : j'appelle" in annexe
    assert "Ce que je veux lire : Plus concret, moins de superlatifs." in annexe
    # Dans l'annexe, la rubrique précède la lettre qu'elle introduit.
    index_rubrique = annexe.index("Ce que je veux lire")
    index_lettre = annexe.index("Lettre réécrite par l'interprète.")
    assert index_rubrique < index_lettre


def test_critere20_run_mlflow_porte_le_modele_de_l_interprete_et_les_trois_comptes(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    from mlflow.tracking import MlflowClient

    jeu = _jeu_banc(1)
    modeles_banc.programmer("tamis", _TAMIS_POINT_0)
    modeles_banc.programmer("redaction", "Lettre 1.")
    modeles_banc.programmer("juge", _juge(decision="je passe"), _JUGE_RIEN_A_REDIRE)
    modeles_banc.programmer(
        "interprete",
        json.dumps(
            {"ce_que_je_veux_lire": "Plus concret.", "lettre": "Lettre réécrite."}
        ),
    )

    banc.lancer_banc(
        jeu,
        [1],
        ["sonnet,interprete=opus"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert run.data.params["modele_interprete"] == "opus"
    metrics = run.data.metrics
    assert metrics["finales_j_appelle"] == 1.0
    assert metrics["finales_j_hesite"] == 0.0
    assert metrics["finales_je_passe"] == 0.0


def test_critere20_sans_interprete_le_parametre_est_absent(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles_banc
):
    from mlflow.tracking import MlflowClient

    jeu = _jeu_banc(1)
    modeles_banc.programmer("tamis", _TAMIS_POINT_0)
    modeles_banc.programmer("redaction", "Lettre 1.")
    modeles_banc.programmer("juge", _JUGE_RIEN_A_REDIRE)

    banc.lancer_banc(
        jeu,
        [1],
        ["sonnet"],
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert "modele_interprete" not in run.data.params
