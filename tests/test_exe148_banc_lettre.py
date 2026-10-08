"""EXE-148 — le banc de la lettre : une commande passe les offres d'un jeu
d'évaluation figé dans la boucle (EXE-147) sous plusieurs configurations de
modèles, et compare leurs lettres, leur durée et leur coût sur une seule page
et dans MLflow.

Réécrit pour EXE-151 : le banc ne résout plus ses offres depuis la base
(`offers`, `verdicts`, `fiches_entreprise`) mais depuis un jeu déjà préparé
(dict en mémoire dans ces tests) — voir test_exe151_jeu_banc_lettre.py pour
les critères propres au jeu et à cette frontière.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé
par une doublure programmable (reprise de test_exe147_boucle_lettre.py).
Aucun test ne lit ni n'écrit sous data/ ou le mlflow.db du dépôt : le
répertoire, le CV de référence, les tournures interdites et les rapports
sont posés dans tmp_path ; l'isolation MLflow est globale (conftest.py).
"""

import json

import mlflow
import pytest
import yaml
from mlflow.tracking import MlflowClient

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import ReponseModele

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (reprise de test_exe147_boucle_lettre.py) ---


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
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=cout)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


# --- fixtures de terrain ---------------------------------------------------


def _repertoire_donnees() -> dict:
    return {
        "version": 1,
        "posture": {"role": "ingénieur", "regles": ["jamais de superlatif"]},
        "forme": {"longueur_cible_mots": 160},
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


@pytest.fixture
def banc_dir(tmp_path):
    return tmp_path / "banc"


def _entree_jeu(
    offer_id,
    *,
    titre="Titre de l'offre",
    entreprise="Entreprise X",
    texte="Texte de l'offre.",
    faits=None,
):
    return {
        "offer_id": offer_id,
        "intitule": titre,
        "entreprise": entreprise,
        "texte_offre": texte,
        "faits": faits
        if faits is not None
        else [
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


def _jeu(*offer_ids, **kwargs) -> dict:
    return {
        "nom": "essai",
        "prepare_le": "2026-10-07T00:00:00Z",
        "offres": [_entree_jeu(i, **kwargs) for i in offer_ids],
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
    jeu,
    repertoire_path,
    cv_path,
    tournures_path,
    banc_dir,
    offer_ids,
    config_specs,
    tracker_factory=None,
):
    kwargs = dict(
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
    )
    if tracker_factory is not None:
        kwargs["tracker_factory"] = tracker_factory
    return banc.lancer_banc(jeu, offer_ids, config_specs, **kwargs)


# --- critère 1 : six passages pour 2 offres × 3 configurations -------------


def test_critere1_boucle_tourne_pour_chaque_offre_sous_chaque_configuration(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(179, 1677)
    for _ in range(6):
        _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [179, 1677],
        ["sonnet", "opus", "sonnet,juge=opus"],
    )

    assert len(resultat.passages) == 6
    assert {(p.config_label, p.offer_id) for p in resultat.passages} == {
        ("sonnet", 179),
        ("sonnet", 1677),
        ("opus", 179),
        ("opus", 1677),
        ("sonnet,juge=opus", 179),
        ("sonnet,juge=opus", 1677),
    }


# --- critères 2-3 : parsing des configurations ------------------------------


def test_critere2_configuration_a_un_seul_modele(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["llama3"]
    )

    appel = next(p for p in resultat.passages)
    assert {a.modele for a in appel.resultat.appels} == {"llama3"}


def test_critere3_juge_different_garde_tamis_et_redaction(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet,juge=opus"],
    )

    passage = resultat.passages[0]
    modeles_par_noeud = {a.noeud: a.modele for a in passage.resultat.appels}
    assert modeles_par_noeud == {
        "tamis": "sonnet",
        "redaction": "sonnet",
        "juge": "opus",
    }


# --- critère 8 (devenu « répertoire absent ») -------------------------------


def test_critere8_repertoire_absent_le_banc_ne_part_pas(
    cv_path, tournures_path, banc_dir, tmp_path, modeles, capsys
):
    jeux_dir = tmp_path / "jeux"
    jeux_dir.mkdir()
    (jeux_dir / "essai.json").write_text(json.dumps(_jeu(1)), encoding="utf-8")

    code = banc.main(
        ["--jeu", "essai", "--config", "sonnet"],
        repertoire_path=tmp_path / "absent.yaml",
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeux_dir=jeux_dir,
    )

    assert code == 1
    assert "introuvable" in capsys.readouterr().out
    assert modeles.appels == []


# --- critère 9 : ligne imprimée à la fin de chaque passage ------------------


def test_critere9_ligne_imprimee_par_passage(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles, capsys
):
    jeu = _jeu(179)
    _programmer_passage_simple(modeles, lettre="Lettre.")

    _lancer(jeu, repertoire_path, cv_path, tournures_path, banc_dir, [179], ["sonnet"])

    sortie = capsys.readouterr().out
    assert "sonnet" in sortie
    assert "179" in sortie
    assert "Entreprise X" in sortie
    assert "Le juge n'a rien à redire" in sortie


# --- critères 10-15 : le rapport ---------------------------------------------


def test_critere10_un_seul_rapport_horodate(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet", "opus"]
    )

    fichiers = list(banc_dir.glob("*.md"))
    assert len(fichiers) == 1
    assert resultat.rapport_path == fichiers[0]
    assert fichiers[0].name != "banc.md"  # le nom porte la date et l'heure


def test_critere11_tableau_de_comparaison(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre.")

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "sonnet" in texte
    for mot in [
        "lettres produites",
        "durée totale",
        "durée moyenne",
        "coût total",
        "tours",
        "plafonds atteints",
        "génériques",
    ]:
        assert mot.split()[0].lower() in texte.lower()


def test_critere12_offre_par_offre_fait_retenu_et_texte_type(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre.")

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "prototyper" in texte
    assert "Citation 0" in texte


def test_critere13_lettre_finale_entiere_avec_tours_mots_duree_cout(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(
        modeles, lettre="Voici le texte complet de la lettre finale."
    )

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Voici le texte complet de la lettre finale." in texte
    passage = resultat.passages[0]
    assert str(passage.resultat.nb_tours) in texte
    assert str(passage.resultat.lettres[-1]["nb_mots"]) in texte


def test_critere14_annexe_lettres_intermediaires_et_duree_des_noeuds(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer(
        "juge",
        json.dumps(
            {
                "rien_a_redire": False,
                "ressenti": "Ressenti mitigé.",
                "details": "trop long",
                "reussites": "Une accroche correcte.",
                "verdict": "À revoir.",
            }
        ),
        _JUGE_RIEN_A_REDIRE,
    )

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Lettre 1." in texte
    assert "Lettre 2." in texte
    assert "trop long" in texte
    assert "tamis" in texte.lower()


def test_critere15_passage_sans_lettre_figure_avec_sa_raison(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    modeles.programmer("tamis", "ceci n'est pas du JSON")
    _programmer_passage_simple(modeles, lettre="Lettre OK.")

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1, 2], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Le tamis a rendu une réponse que le code ne sait pas lire" in texte
    assert "Lettre OK." in texte
    passage_2 = next(p for p in resultat.passages if p.offer_id == 2)
    assert passage_2.resultat is not None


# --- critères 16-20 : MLflow --------------------------------------------------


def test_critere16_un_run_mlflow_par_configuration_avec_ses_parametres(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(179)
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    _lancer(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [179],
        ["sonnet", "sonnet,juge=opus"],
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])
    assert len(runs) == 2
    noms = {r.info.run_name for r in runs}
    assert noms == {"sonnet", "sonnet,juge=opus"}

    run_juge_opus = next(r for r in runs if r.info.run_name == "sonnet,juge=opus")
    params = run_juge_opus.data.params
    assert params["modele_tamis"] == "sonnet"
    assert params["modele_redaction"] == "sonnet"
    assert params["modele_juge"] == "opus"
    assert params["plafond_tours"] == str(boucle.MAX_TOURS)
    assert params["offres"] == "179"


def test_critere17_metriques_du_run_reprennent_la_ligne_du_tableau(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    _lancer(jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"])

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    metrics = run.data.metrics
    assert metrics["lettres_produites"] == 1.0
    assert metrics["tours_moyen"] == 1.0
    assert metrics["plafonds_atteints"] == 0.0
    assert metrics["lettres_generiques"] == 0.0


def test_critere18_table_une_ligne_par_offre_avec_les_colonnes_attendues(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles, lettre="Lettre complète.")

    _lancer(jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"])

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    path = mlflow.artifacts.download_artifacts(
        run_id=run.info.run_id, artifact_path="passages.json"
    )
    table = json.loads(open(path, encoding="utf-8").read())
    colonnes = set(table["columns"])
    assert colonnes == {
        "offre",
        "entreprise",
        "intitule",
        "fait_retenu",
        "texte_type",
        "lettre_finale",
        "tours",
        "mots",
        "duree_s",
        "cout_usd",
        "raison_fin",
        # EXE-152, critère 17 : tournures interdites et écart de longueur de
        # la lettre finale, ajoutés à la table du run MLflow.
        "tournures_lettre_finale",
        "ecart_mots",
        # EXE-158, critère 18 : le verdict du juge sur la lettre finale.
        "verdict_juge_lettre_finale",
    }
    ligne = dict(zip(table["columns"], table["data"][0]))
    assert ligne["offre"] == 1
    assert ligne["lettre_finale"] == "Lettre complète."


def test_critere19_memes_colonnes_et_memes_offres_entre_deux_runs(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    for _ in range(4):
        _programmer_passage_simple(modeles)

    _lancer(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet", "opus"],
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    runs = client.search_runs([experiment.experiment_id])
    tables = []
    for run in runs:
        path = mlflow.artifacts.download_artifacts(
            run_id=run.info.run_id, artifact_path="passages.json"
        )
        tables.append(json.loads(open(path, encoding="utf-8").read()))

    assert tables[0]["columns"] == tables[1]["columns"]
    offres_0 = [
        dict(zip(tables[0]["columns"], ligne))["offre"] for ligne in tables[0]["data"]
    ]
    offres_1 = [
        dict(zip(tables[1]["columns"], ligne))["offre"] for ligne in tables[1]["data"]
    ]
    assert offres_0 == offres_1 == [1, 2]


def test_critere20_le_run_porte_en_piece_le_rapport(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    artefacts = {a.path for a in client.list_artifacts(run.info.run_id)}
    assert resultat.rapport_path.name in artefacts


# --- critère 21 : MLflow ne peut pas écrire ----------------------------------


def test_critere21_mlflow_ne_peut_pas_ecrire_le_banc_va_au_bout(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles, capsys
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    class _TrackerEnPanne:
        def __init__(self, experiment_name):
            self.active = False

        def start(self, params, run_name=None):
            print("[run] suivi MLflow a échoué au démarrage : stockage verrouillé")

        def log_metrics(self, metrics):
            pass

        def log_table(self, data, artifact_file):
            pass

        def log_artifact(self, path):
            pass

        def end(self):
            pass

    resultat = _lancer(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet"],
        tracker_factory=_TrackerEnPanne,
    )

    assert resultat.rapport_path.exists()
    assert "suivi MLflow a échoué" in capsys.readouterr().out


# --- ce qui ne doit pas arriver ----------------------------------------------


def test_un_seul_rapport_pas_un_par_configuration(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet", "opus"]
    )

    assert len(list(banc_dir.glob("*.md"))) == 1


def test_rapport_hors_git_dans_data_lettre_banc():
    from orchestrator.job_search.paths import LETTRE_BANC_REPORTS_DIR, REPO_ROOT

    assert LETTRE_BANC_REPORTS_DIR == REPO_ROOT / "data" / "lettre" / "banc"


def test_jeux_sous_le_dossier_du_banc():
    from orchestrator.job_search.paths import (
        LETTRE_BANC_JEUX_DIR,
        LETTRE_BANC_REPORTS_DIR,
    )

    assert LETTRE_BANC_JEUX_DIR == LETTRE_BANC_REPORTS_DIR / "jeux"


def test_aucune_note_de_qualite_dans_le_rapport(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8").lower()
    for mot_interdit in ["note sur 10", "score de qualité", "qualité :"]:
        assert mot_interdit not in texte
