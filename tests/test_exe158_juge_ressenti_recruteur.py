"""Tests EXE-158 — le juge de la lettre dit ce qu'un recruteur ressent en la
lisant (plutôt que de la juger contre mes règles d'écriture), et la rédaction
corrige sur ce ressenti.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par
une doublure programmable (reprise de test_exe147_boucle_lettre.py). Aucun
test ne lit ni n'écrit sous data/ ou le mlflow.db du dépôt : le répertoire, le
CV de référence, les tournures interdites, les jeux et les rapports sont posés
dans tmp_path ; l'isolation MLflow est globale (conftest.py).
"""

import json
import sqlite3

import pytest
import yaml
from mlflow.tracking import MlflowClient

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_boucle,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu de mon CV de référence.</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (reprise de test_exe147_boucle_lettre.py) ---


class FakeModeles:
    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        if noeud == "verificateur" and not self.files["verificateur"]:
            # EXE-160 : sans programmation explicite, le vérificateur rend un
            # relevé vide et n'entre pas dans `self.appels` — les tests d'avant
            # la fiche gardent leurs index positionnels sur tamis/rédaction/juge.
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


def _config(modele="sonnet") -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis=modele, modele_redaction=modele, modele_juge=modele
    )


# --- fixtures de terrain ---------------------------------------------------


def _repertoire_donnees(
    *,
    version=7,
    juge_consigne="Consigne du juge : dis ce que tu ressens à la lecture.",
    juge_contexte="Contexte du juge : tu es un recruteur qui ne connaît pas le candidat.",
    juge_exemples=None,
    redaction_consigne_reprise="Corrige la lettre selon le ressenti du juge.",
    redaction_consigne_verification="Consigne de correction : corrige strictement le relevé.",
    verificateur_consigne="Consigne du vérificateur : tournures, lieux, affirmations.",
    ce_qui_est_vrai_sur_moi=None,
    lettre_de_reference=None,
) -> dict:
    donnees: dict = {
        "posture": {
            "role": "ingénieur qui prototype vite",
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [
                {"texte": "passionné par l'IA", "motif": "trop vu, sonne creux"}
            ],
        },
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
            }
        ],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": lettre_de_reference
            or "lettre envoyée à Entreprise X",
        },
        "textes_types": [
            {
                "id": "prototyper",
                "sujet": "sujet de prototyper",
                "conviction": "conviction de prototyper",
                "ce_que_j_ai_fait": "ce que j'ai fait pour prototyper",
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
    }
    if version is not None:
        donnees["version"] = version
    if ce_qui_est_vrai_sur_moi is not None:
        donnees["ce_qui_est_vrai_sur_moi"] = ce_qui_est_vrai_sur_moi
    juge: dict = {}
    if juge_consigne is not None:
        juge["consigne"] = juge_consigne
    if juge_contexte is not None:
        juge["contexte"] = juge_contexte
    if juge_exemples is not None:
        juge["exemples"] = juge_exemples
    if juge:
        donnees["juge"] = juge
    redaction: dict = {}
    if redaction_consigne_reprise is not None:
        redaction["consigne_reprise"] = redaction_consigne_reprise
    if redaction_consigne_verification is not None:
        redaction["consigne_verification"] = redaction_consigne_verification
    if redaction:
        donnees["redaction"] = redaction
    if verificateur_consigne is not None:
        donnees["verificateur"] = {"consigne": verificateur_consigne}
    return donnees


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(**kwargs):
        chemin = tmp_path / "repertoire.yaml"
        donnees = _repertoire_donnees(**kwargs)
        chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
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


def _poser_offre_et_fiche(db_path, offer_id=1, employeur_nom="Entreprise X"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre de l''offre', "
            "'Entreprise X SAS', 'Nous cherchons un ingénieur.')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, ?, "
            "'2026-10-08')",
            (offer_id, json.dumps(_points_fiche()), employeur_nom),
        )
        conn.commit()
    finally:
        conn.close()


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _lancer(
    db_path,
    repertoire_path,
    cv_path,
    tournures_path,
    config=None,
    offer_id=1,
    **repertoire_kwargs,
):
    conn = _conn(db_path)
    try:
        return generer_lettre_boucle(
            conn,
            offer_id,
            config or _config(),
            repertoire_path=repertoire_path(**repertoire_kwargs),
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
        )
    finally:
        conn.close()


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})


def _juge_json(
    *,
    rien_a_redire=True,
    ressenti="Ressenti neutre.",
    details="Détails neutres.",
    reussites="Réussites neutres.",
    verdict="Verdict neutre.",
) -> str:
    return json.dumps(
        {
            "rien_a_redire": rien_a_redire,
            "ressenti": ressenti,
            "details": details,
            "reussites": reussites,
            "verdict": verdict,
        }
    )


_JUGE_RIEN_A_REDIRE = _juge_json()


# =================================================================================
# Critères 1-4 : ce que reçoit (et ne reçoit pas) le juge
# =================================================================================


def test_critere1_juge_recoit_lettre_intitule_entreprise_et_texte_annonce(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Voici le texte complet de ma lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_juge = modeles.appels[2][2]
    assert "Voici le texte complet de ma lettre." in demande_juge
    assert "Titre de l'offre" in demande_juge
    assert "Entreprise X" in demande_juge
    assert "Nous cherchons un ingénieur." in demande_juge


def test_critere2_juge_recoit_consigne_et_contexte_en_entier(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        juge_consigne="Consigne du juge, phrase unique entière.",
        juge_contexte="Contexte du juge, phrase unique entière.",
    )

    demande_juge = modeles.appels[2][2]
    assert "Consigne du juge, phrase unique entière." in demande_juge
    assert "Contexte du juge, phrase unique entière." in demande_juge


def test_critere3_juge_recoit_chaque_exemple_de_relecture(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        juge_exemples=[
            {
                "titre": "Relecture A",
                "passage_lu": "Passage lu A, phrase unique.",
                "relecture": "Relecture A, phrase unique.",
            },
            {
                "titre": "Relecture B",
                "passage_lu": "Passage lu B, phrase unique.",
                "relecture": "Relecture B, phrase unique.",
            },
        ],
    )

    demande_juge = modeles.appels[2][2]
    assert "Passage lu A, phrase unique." in demande_juge
    assert "Relecture A, phrase unique." in demande_juge
    assert "Passage lu B, phrase unique." in demande_juge
    assert "Relecture B, phrase unique." in demande_juge


def test_critere4_juge_ne_recoit_aucune_regle_posture_ni_sujet_interdit_ni_vrai_sur_moi_ni_lettre_reference_ni_fait_ni_cv(  # noqa: E501
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        ce_qui_est_vrai_sur_moi=["Je code en Python depuis dix ans"],
        lettre_de_reference="Lettre de référence, phrase unique à ne pas envoyer.",
    )

    demande_juge = modeles.appels[2][2]
    # Règles de posture et formulations rejetées (réservées à la rédaction).
    assert "jamais de superlatif" not in demande_juge
    assert "passionné par l'IA" not in demande_juge
    # Sujets interdits.
    assert "Claude / Anthropic" not in demande_juge
    # Ce qui est vrai sur moi.
    assert "Je code en Python depuis dix ans" not in demande_juge
    # Lettre de référence.
    assert "Lettre de référence, phrase unique à ne pas envoyer." not in demande_juge
    # Fait retenu (point de la fiche entreprise).
    assert "Citation 0" not in demande_juge
    # CV de référence.
    assert "Contenu de mon CV de référence." not in demande_juge


# =================================================================================
# Critères 5-8 : la forme de la réponse du juge
# =================================================================================


def test_critere5_juge_rend_quatre_rubriques_et_rien_a_redire(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer(
        "juge",
        _juge_json(
            rien_a_redire=False,
            ressenti="Je ressens de la distance.",
            details="Le paragraphe 2 sonne creux.",
            reussites="L'accroche est précise.",
            verdict="À reprendre.",
        ),
        _JUGE_RIEN_A_REDIRE,
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    premier_jugement = resultat.lettres[0]["jugement"]
    assert premier_jugement.rien_a_redire is False
    assert premier_jugement.ressenti == "Je ressens de la distance."
    assert premier_jugement.details == "Le paragraphe 2 sonne creux."
    assert premier_jugement.reussites == "L'accroche est précise."
    assert premier_jugement.verdict == "À reprendre."


@pytest.mark.parametrize("champ", ["ressenti", "details", "reussites", "verdict"])
def test_critere6_reponse_a_qui_manque_une_rubrique_arrete_reponse_illisible(
    db_path, repertoire_path, cv_path, tournures_path, modeles, champ
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    data = json.loads(_JUGE_RIEN_A_REDIRE)
    del data[champ]
    modeles.programmer("juge", json.dumps(data))

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert (
        resultat.raison_fin
        == "Le juge a rendu une réponse que le code ne sait pas lire"
    )
    assert len(resultat.lettres) == 1
    assert resultat.lettres[0]["jugement"] is None


def test_critere7_rien_a_redire_arrete_la_boucle_sur_cette_lettre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.raison_fin == boucle.RAISON_RIEN_A_REDIRE
    assert resultat.nb_tours == 1


def test_critere8_sans_exemple_de_relecture_ni_rubrique_vide_ni_none(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_juge = modeles.appels[2][2]
    assert "Exemples de relecture" not in demande_juge
    assert "None" not in demande_juge


# =================================================================================
# Critères 9-12 : la rédaction au tour suivant
# =================================================================================


def test_critere9_redaction_tour2_recoit_lettre_precedente_quatre_rubriques_et_consigne_reprise(  # noqa: E501
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer(
        "juge",
        _juge_json(
            rien_a_redire=False,
            ressenti="Ressenti du tour 1.",
            details="Détails du tour 1.",
            reussites="Réussites du tour 1.",
            verdict="Verdict du tour 1.",
        ),
        _JUGE_RIEN_A_REDIRE,
    )

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        redaction_consigne_reprise="Consigne de reprise, phrase unique.",
    )

    demande_redaction_2 = modeles.appels[3][2]
    assert "Lettre 1." in demande_redaction_2
    assert "Ressenti du tour 1." in demande_redaction_2
    assert "Détails du tour 1." in demande_redaction_2
    assert "Réussites du tour 1." in demande_redaction_2
    assert "Verdict du tour 1." in demande_redaction_2
    assert "Consigne de reprise, phrase unique." in demande_redaction_2


def test_critere10_redaction_tour3_ne_recoit_que_le_dernier_jugement(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge_json(rien_a_redire=False, details="Détails du tour 1, à oublier."),
        _juge_json(rien_a_redire=False, details="Détails du tour 2, le dernier."),
        _JUGE_RIEN_A_REDIRE,
    )

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction_3 = modeles.appels[5][2]
    assert "Détails du tour 2, le dernier." in demande_redaction_3
    assert "Détails du tour 1, à oublier." not in demande_redaction_3


def test_critere11_premier_tour_rédaction_sans_bloc_de_reprise(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction_1 = modeles.appels[1][2]
    assert "Lettre précédente" not in demande_redaction_1
    assert "Consigne de reprise" not in demande_redaction_1


def test_critere12_troisieme_lettre_jugee_arrete_sur_le_plafond(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge_json(rien_a_redire=False, details="remarque 1"),
        _juge_json(rien_a_redire=False, details="remarque 2"),
        _juge_json(rien_a_redire=False, details="remarque 3"),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 3
    assert resultat.raison_fin == boucle.RAISON_PLAFOND
    assert sum(1 for n, _, _ in modeles.appels if n == "redaction") == 3


# =================================================================================
# Critères 13-14 : le répertoire, refusé avant tout appel de modèle
# =================================================================================


@pytest.fixture
def jeux_dir(tmp_path):
    chemin = tmp_path / "jeux"
    chemin.mkdir()
    return chemin


def _jeu_simple(offer_id=1) -> dict:
    return {
        "nom": "essai",
        "prepare_le": "2026-10-08T00:00:00Z",
        "offres": [
            {
                "offer_id": offer_id,
                "intitule": "Titre",
                "entreprise": "Entreprise X",
                "texte_offre": "Texte de l'offre.",
                "faits": [],
                "raison_echec_recherche": None,
            }
        ],
    }


def _poser_jeu(jeux_dir, nom="essai", offer_id=1):
    (jeux_dir / f"{nom}.json").write_text(
        json.dumps(_jeu_simple(offer_id)), encoding="utf-8"
    )


@pytest.fixture
def banc_dir(tmp_path):
    return tmp_path / "banc"


@pytest.mark.parametrize(
    "kwargs,attendu",
    [
        ({"juge_consigne": None}, "consigne du juge"),
        ({"juge_contexte": None}, "contexte du juge"),
    ],
)
def test_critere13_banc_refuse_si_consigne_ou_contexte_du_juge_manque(
    repertoire_path,
    cv_path,
    tournures_path,
    banc_dir,
    jeux_dir,
    modeles,
    capsys,
    kwargs,
    attendu,
):
    _poser_jeu(jeux_dir)
    chemin_repertoire = repertoire_path(**kwargs)

    code = banc.main(
        ["--jeu", "essai", "--config", "sonnet"],
        repertoire_path=chemin_repertoire,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeux_dir=jeux_dir,
    )

    assert code == 1
    assert attendu in capsys.readouterr().out
    assert modeles.appels == []


def test_critere14_banc_refuse_si_consigne_de_reprise_manque(
    repertoire_path, cv_path, tournures_path, banc_dir, jeux_dir, modeles, capsys
):
    _poser_jeu(jeux_dir)
    chemin_repertoire = repertoire_path(redaction_consigne_reprise=None)

    code = banc.main(
        ["--jeu", "essai", "--config", "sonnet"],
        repertoire_path=chemin_repertoire,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeux_dir=jeux_dir,
    )

    assert code == 1
    assert "consigne de reprise" in capsys.readouterr().out
    assert modeles.appels == []


# =================================================================================
# Critères 15-18 : le banc (rapport et MLflow)
# =================================================================================


def _programmer_passage_simple(modeles, lettre="Lettre finale."):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", lettre)
    modeles.programmer(
        "juge", _juge_json(verdict="Verdict final de la lettre, phrase unique.")
    )


def _lancer_banc(
    jeu,
    repertoire_path,
    cv_path,
    tournures_path,
    banc_dir,
    offer_ids,
    config_specs,
    jeu_path=None,
):
    return banc.lancer_banc(
        jeu,
        offer_ids,
        config_specs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeu_path=jeu_path,
    )


def test_critere15_run_mlflow_porte_version_repertoire_en_parametre_et_fichier_en_piece(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu_simple(1)
    _programmer_passage_simple(modeles)
    chemin_repertoire = repertoire_path(version=7)

    _lancer_banc(
        jeu, chemin_repertoire, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert run.data.params["repertoire_version"] == "7"
    artefacts = {a.path for a in client.list_artifacts(run.info.run_id)}
    assert chemin_repertoire.name in artefacts


def test_critere16_entete_du_rapport_donne_le_numero_de_version(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu_simple(1)
    _programmer_passage_simple(modeles)
    chemin_repertoire = repertoire_path(version=7)

    resultat = _lancer_banc(
        jeu, chemin_repertoire, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Répertoire version : 7" in texte


def test_critere16_entete_du_rapport_sans_version_pas_zero(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu_simple(1)
    _programmer_passage_simple(modeles)
    chemin_repertoire = repertoire_path(version=None)

    resultat = _lancer_banc(
        jeu, chemin_repertoire, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Répertoire version : sans version" in texte
    assert "Répertoire version : 0" not in texte


def test_critere17_annexe_montre_la_lettre_puis_les_quatre_rubriques_sous_leur_nom(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu_simple(1)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre à annexer.")
    modeles.programmer(
        "juge",
        _juge_json(
            ressenti="Ressenti d'annexe.",
            details="Détails d'annexe.",
            reussites="Réussites d'annexe.",
            verdict="Verdict d'annexe.",
        ),
    )
    chemin_repertoire = repertoire_path()

    resultat = _lancer_banc(
        jeu, chemin_repertoire, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    annexe = resultat.rapport_path.read_text(encoding="utf-8").split("## Annexe")[1]
    assert "Lettre à annexer." in annexe
    idx_lettre = annexe.index("Lettre à annexer.")
    idx_ressenti = annexe.index("Ressenti : Ressenti d'annexe.")
    idx_details = annexe.index("Détails : Détails d'annexe.")
    idx_reussites = annexe.index("Réussites : Réussites d'annexe.")
    idx_verdict = annexe.index("Verdict : Verdict d'annexe.")
    assert idx_lettre < idx_ressenti < idx_details < idx_reussites < idx_verdict


def test_critere18_table_mlflow_porte_le_verdict_du_juge_sur_la_lettre_finale(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    import mlflow

    jeu = _jeu_simple(1)
    _programmer_passage_simple(modeles)
    chemin_repertoire = repertoire_path()

    _lancer_banc(
        jeu, chemin_repertoire, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    path = mlflow.artifacts.download_artifacts(
        run_id=run.info.run_id, artifact_path="passages.json"
    )
    table = json.loads(open(path, encoding="utf-8").read())
    idx = table["columns"].index("verdict_juge_lettre_finale")
    assert table["data"][0][idx] == "Verdict final de la lettre, phrase unique."


# =================================================================================
# Ce qui ne doit pas arriver
# =================================================================================


def test_graphe_de_la_boucle_inchange():
    mermaid = boucle.dessiner_graphe()
    assert "tamis" in mermaid
    assert "redaction" in mermaid
    assert "juge" in mermaid
    assert "juge -.-> redaction" in mermaid
    assert boucle.MAX_TOURS == 3


def test_tamis_ne_recoit_rien_du_juge(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        juge_consigne="Consigne du juge, ne doit pas atteindre le tamis.",
    )

    demande_tamis = modeles.appels[0][2]
    assert "Consigne du juge, ne doit pas atteindre le tamis." not in demande_tamis
