"""EXE-155 — la rédaction de la lettre lit l'annonce, et le banc peut demander la
lettre générique d'une offre.

Partie A (critères 1-4) : la rédaction reçoit le texte intégral de l'annonce, sans
bloc de style/script ni balise, à chaque tour — pas seulement quand le tamis a
choisi la lettre générique.

Partie B (critères 5-11) : la configuration du banc « tamis=generique » n'appelle
aucun modèle pour le tamis — elle résout directement le texte type générique.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par une
doublure programmable (reprise de test_exe147_boucle_lettre.py et
test_exe148_banc_lettre.py). Aucun test ne lit ni n'écrit sous data/ ou le
mlflow.db du dépôt : répertoire, CV de référence, tournures interdites et rapports
sont posés dans tmp_path ; l'isolation MLflow est globale (conftest.py).
"""

import json
import sqlite3

import pytest
import yaml
from mlflow.tracking import MlflowClient

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.banc import (
    ConfigurationInvalideError,
    parser_config,
)
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_boucle,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublure des appels de modèle (reprise des tests EXE-147/EXE-148) --------


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
        cout = 0.01 if modele in boucle.MODELES_CLAUDE else None
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=cout)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


# --- fixtures de terrain --------------------------------------------------------


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"sujet de {identifiant}",
        "conviction": f"conviction de {identifiant}",
        "ce_que_j_ai_fait": f"ce que j'ai fait pour {identifiant}",
        "texte": f"texte générique rédigé de {identifiant}",
        "exemples": [],
    }
    base.update(overrides)
    return base


def _repertoire_donnees(generique_texte: str | None = "texte générique rédigé") -> dict:
    return {
        "version": 1,
        "posture": {"role": "ingénieur", "regles": ["jamais de superlatif"]},
        "forme": {"longueur_cible_mots": 160},
        "textes_types": [
            _texte_type("prototyper"),
            _texte_type("generique", texte=generique_texte),
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


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(generique_texte="texte générique rédigé"):
        chemin = tmp_path / "repertoire.yaml"
        donnees = _repertoire_donnees(generique_texte)
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
            "citation": "Citation 0",
            "url": "https://exemple.test/0",
        }
    ]


def _poser_offre_et_fiche(db_path, offer_id=1, texte_offre="Texte de l'offre."):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre de l''offre', "
            "'Entreprise X SAS', ?)",
            (offer_id, str(offer_id), texte_offre),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, "
            "'Entreprise X', '2026-10-07')",
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
            config
            or ConfigBoucle(
                modele_tamis="sonnet", modele_redaction="sonnet", modele_juge="sonnet"
            ),
            repertoire_path=repertoire_path(),
            cv_reference_path=cv_path,
            tournures_path=tournures_path,
        )
    finally:
        conn.close()


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
_TAMIS_GENERIQUE = json.dumps({"point_index": None, "texte_type_id": "generique"})
_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
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
        }
    )


# =================================================================================
# Partie A — critères 1-4 : la rédaction reçoit le texte de l'annonce
# =================================================================================


def test_critere1_tamis_generique_redaction_recoit_l_annonce_entiere(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path, texte_offre="Nous cherchons un développeur Python.")
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Nous cherchons un développeur Python." in demande_redaction


def test_critere2_tamis_a_retenu_un_fait_redaction_recoit_aussi_l_annonce_entiere(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path, texte_offre="Nous cherchons un développeur Python.")
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Nous cherchons un développeur Python." in demande_redaction
    # Toujours accompagnée du fait retenu — le texte de l'annonce s'ajoute, il ne
    # le remplace pas.
    assert "Citation 0" in demande_redaction


def test_critere3_bloc_de_style_et_balises_retires_de_ce_que_recoit_la_redaction(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    texte_offre = (
        "<style>body{color:red}</style>"
        "<p>Nous cherchons un <b>développeur</b> Python.</p>"
        "<script>alert('x')</script>"
    )
    _poser_offre_et_fiche(db_path, texte_offre=texte_offre)
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Nous cherchons un" in demande_redaction
    assert "développeur" in demande_redaction
    assert "color:red" not in demande_redaction
    assert "alert" not in demande_redaction
    assert "<" not in demande_redaction
    assert ">" not in demande_redaction


def test_critere4_deuxieme_et_troisieme_tour_recoivent_encore_l_annonce(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path, texte_offre="Nous cherchons un développeur Python.")
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge_remarques("remarque 1"),
        _juge_remarques("remarque 2"),
        _JUGE_RIEN_A_REDIRE,
    )

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    appels_redaction = [a for a in modeles.appels if a[0] == "redaction"]
    assert len(appels_redaction) == 3
    for _, _, demande in appels_redaction:
        assert "Nous cherchons un développeur Python." in demande


# =================================================================================
# Partie B — critères 5-11 : le banc peut demander la lettre générique
# =================================================================================


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


@pytest.fixture
def banc_dir(tmp_path):
    return tmp_path / "banc"


def _lancer_banc(
    jeu, repertoire_path, cv_path, tournures_path, banc_dir, offer_ids, config_specs
):
    return banc.lancer_banc(
        jeu,
        offer_ids,
        config_specs,
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
    )


def test_critere5_tamis_generique_aucun_modele_appele_pour_le_tamis(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    # Aucune réponse programmée pour "tamis" : si le nœud appelait un modèle, la
    # file vide lèverait IndexError et le test échouerait.
    modeles.programmer("redaction", "Lettre générique 1.", "Lettre générique 2.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE, _JUGE_RIEN_A_REDIRE)

    _lancer_banc(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet,tamis=generique"],
    )

    assert modeles.files["tamis"] == []
    assert not any(noeud == "tamis" for noeud, _, _ in modeles.appels)


def test_critere6_redaction_recoit_le_texte_generique_et_aucun_fait(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    modeles.programmer("redaction", "Lettre générique 1.", "Lettre générique 2.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE, _JUGE_RIEN_A_REDIRE)

    _lancer_banc(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet,tamis=generique"],
    )

    appels_redaction = [a for a in modeles.appels if a[0] == "redaction"]
    assert len(appels_redaction) == 2
    for _, _, demande in appels_redaction:
        assert "texte générique rédigé" in demande
        assert "Aucun fait d'entreprise retenu" in demande
        assert "Citation 0" not in demande


def test_critere7_rapport_montre_generique_et_aucun_fait_retenu_par_offre(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1, 2)
    modeles.programmer("redaction", "Lettre générique 1.", "Lettre générique 2.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE, _JUGE_RIEN_A_REDIRE)

    resultat = _lancer_banc(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1, 2],
        ["sonnet,tamis=generique"],
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert texte.count("texte type « generique »") == 2
    assert texte.count("(aucun — générique)") == 2


def test_critere8_repertoire_sans_generique_arrete_sans_appeler_la_redaction(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    # Aucune réponse programmée pour "redaction" : si le nœud était appelé, la
    # file vide lèverait IndexError et le test échouerait.

    resultat = _lancer_banc(
        jeu,
        lambda: repertoire_path(generique_texte=None),
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet,tamis=generique"],
    )

    assert modeles.files["redaction"] == []
    assert not any(noeud == "redaction" for noeud, _, _ in modeles.appels)
    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Le texte générique n'est pas écrit dans le répertoire" in texte


def test_critere9_run_mlflow_porte_generique_comme_modele_du_tamis(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer_banc(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet,tamis=generique"],
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert run.info.run_name == "sonnet,tamis=generique"
    assert run.data.params["modele_tamis"] == "generique"
    assert run.data.params["modele_redaction"] == "sonnet"
    assert run.data.params["modele_juge"] == "sonnet"


def test_critere10_annexe_du_rapport_ne_liste_aucun_appel_de_tamis(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer_banc(
        jeu,
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        [1],
        ["sonnet,tamis=generique"],
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    annexe = texte.split("## Annexe")[1]
    assert "- tamis (" not in annexe


def test_critere11_configuration_sans_tamis_generique_appelle_toujours_le_tamis(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(1)
    modeles.programmer("tamis", _TAMIS_POINT_0)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer_banc(
        jeu, repertoire_path, cv_path, tournures_path, banc_dir, [1], ["sonnet"]
    )

    assert any(noeud == "tamis" for noeud, _, _ in modeles.appels)
    assert modeles.files["tamis"] == []


# --- H2 : « generique » n'est valable que pour le rôle tamis -------------------


@pytest.mark.parametrize(
    "spec", ["sonnet,redaction=generique", "sonnet,juge=generique", "generique"]
)
def test_generique_refuse_hors_du_role_tamis(spec):
    with pytest.raises(ConfigurationInvalideError):
        parser_config(spec)
