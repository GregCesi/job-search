"""EXE-148 — le banc de la lettre : une commande passe les mêmes offres dans la
boucle (EXE-147) sous plusieurs configurations de modèles, et compare leurs
lettres, leur durée et leur coût sur une seule page et dans MLflow.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par
une doublure programmable (reprise de test_exe147_boucle_lettre.py). Aucun
test ne lit ni n'écrit sous data/ ou le mlflow.db du dépôt : la base, le
répertoire, le CV de référence, les tournures interdites et les rapports sont
posés dans tmp_path ; l'isolation MLflow est globale (conftest.py).
"""

import json
import sqlite3

import mlflow
import pytest
import yaml
from mlflow.tracking import MlflowClient

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import ReponseModele
from orchestrator.job_search.lettre.redaction import (
    RAISON_FICHE_NON_TERMINEE,
    RAISON_TEXTE_MANQUANT,
)
from orchestrator.job_search.storage.db import init_db

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


@pytest.fixture
def db_path(tmp_path):
    chemin = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(chemin)
    init_db(conn)
    conn.close()
    return chemin


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _points_fiche() -> list[dict]:
    return [
        {"position": "Point 0", "citation": "Citation 0", "url": "https://ex.test/0"}
    ]


def _poser_offre(
    conn,
    offer_id,
    *,
    retenue=True,
    fiche_terminee=True,
    texte="Texte de l'offre.",
    titre="Titre de l'offre",
    entreprise="Entreprise X SAS",
    employeur_nom="Entreprise X",
):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
        "description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, ?)",
        (offer_id, str(offer_id), titre, entreprise, texte),
    )
    if retenue:
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', '2026-10-07')",
            (offer_id,),
        )
    if fiche_terminee:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, ?, '2026-10-07')",
            (offer_id, json.dumps(_points_fiche()), employeur_nom),
        )
    conn.commit()


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
_JUGE_RIEN_A_REDIRE = json.dumps({"rien_a_redire": True, "remarques": None})


def _programmer_passage_simple(modeles, lettre="Lettre finale."):
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", lettre)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)


def _lancer(
    db_path,
    repertoire_path,
    cv_path,
    tournures_path,
    banc_dir,
    offer_ids,
    config_specs,
    tracker_factory=None,
):
    conn = _conn(db_path)
    try:
        kwargs = dict(
            repertoire_path=repertoire_path,
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
            banc_dir=banc_dir,
        )
        if tracker_factory is not None:
            kwargs["tracker_factory"] = tracker_factory
        return banc.lancer_banc(conn, offer_ids, config_specs, **kwargs)
    finally:
        conn.close()


# --- critère 1 : six passages pour 2 offres × 3 configurations -------------


def test_critere1_boucle_tourne_pour_chaque_offre_sous_chaque_configuration(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 179)
    _poser_offre(conn, 1677)
    conn.close()

    for _ in range(6):
        _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path,
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
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["llama3"]
    )

    appel = next(p for p in resultat.passages)
    assert {a.modele for a in appel.resultat.appels} == {"llama3"}


def test_critere3_juge_different_garde_tamis_et_redaction(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path,
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


# --- critères 4-7 : offres sautées -------------------------------------------


def test_critere4_offre_non_retenue_sautee_pour_toutes_les_configurations(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1, retenue=False)
    _poser_offre(conn, 2)
    conn.close()
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet", "opus"],
    )

    sautees = [p for p in resultat.passages if p.offer_id == 1]
    assert len(sautees) == 2
    for p in sautees:
        assert p.resultat is None
        assert p.skip_reason is not None
    autres = [p for p in resultat.passages if p.offer_id == 2]
    assert all(p.resultat is not None for p in autres)


def test_critere5_offre_sans_fiche_terminee_sautee(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1, fiche_terminee=False)
    conn.close()

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    passage = resultat.passages[0]
    assert passage.resultat is None
    assert passage.skip_reason == RAISON_FICHE_NON_TERMINEE


def test_critere6_offre_sans_texte_sautee(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1, texte="")
    conn.close()

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    passage = resultat.passages[0]
    assert passage.resultat is None
    assert passage.skip_reason == RAISON_TEXTE_MANQUANT


def test_critere7_numero_inconnu_sautee_les_autres_passent(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 2)
    conn.close()
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [999, 2],
        ["sonnet"],
    )

    inconnue = next(p for p in resultat.passages if p.offer_id == 999)
    assert inconnue.resultat is None
    assert inconnue.skip_reason is not None
    connue = next(p for p in resultat.passages if p.offer_id == 2)
    assert connue.resultat is not None


# --- critère 8 : répertoire absent ou mal formé -----------------------------


def test_critere8_repertoire_absent_le_banc_ne_part_pas(
    db_path, cv_path, tournures_path, banc_dir, tmp_path, modeles, capsys
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()

    code = banc.main(
        [
            "--offres",
            "1",
            "--config",
            "sonnet",
        ],
        repertoire_path=tmp_path / "absent.yaml",
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        db_path=db_path,
    )

    assert code == 1
    assert "introuvable" in capsys.readouterr().out
    assert modeles.appels == []


# --- critère 9 : ligne imprimée à la fin de chaque passage ------------------


def test_critere9_ligne_imprimee_par_passage(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles, capsys
):
    conn = _conn(db_path)
    _poser_offre(conn, 179)
    conn.close()
    _programmer_passage_simple(modeles, lettre="Lettre.")

    _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [179], ["sonnet"]
    )

    sortie = capsys.readouterr().out
    assert "sonnet" in sortie
    assert "179" in sortie
    assert "Entreprise X" in sortie
    assert "Le juge n'a rien à redire" in sortie


# --- critères 10-15 : le rapport ---------------------------------------------


def test_critere10_un_seul_rapport_horodate(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet", "opus"],
    )

    fichiers = list(banc_dir.glob("*.md"))
    assert len(fichiers) == 1
    assert resultat.rapport_path == fichiers[0]
    assert fichiers[0].name != "banc.md"  # le nom porte la date et l'heure


def test_critere11_tableau_de_comparaison(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles, lettre="Lettre.")

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "sonnet" in texte
    # Les 7 observables du critère 11.
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
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles, lettre="Lettre.")

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "prototyper" in texte
    assert "Citation 0" in texte


def test_critere13_lettre_finale_entiere_avec_tours_mots_duree_cout(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(
        modeles, lettre="Voici le texte complet de la lettre finale."
    )

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Voici le texte complet de la lettre finale." in texte
    passage = resultat.passages[0]
    assert str(passage.resultat.nb_tours) in texte
    assert str(passage.resultat.lettres[-1]["nb_mots"]) in texte


def test_critere14_annexe_lettres_intermediaires_et_duree_des_noeuds(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer(
        "juge",
        json.dumps({"rien_a_redire": False, "remarques": "trop long"}),
        _JUGE_RIEN_A_REDIRE,
    )

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Lettre 1." in texte
    assert "Lettre 2." in texte
    assert "trop long" in texte
    assert "tamis" in texte.lower()


def test_critere15_passage_sans_lettre_figure_avec_sa_raison(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    _poser_offre(conn, 2)
    conn.close()
    modeles.programmer("tamis", "ceci n'est pas du JSON")
    _programmer_passage_simple(modeles, lettre="Lettre OK.")

    resultat = _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet"],
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Le tamis a rendu une réponse que le code ne sait pas lire" in texte
    assert "Lettre OK." in texte
    passage_2 = next(p for p in resultat.passages if p.offer_id == 2)
    assert passage_2.resultat is not None


# --- critères 16-20 : MLflow --------------------------------------------------


def _config_param_names():
    return {
        "modele_tamis",
        "modele_redaction",
        "modele_juge",
        "plafond_tours",
        "offres",
    }


def test_critere16_un_run_mlflow_par_configuration_avec_ses_parametres(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 179)
    conn.close()
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    _lancer(
        db_path,
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
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    metrics = run.data.metrics
    assert metrics["lettres_produites"] == 1.0
    assert metrics["tours_moyen"] == 1.0
    assert metrics["plafonds_atteints"] == 0.0
    assert metrics["lettres_generiques"] == 0.0


def test_critere18_table_une_ligne_par_offre_avec_les_colonnes_attendues(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles, lettre="Lettre complète.")

    _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

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
    }
    ligne = dict(zip(table["columns"], table["data"][0]))
    assert ligne["offre"] == 1
    assert ligne["lettre_finale"] == "Lettre complète."


def test_critere19_memes_colonnes_et_memes_offres_entre_deux_runs(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    _poser_offre(conn, 2, retenue=False)
    conn.close()
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    _lancer(
        db_path,
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
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    artefacts = {a.path for a in client.list_artifacts(run.info.run_id)}
    assert resultat.rapport_path.name in artefacts


# --- critère 21 : MLflow ne peut pas écrire ----------------------------------


def test_critere21_mlflow_ne_peut_pas_ecrire_le_banc_va_au_bout(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles, capsys
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
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
        db_path,
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


# --- critères 22-23 : la base est intacte -------------------------------------


def test_critere22_meme_nombre_de_lignes_apres_le_banc(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    def _comptes(db_path):
        conn = sqlite3.connect(db_path)
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        comptes = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables
        }
        conn.close()
        return comptes

    avant = _comptes(db_path)
    _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )
    apres = _comptes(db_path)

    assert avant == apres


def test_critere23_lettre_enregistree_inchangee(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.execute(
        "INSERT INTO lettres (offer_id, statut, texte, created_at) "
        "VALUES (1, 'done', 'Lettre déjà enregistrée', '2026-10-01')"
    )
    conn.commit()
    conn.close()
    _programmer_passage_simple(modeles, lettre="Lettre du banc, jamais enregistrée.")

    _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    conn = sqlite3.connect(db_path)
    texte = conn.execute("SELECT texte FROM lettres WHERE offer_id=1").fetchone()[0]
    conn.close()
    assert texte == "Lettre déjà enregistrée"


# --- ce qui ne doit pas arriver ----------------------------------------------


def test_un_seul_rapport_pas_un_par_configuration(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    _lancer(
        db_path,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet", "opus"],
    )

    assert len(list(banc_dir.glob("*.md"))) == 1


def test_rapport_hors_git_dans_data_lettre_banc():
    from orchestrator.job_search.paths import LETTRE_BANC_REPORTS_DIR, REPO_ROOT

    assert LETTRE_BANC_REPORTS_DIR == REPO_ROOT / "data" / "lettre" / "banc"


def test_aucune_note_de_qualite_dans_le_rapport(
    db_path, repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        db_path, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8").lower()
    for mot_interdit in ["note sur 10", "score de qualité", "qualité :"]:
        assert mot_interdit not in texte
