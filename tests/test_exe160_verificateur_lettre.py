"""Tests EXE-160 — un vérificateur relit chaque lettre avant le juge : tournures
interdites, lieu absent de l'annonce, affirmations que rien ne soutient.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par une
doublure programmable (reprise de test_exe147_boucle_lettre.py et
test_exe158_juge_ressenti_recruteur.py). Aucun test ne lit ni n'écrit sous data/ ou
le mlflow.db du dépôt : le répertoire, le CV de référence, les tournures interdites,
les jeux et les rapports sont posés dans tmp_path ; l'isolation MLflow est globale
(conftest.py).
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
TOURNURES_INTERDITES = "je veux\npas seulement\n"


# --- doublure des appels de modèle (reprise de test_exe147_boucle_lettre.py) ------


class FakeModeles:
    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
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


# --- fixtures de terrain -----------------------------------------------------


def _repertoire_donnees(
    *,
    version=4,
    juge_consigne="Consigne du juge : dis ce que tu ressens à la lecture.",
    juge_contexte="Contexte du juge : tu es un recruteur qui ne connaît pas le candidat.",
    redaction_consigne_reprise="Corrige la lettre selon le ressenti du juge.",
    redaction_consigne_verification="Corrige strictement le relevé, sans ajouter de fait.",
    verificateur_consigne="Relis la lettre : tournures, lieux absents, affirmations non soutenues.",
    ce_qui_est_vrai_sur_moi=None,
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
            "lettre_de_reference": "lettre envoyée à Entreprise X",
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
        {
            "position": "Point 0",
            "citation": "Citation notable 0",
            "url": "https://ex.test/0",
        }
    ]


def _poser_offre_et_fiche(db_path, offer_id=1, employeur_nom="Entreprise X"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre de l''offre', "
            "'Entreprise X SAS', 'Nous cherchons un ingénieur à Strasbourg.')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, ?, "
            "'2026-10-09')",
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


def _verif_json(*, rien_a_signaler=True, lieux=None, affirmations=None) -> str:
    return json.dumps(
        {
            "rien_a_signaler": rien_a_signaler,
            "lieux": lieux or [],
            "affirmations": affirmations or [],
        }
    )


_VERIF_RIEN_A_SIGNALER = _verif_json()


# =================================================================================
# Critères 1-6 : le vérificateur
# =================================================================================


def test_critere1_verificateur_appele_apres_chaque_redaction_et_releve_enregistre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Voici ma lettre.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    noeuds = [appel[0] for appel in modeles.appels]
    assert noeuds == ["tamis", "redaction", "verificateur", "juge"]
    lettre = resultat.lettres[0]
    assert lettre["releve_redaction"] == {
        "tournures": [],
        "lieux": [],
        "affirmations": [],
    }


def test_critere2_tournures_interdites_relevees_sans_appel_de_modele(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Je veux rejoindre cette entreprise.")
    # Le modèle du vérificateur ne relève ni lieu ni affirmation : les tournures
    # sont trouvées quand même, par `detect_tournures`, jamais par le modèle.
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("redaction", "Lettre corrigée, sans tournure.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.lettres[0]["releve_redaction"]["tournures"] == ["Je veux"]


def test_critere3_lieux_absents_de_annonce_relevés_avec_phrase(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Je suis ravi de rejoindre vos bureaux de Paris.")
    modeles.programmer(
        "verificateur",
        _verif_json(
            lieux=[
                {
                    "lieu": "Paris",
                    "phrase": "Je suis ravi de rejoindre vos bureaux de Paris.",
                }
            ]
        ),
    )
    modeles.programmer("redaction", "Lettre corrigée, sans lieu inventé.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    lieux = resultat.lettres[0]["releve_redaction"]["lieux"]
    assert lieux == [
        {"lieu": "Paris", "phrase": "Je suis ravi de rejoindre vos bureaux de Paris."}
    ]


def test_critere4_affirmations_non_soutenues_relevees_avec_passage_et_manque(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "J'ai dirigé une équipe de 40 personnes.")
    modeles.programmer(
        "verificateur",
        _verif_json(
            affirmations=[
                {
                    "passage": "J'ai dirigé une équipe de 40 personnes.",
                    "manque": "aucune source ne mentionne une équipe de 40 personnes",
                }
            ]
        ),
    )
    modeles.programmer("redaction", "Lettre corrigée, sans affirmation inventée.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    affirmations = resultat.lettres[0]["releve_redaction"]["affirmations"]
    assert affirmations == [
        {
            "passage": "J'ai dirigé une équipe de 40 personnes.",
            "manque": "aucune source ne mentionne une équipe de 40 personnes",
        }
    ]


def test_critere5_verificateur_recoit_la_liste_precise_sans_posture_ni_sujets_interdits_ni_juge(  # noqa: E501
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        verificateur_consigne="Consigne du vérificateur, phrase unique.",
        ce_qui_est_vrai_sur_moi=["Je code en Python depuis dix ans"],
    )

    demande_verif = modeles.appels[2][2]
    assert modeles.appels[2][0] == "verificateur"
    # Reçoit : consigne, lettre, offre, ce qui est vrai sur moi, CV, fait retenu.
    assert "Consigne du vérificateur, phrase unique." in demande_verif
    assert "Lettre." in demande_verif
    assert "Titre de l'offre" in demande_verif
    assert "Je code en Python depuis dix ans" in demande_verif
    assert "Contenu de mon CV de référence." in demande_verif
    assert "Citation notable 0" in demande_verif
    # Ne reçoit pas : posture, sujets interdits, rubriques du juge.
    assert "jamais de superlatif" not in demande_verif
    assert "passionné par l'IA" not in demande_verif
    assert "Claude / Anthropic" not in demande_verif
    assert "Consigne du juge" not in demande_verif
    assert "Contexte du juge" not in demande_verif


def test_critere6_releve_vide_rien_a_signaler_releve_partiel_sans_rubrique_vide():
    vide = {"tournures": [], "lieux": [], "affirmations": []}
    assert boucle.releve_vide(vide) is True
    assert boucle.releve_txt(vide) == "Rien à signaler."

    partiel = {
        "tournures": [],
        "lieux": [{"lieu": "Lyon", "phrase": "phrase avec Lyon"}],
        "affirmations": [],
    }
    texte = boucle.releve_txt(partiel)
    assert "Lyon" in texte
    assert "Tournures interdites" not in texte
    assert "Affirmations non soutenues" not in texte
    assert "None" not in texte


# =================================================================================
# Critères 7-11 : la correction
# =================================================================================


def test_critere7_releve_non_vide_renvoie_a_la_redaction_puis_va_au_juge_quel_que_soit_le_second_releve(  # noqa: E501
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Je veux cette offre.", "Lettre corrigée.")
    modeles.programmer(
        "verificateur",
        _verif_json(lieux=[{"lieu": "Lyon", "phrase": "phrase avec Lyon"}]),
        # Le second relevé reste non vide : la lettre va au juge malgré tout.
        _verif_json(lieux=[{"lieu": "Lyon", "phrase": "phrase avec Lyon"}]),
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    noeuds = [appel[0] for appel in modeles.appels]
    assert noeuds == [
        "tamis",
        "redaction",
        "verificateur",
        "redaction",
        "verificateur",
        "juge",
    ]
    lettre = resultat.lettres[0]
    assert lettre["texte_redige"] == "Je veux cette offre."
    assert lettre["texte_corrige"] == "Lettre corrigée."
    assert lettre["texte"] == "Lettre corrigée."
    assert resultat.nb_tours == 1
    demande_juge = modeles.appels[5][2]
    assert "Lettre corrigée." in demande_juge


def test_critere8_releve_vide_va_direct_au_juge_sans_repasser_par_la_redaction(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre propre.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    noeuds = [appel[0] for appel in modeles.appels]
    assert noeuds == ["tamis", "redaction", "verificateur", "juge"]


def test_critere9_correction_ne_compte_pas_comme_un_tour_plafond_reste_trois(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    # Trois tours jugés, chacun corrigé une fois par le vérificateur.
    modeles.programmer(
        "redaction",
        "Je veux 1.",
        "Corrigée 1.",
        "Je veux 2.",
        "Corrigée 2.",
        "Je veux 3.",
        "Corrigée 3.",
    )
    modeles.programmer(
        "verificateur",
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer(
        "juge",
        _juge_json(rien_a_redire=False),
        _juge_json(rien_a_redire=False),
        _juge_json(rien_a_redire=False),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 3
    assert resultat.raison_fin == boucle.RAISON_PLAFOND
    noeuds_redaction = [a for a in modeles.appels if a[0] == "redaction"]
    assert len(noeuds_redaction) == 6


def test_critere10_demande_de_correction_ne_contient_jamais_de_rubrique_du_juge(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer(
        "redaction", "Je veux 1.", "Corrigée 1.", "Je veux 2.", "Corrigée 2."
    )
    modeles.programmer(
        "verificateur",
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer(
        "juge",
        _juge_json(
            rien_a_redire=False,
            ressenti="Ressenti du premier tour, jamais à la correction.",
        ),
        _JUGE_RIEN_A_REDIRE,
    )

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demandes_redaction = [a[2] for a in modeles.appels if a[0] == "redaction"]
    # Tour 1, correction (pas de juge encore) : pas de rubrique du juge.
    assert "Ressenti" not in demandes_redaction[1]
    assert "Verdict du juge" not in demandes_redaction[1]
    # Tour 2, correction qui suit une reprise : toujours pas de rubrique du juge,
    # même si le ressenti du tour 1 existe.
    assert (
        "Ressenti du premier tour, jamais à la correction." not in demandes_redaction[3]
    )
    assert "Verdict du juge" not in demandes_redaction[3]


def test_critere11_juge_ne_recoit_jamais_le_releve_du_verificateur(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Je veux 1.", "Corrigée 1.")
    modeles.programmer(
        "verificateur",
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_juge = [a[2] for a in modeles.appels if a[0] == "juge"][0]
    assert "Lyon" not in demande_juge
    assert "vérificateur" not in demande_juge.lower()


# =================================================================================
# Critère 12 : le répertoire
# =================================================================================


@pytest.mark.parametrize(
    "kwargs,attendu",
    [
        ({"verificateur_consigne": None}, "consigne du vérificateur"),
        ({"redaction_consigne_verification": None}, "consigne de correction"),
    ],
)
def test_critere12_banc_refuse_si_consigne_du_verificateur_ou_de_correction_manque(
    repertoire_path, cv_path, tournures_path, tmp_path, modeles, capsys, kwargs, attendu
):
    jeux_dir = tmp_path / "jeux"
    jeux_dir.mkdir()
    (jeux_dir / "essai.json").write_text(
        json.dumps(
            {
                "nom": "essai",
                "offres": [
                    {
                        "offer_id": 1,
                        "intitule": "Titre",
                        "entreprise": "Entreprise X",
                        "texte_offre": "Texte de l'offre.",
                        "faits": [],
                        "raison_echec_recherche": None,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    chemin_repertoire = repertoire_path(**kwargs)

    code = banc.main(
        ["--jeu", "essai", "--config", "sonnet"],
        repertoire_path=chemin_repertoire,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=tmp_path / "banc",
        jeux_dir=jeux_dir,
    )

    assert code == 1
    assert attendu in capsys.readouterr().out
    assert modeles.appels == []


# =================================================================================
# Critères 13-17 : le banc
# =================================================================================


@pytest.fixture
def jeux_dir(tmp_path):
    chemin = tmp_path / "jeux"
    chemin.mkdir()
    return chemin


def _jeu_simple(offer_id=1) -> dict:
    return {
        "nom": "essai",
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


@pytest.fixture
def banc_dir(tmp_path):
    return tmp_path / "banc"


def _lancer_banc(repertoire_path, cv_path, tournures_path, banc_dir, config_specs):
    jeu = _jeu_simple(1)
    return banc.lancer_banc(
        jeu,
        [1],
        config_specs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
    )


def test_critere13_quatre_mesures_verif_dans_la_table_et_mlflow(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer(
        "redaction", "Je veux cette offre.", "Corrigée mais je veux toujours."
    )
    modeles.programmer(
        "verificateur",
        _verif_json(
            rien_a_signaler=False,
            lieux=[{"lieu": "Lyon", "phrase": "x"}],
            affirmations=[{"passage": "y", "manque": "z"}],
        ),
        # second relevé encore signalé (la tournure subsiste) : va au juge quand même.
        _verif_json(rien_a_signaler=False),
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    chemin_repertoire = repertoire_path()
    resultat = _lancer_banc(
        chemin_repertoire, cv_path, tournures_path, banc_dir, ["sonnet"]
    )

    resume = resultat.resumes[0]
    # « je veux » relevé au premier passage ET au second (correction imparfaite).
    assert resume.verif_tournures == 2
    assert resume.verif_lieux == 1
    assert resume.verif_affirmations == 1
    assert resume.lettres_finales_signalees == 1  # second relevé encore signalé

    texte_rapport = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Tournures relevées (vérificateur)" in texte_rapport

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert run.data.metrics["verif_tournures"] == 2.0
    assert run.data.metrics["verif_lieux"] == 1.0
    assert run.data.metrics["verif_affirmations"] == 1.0
    assert run.data.metrics["lettres_finales_signalees"] == 1.0


def test_critere14_annexe_montre_lettre_redigee_releve_lettre_corrigee_second_releve_puis_juge(  # noqa: E501
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Je veux cette offre.", "Lettre corrigée finale.")
    modeles.programmer(
        "verificateur",
        _verif_json(rien_a_signaler=False, lieux=[{"lieu": "Lyon", "phrase": "x"}]),
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer("juge", _juge_json(verdict="Verdict final, phrase unique."))

    chemin_repertoire = repertoire_path()
    resultat = _lancer_banc(
        chemin_repertoire, cv_path, tournures_path, banc_dir, ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    i_redigee = texte.index("Je veux cette offre.")
    i_releve = texte.index("Lyon", i_redigee)
    i_corrigee = texte.index("Lettre corrigée finale.", i_releve)
    i_second_releve = texte.index("rien à signaler.", i_corrigee)
    i_verdict = texte.index("Verdict final, phrase unique.", i_second_releve)
    assert i_redigee < i_releve < i_corrigee < i_second_releve < i_verdict


def test_critere15_config_du_banc_accepte_verif_et_defaut_au_modele_de_redaction():
    config_sans_verif = banc.parser_config("sonnet,redaction=opus").config
    assert config_sans_verif.modele_verificateur is None
    assert config_sans_verif.modele_verificateur_effectif() == "opus"

    config_avec_verif = banc.parser_config("sonnet,verif=opus").config
    assert config_avec_verif.modele_verificateur == "opus"
    assert config_avec_verif.modele_verificateur_effectif() == "opus"


def test_critere16_duree_des_noeuds_de_annexe_liste_appel_verificateur_nomme(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("verificateur", _VERIF_RIEN_A_SIGNALER)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    chemin_repertoire = repertoire_path()
    resultat = _lancer_banc(
        chemin_repertoire, cv_path, tournures_path, banc_dir, ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "verificateur (sonnet)" in texte


def test_critere17_mesure_tournures_lettre_finale_reste_celle_de_la_lettre_finale(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    # Deux tournures au premier jet, corrigées à zéro : la mesure historique ne
    # compte que la lettre finale (0), le nouveau total du vérificateur compte
    # les deux relevées avant correction.
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer(
        "redaction", "Je veux pas seulement cette offre.", "Lettre propre."
    )
    modeles.programmer(
        "verificateur",
        _verif_json(rien_a_signaler=False),
        _VERIF_RIEN_A_SIGNALER,
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    chemin_repertoire = repertoire_path()
    resultat = _lancer_banc(
        chemin_repertoire, cv_path, tournures_path, banc_dir, ["sonnet"]
    )

    resume = resultat.resumes[0]
    assert resume.total_tournures == 0
    assert resume.lettres_sans_tournures == 1
    assert resume.verif_tournures == 2
