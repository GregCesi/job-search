"""Tests EXE-152 — le banc de la lettre mesure chaque lettre finale : ses
tournures interdites, son écart en mots à la longueur cible du répertoire, et
six observables par configuration (dont le compte des arrêts par réponse
illisible ou appel échoué) — dans le rapport comme dans MLflow. L'annexe donne
en plus le nombre de jetons lus par un appel à un modèle local.

Aucune de ces mesures n'appelle de modèle : elles viennent des champs déjà
rendus par la boucle (tournures, mots, type d'erreur) ou d'un calcul Python
pur sur eux. `boucle.appeler_modele` est remplacé par une doublure
programmable (reprise de test_exe148_banc_lettre.py) ; aucun test ne lit ni
n'écrit sous data/ ou le mlflow.db du dépôt (isolation globale, conftest.py).
"""

import json

import mlflow
import pytest
import yaml
from mlflow.tracking import MlflowClient

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import AppelModeleError, ReponseModele

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (reprise de test_exe148_banc_lettre.py) ---


class FakeModeles:
    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        self.appels.append((noeud, modele, prompt_text))
        valeur = self.files[noeud].pop(0)
        if isinstance(valeur, BaseException):
            raise valeur
        cout = 0.01 if modele in boucle.MODELES_CLAUDE else None
        # EXE-152, critères 19, 20 : un modèle local rend un nombre de jetons
        # lus, jamais Claude.
        nb_jetons = None if modele in boucle.MODELES_CLAUDE else 321
        return ReponseModele(
            texte=valeur, duree_s=0.01, cout_usd=cout, nb_jetons=nb_jetons
        )


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


# --- fixtures de terrain ---------------------------------------------------


def _repertoire_donnees(longueur_cible_mots=160) -> dict:
    donnees: dict = {
        "version": 1,
        "posture": {"role": "ingénieur", "regles": ["jamais de superlatif"]},
        "forme": {},
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
        "redaction": {"consigne_reprise": "Consigne de reprise."},
    }
    if longueur_cible_mots is not None:
        donnees["forme"]["longueur_cible_mots"] = longueur_cible_mots
    return donnees


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(longueur_cible_mots=160):
        chemin = tmp_path / "repertoire.yaml"
        chemin.write_text(
            yaml.safe_dump(
                _repertoire_donnees(longueur_cible_mots), allow_unicode=True
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
def banc_dir(tmp_path):
    return tmp_path / "banc"


def _entree_jeu(offer_id, *, titre="Titre de l'offre", entreprise="Entreprise X"):
    return {
        "offer_id": offer_id,
        "intitule": titre,
        "entreprise": entreprise,
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


def _jeu(*offer_ids) -> dict:
    return {
        "nom": "essai",
        "prepare_le": "2026-10-07T00:00:00Z",
        "offres": [_entree_jeu(i) for i in offer_ids],
    }


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


def _programmer_passage_simple(modeles, lettre="Lettre finale."):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", lettre)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)


def _lancer(
    jeu, repertoire_path, cv_path, tournures_path, banc_dir, offer_ids, config_specs
):
    return banc.lancer_banc(
        jeu,
        offer_ids,
        config_specs,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
    )


# --- critères 6-7 : tournures interdites citées sous la lettre finale ---------


def test_critere6_tournures_interdites_citees_sous_la_lettre_finale(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Je veux rejoindre votre équipe.")

    resultat = _lancer(
        jeu, repertoire_path(), cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Tournures interdites : « Je veux »" in texte


def test_critere7_aucune_tournure_interdite_le_rapport_le_dit(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre tout à fait correcte.")

    resultat = _lancer(
        jeu, repertoire_path(), cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Aucune tournure interdite." in texte


# --- critères 8-9 : écart en mots à la longueur cible -------------------------


def test_critere8_ecart_en_mots_avec_signe(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Un deux trois quatre cinq.")  # 5 mots

    resultat = _lancer(
        jeu, repertoire_path(160), cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Écart à la longueur cible : -155 mot(s)" in texte


def test_critere9_sans_longueur_cible_ecart_absent_sans_zero(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Un deux trois quatre cinq.")

    resultat = _lancer(
        jeu,
        repertoire_path(longueur_cible_mots=None),
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet"],
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Écart à la longueur cible" not in texte
    assert "0 mot(s)" not in texte


# --- critères 10-16 : tableau de comparaison et métriques MLflow -------------


def test_criteres10a16_six_mesures_du_tableau_et_de_mlflow(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2, 3, 4)
    lettre_propre = "Un deux trois quatre cinq."  # 5 mots, écart -155
    lettre_avec_tournure = "Je veux vraiment ce poste maintenant."  # 6 mots, -154

    modeles.programmer(
        "tamis",
        _TAMIS_POINT_0,
        _TAMIS_POINT_0,
        "ceci n'est pas du JSON",  # offre 3 : réponse illisible
        _TAMIS_POINT_0,
    )
    modeles.programmer(
        "redaction",
        lettre_propre,
        lettre_avec_tournure,
        AppelModeleError("boom"),  # offre 4 : appel échoué
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE, _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(
        jeu,
        repertoire_path(160),
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2, 3, 4],
        ["sonnet"],
    )

    resume = resultat.resumes[0]
    assert resume.lettres_sans_tournures == 1
    assert resume.total_tournures == 1
    assert resume.juge_rien_a_redire == 2
    assert resume.erreurs_reponse_illisible == 1
    assert resume.erreurs_appel_echoue == 1
    assert resume.ecart_moyen_abs_mots == pytest.approx((155 + 154) / 2)

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    for titre_colonne in [
        "Lettres sans tournure interdite",
        "Tournures interdites trouvées",
        "Écart moyen (abs) à la longueur cible",
        "Lettres sans rien à redire",
        "Réponses illisibles",
        "Appels échoués",
    ]:
        assert titre_colonne in texte

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    metrics = run.data.metrics
    assert metrics["lettres_sans_tournures"] == 1.0
    assert metrics["total_tournures"] == 1.0
    assert metrics["juge_rien_a_redire"] == 2.0
    assert metrics["erreurs_reponse_illisible"] == 1.0
    assert metrics["erreurs_appel_echoue"] == 1.0
    assert metrics["ecart_moyen_abs_mots"] == pytest.approx((155 + 154) / 2)


# --- critère 17 : la table MLflow porte tournures et écart par offre ---------


def test_critere17_table_mlflow_porte_tournures_et_ecart_par_offre(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    modeles.programmer("tamis", _TAMIS_POINT_0, _TAMIS_POINT_0)
    modeles.programmer(
        "redaction", "Un deux trois quatre cinq.", "Je veux vraiment ce poste."
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE, _JUGE_RIEN_A_REDIRE)

    _lancer(
        jeu, repertoire_path(160), cv_path, tournures_path, banc_dir, [1, 2], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    path = mlflow.artifacts.download_artifacts(
        run_id=run.info.run_id, artifact_path="passages.json"
    )
    table = json.loads(open(path, encoding="utf-8").read())
    colonnes = table["columns"]
    idx_offre = colonnes.index("offre")
    idx_tournures = colonnes.index("tournures_lettre_finale")
    idx_ecart = colonnes.index("ecart_mots")
    lignes = {ligne[idx_offre]: ligne for ligne in table["data"]}

    assert lignes[1][idx_tournures] == []
    assert lignes[1][idx_ecart] == 5 - 160
    assert lignes[2][idx_tournures] == ["Je veux"]
    assert lignes[2][idx_ecart] == 5 - 160  # "Je veux vraiment ce poste." = 5 mots


# --- critères 19-20 : jetons lus, modèle local seulement, jamais un zéro -----


def test_critere19_annexe_donne_les_jetons_lus_par_un_modele_local(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre locale.")

    resultat = _lancer(
        jeu, repertoire_path(), cv_path, tournures_path, banc_dir, [1], ["llama3"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "321 jeton(s) lus" in texte


def test_critere20_annexe_omet_les_jetons_pour_sonnet_sans_zero(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre Claude.")

    resultat = _lancer(
        jeu, repertoire_path(), cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "jeton(s) lus" not in texte


# --- ce qui ne doit pas arriver ----------------------------------------------


def test_le_texte_de_la_lettre_finale_n_est_jamais_modifie(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    lettre = "Je veux absolument ce poste, n'hésitez pas à me contacter."
    _programmer_passage_simple(modeles, lettre=lettre)

    resultat = _lancer(
        jeu, repertoire_path(), cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert lettre in texte


def test_graphe_de_la_boucle_inchange():
    mermaid = boucle.dessiner_graphe()
    assert "tamis" in mermaid
    assert "redaction" in mermaid
    assert "juge" in mermaid
    assert boucle.MAX_TOURS == 3
