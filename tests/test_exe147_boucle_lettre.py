"""EXE-147 — la boucle de la lettre (LangGraph) : un tamis choisit le fait et le texte
type, une rédaction écrit, un juge recruteur renvoie à la rédaction, trois lettres au
plus.

Aucun test n'appelle un modèle réel : `boucle.appeler_modele` est remplacé par une
doublure programmable, sauf dans la classe `TestDispatchModele` qui double directement
`claude_agent_sdk.query` et `ollama.Client` pour prouver le branchement sonnet/opus vs
llama3/gemma. Aucun test ne lit ni n'écrit sous data/ : la base, le répertoire, le CV
de référence et les tournures interdites sont posés dans tmp_path.
"""

import json
import sqlite3

import pytest
import yaml

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre.boucle import (
    Appel,
    ConfigBoucle,
    ReponseModele,
    generer_lettre_boucle,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\n"


# --- doublure des appels de modèle ---------------------------------------------


class FakeModeles:
    """File programmable par nœud : `programmer("tamis", valeur, valeur, ...)` pose
    les réponses rendues dans l'ordre des appels. Une valeur est soit un texte JSON
    (ou libre pour la rédaction), soit une exception à lever (critères 24-26)."""

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


# --- fixtures de terrain --------------------------------------------------------


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"sujet de {identifiant}",
        "conviction": f"conviction de {identifiant}",
        "ce_que_j_ai_fait": f"ce que j'ai fait pour {identifiant}",
        "s_applique_si": f"condition d'usage de {identifiant}",
        "texte": f"texte rédigé de {identifiant}",
        "exemples": [
            {
                "entreprise": "Entreprise avec texte",
                "fait": "fait notable",
                "citation": "citation notable",
                "url": "https://exemple.test/avec-texte",
                "texte": "exemple rédigé, à envoyer",
            },
            {
                "entreprise": "Entreprise sans texte",
                "fait": "fait jamais rédigé",
                "citation": "citation jamais rédigée",
                "url": "https://exemple.test/sans-texte",
                "texte": None,
            },
        ],
    }
    base.update(overrides)
    return base


def _repertoire_donnees(generique_texte: str | None = "texte générique rédigé") -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "quatre_temps": ["accroche", "preuve", "offre", "cta"],
            "regles": ["jamais de superlatif", "une phrase, une idée"],
            "formulations_rejetees": [
                {"texte": "passionné par l'IA", "motif": "trop vu, sonne creux"}
            ],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
            }
        ],
        "conditions_generales": ["lettre en français", "160 mots cible"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": "lettre envoyée à Entreprise X",
        },
        "textes_types": [
            _texte_type("prototyper"),
            _texte_type("generique", texte=generique_texte, exemples=[]),
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
        },
        {
            "position": "Point 1",
            "citation": "Citation 1",
            "url": "https://exemple.test/1",
        },
    ]


def _poser_offre_et_fiche(
    db_path, offer_id=1, points=None, employeur_nom="Entreprise X"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre de l''offre', 'Entreprise X SAS', "
            "'Texte de l''offre')",
            (offer_id, str(offer_id)),
        )
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, 'done', 'Présentation', ?, ?, '2026-10-07')",
            (
                offer_id,
                json.dumps(points if points is not None else _points_fiche()),
                employeur_nom,
            ),
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


_TAMIS_POINT_0_PROTOTYPER = json.dumps(
    {"point_index": 0, "texte_type_id": "prototyper"}
)
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
    # EXE-158 : `texte` vit dans la rubrique « détails », celle qui porte
    # historiquement les remarques du juge dans ces tests.
    return json.dumps(
        {
            "rien_a_redire": False,
            "ressenti": "Ressenti mitigé.",
            "details": texte,
            "reussites": "Une accroche correcte.",
            "verdict": "À revoir.",
        }
    )


# --- critères 1-3 : ce que reçoit le tamis --------------------------------------


def test_critere1_tamis_recoit_intitule_texte_et_points_fiche(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_tamis = modeles.appels[0][2]
    assert "Titre de l'offre" in demande_tamis
    assert "Texte de l'offre" in demande_tamis
    assert "Point 0" in demande_tamis and "Citation 0" in demande_tamis
    assert "https://exemple.test/0" in demande_tamis


def test_critere2_tamis_recoit_textes_types_et_conditions_usage(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_tamis = modeles.appels[0][2]
    assert "prototyper" in demande_tamis
    assert "condition d'usage de prototyper" in demande_tamis


def test_critere3_tamis_recoit_sujets_interdits_conditions_bonne_accroche(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_tamis = modeles.appels[0][2]
    assert "Claude / Anthropic" in demande_tamis
    assert "lettre en français" in demande_tamis
    assert "un fait précis de l'entreprise" in demande_tamis


# --- critères 4-9 : résolution du choix du tamis --------------------------------


def test_critere4_point_et_texte_type_valides_transmis_a_la_redaction(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "Citation 0" in demande_redaction
    assert "conviction de prototyper" in demande_redaction
    assert resultat.texte_type_id == "prototyper"
    assert resultat.fait_retenu["citation"] == "Citation 0"


def test_critere5_point_hors_fiche_traite_comme_generique(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer(
        "tamis", json.dumps({"point_index": 99, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.texte_type_id == "generique"
    assert resultat.fait_retenu == "generique"
    demande_redaction = modeles.appels[1][2]
    assert "Aucun fait d'entreprise retenu" in demande_redaction


def test_critere6_texte_type_hors_repertoire_traite_comme_generique(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "inconnu"})
    )
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.texte_type_id == "generique"
    assert resultat.fait_retenu == "generique"


def test_critere7_generique_rend_texte_type_generique_sans_fait(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    # Critère 11 : conviction/ce que j'ai fait du texte type choisi (ici « generique »),
    # jamais son champ `texte` brut — ce dernier n'est qu'une porte de disponibilité
    # (critère 8), pas un contenu envoyé à la rédaction.
    assert "conviction de generique" in demande_redaction
    assert "ce que j'ai fait pour generique" in demande_redaction
    assert "Citation 0" not in demande_redaction
    assert "Citation 1" not in demande_redaction
    assert "Aucun fait d'entreprise retenu" in demande_redaction


def test_critere8_texte_generique_manquant_arrete_sans_lettre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_GENERIQUE)

    resultat = _lancer(
        db_path, lambda: repertoire_path(generique_texte=None), cv_path, tournures_path
    )

    assert (
        resultat.raison_fin == "Le texte générique n'est pas écrit dans le répertoire"
    )
    assert resultat.lettres == []


def test_critere9_generique_manquant_aucune_redaction_appelee(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    # Aucune réponse programmée pour "redaction" : si le nœud était appelé, la file
    # vide lèverait IndexError et le test échouerait.

    _lancer(
        db_path, lambda: repertoire_path(generique_texte=None), cv_path, tournures_path
    )

    assert modeles.files["redaction"] == []
    assert not any(noeud == "redaction" for noeud, _, _ in modeles.appels)


# --- critères 10-13 : ce que reçoivent la rédaction et le juge -----------------


def test_critere10_redaction_recoit_posture_forme_intitule_entreprise_cv(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "ingénieur qui prototype vite" in demande_redaction
    assert "jamais de superlatif" in demande_redaction
    assert "passionné par l'IA" in demande_redaction
    assert "accroche, preuve, offre, cta" in demande_redaction
    assert "lettre envoyée à Entreprise X" in demande_redaction
    assert "Titre de l'offre" in demande_redaction
    assert "Entreprise X" in demande_redaction
    assert "Contenu CV de test" in demande_redaction


def test_critere11_redaction_recoit_conviction_cqjf_et_exemples_avec_texte_seulement(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    assert "conviction de prototyper" in demande_redaction
    assert "ce que j'ai fait pour prototyper" in demande_redaction
    assert "exemple rédigé, à envoyer" in demande_redaction
    assert "Entreprise avec texte" in demande_redaction
    # Critère 11 + interdit « exemple sans texte envoyé » : l'exemple sans texte
    # (Entreprise sans texte) n'apparaît jamais dans la demande.
    assert "Entreprise sans texte" not in demande_redaction
    assert "fait jamais rédigé" not in demande_redaction


def test_critere12_redaction_ne_recoit_aucun_autre_texte_type(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre générique.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_redaction = modeles.appels[1][2]
    # "prototyper" n'est pas le texte type choisi (générique l'est) : son contenu ne
    # doit pas fuiter dans la demande de rédaction.
    assert "conviction de prototyper" not in demande_redaction
    assert "ce que j'ai fait pour prototyper" not in demande_redaction


def test_critere13_juge_recoit_lettre_intitule_entreprise_consigne_et_contexte(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    # Modifié pour EXE-158 (critères 1-4) : le juge ne reçoit plus mes règles de
    # posture ni mes formulations rejetées — seulement la lettre, l'offre, et le
    # répertoire du juge.
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Voici le texte complet de ma lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    demande_juge = modeles.appels[2][2]
    assert "Voici le texte complet de ma lettre." in demande_juge
    assert "Titre de l'offre" in demande_juge
    assert "Entreprise X" in demande_juge
    assert "Consigne du juge." in demande_juge
    assert "Contexte du juge." in demande_juge
    assert "jamais de superlatif" not in demande_juge
    assert "passionné par l'IA" not in demande_juge


# --- critères 14-16 : la boucle du juge -----------------------------------------


def test_critere14_rien_a_redire_termine_en_un_tour(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 1
    assert len(resultat.lettres) == 1
    assert resultat.lettres[0]["texte"] == "Lettre 1."
    assert resultat.raison_fin == "Le juge n'a rien à redire"


def test_critere15_remarques_relancent_la_redaction_avec_lettre_et_remarques(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer("juge", _juge_remarques("trop long"), _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 2
    assert [lettre["texte"] for lettre in resultat.lettres] == [
        "Lettre 1.",
        "Lettre 2.",
    ]
    assert resultat.lettres[0]["jugement"].details == "trop long"
    demande_redaction_2 = modeles.appels[3][2]
    assert "Lettre 1." in demande_redaction_2
    assert "trop long" in demande_redaction_2


def test_critere16_plafond_de_trois_tours(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.", "Lettre 3.")
    modeles.programmer(
        "juge",
        _juge_remarques("remarque 1"),
        _juge_remarques("remarque 2"),
        _juge_remarques("remarque 3"),
    )

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 3
    assert len(resultat.lettres) == 3
    assert resultat.lettres[-1]["texte"] == "Lettre 3."
    assert resultat.lettres[-1]["jugement"].details == "remarque 3"
    assert resultat.raison_fin == "Le plafond de tours est atteint"
    # Pas de quatrième rédaction après le plafond.
    assert len(modeles.files["redaction"]) == 0
    assert sum(1 for n, _, _ in modeles.appels if n == "redaction") == 3


# --- critères 17-20 : ce que rend la boucle -------------------------------------


def test_critere17_fait_retenu_et_texte_type_choisi(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert resultat.fait_retenu == {
        "position": "Point 0",
        "citation": "Citation 0",
        "url": "https://exemple.test/0",
    }
    assert resultat.texte_type_id == "prototyper"


def test_critere18_lettres_dans_l_ordre_avec_remarques_tours_et_raison(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre 1.", "Lettre 2.")
    modeles.programmer("juge", _juge_remarques("à revoir"), _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert [lettre["texte"] for lettre in resultat.lettres] == [
        "Lettre 1.",
        "Lettre 2.",
    ]
    assert resultat.lettres[0]["jugement"].details == "à revoir"
    assert resultat.lettres[1]["jugement"].rien_a_redire is True
    assert resultat.nb_tours == 2
    assert resultat.raison_fin == "Le juge n'a rien à redire"


def test_critere19_derniere_lettre_nb_mots_et_tournures(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    # EXE-160 : une tournure interdite déclenche une correction du vérificateur —
    # le second jet (ici identique) est ce qui reste la lettre finale.
    modeles.programmer(
        "redaction",
        "Je veux vous rejoindre avec enthousiasme total.",
        "Je veux vous rejoindre avec enthousiasme total.",
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    derniere = resultat.lettres[-1]
    assert derniere["nb_mots"] == 7
    assert derniere["tournures_signalees"] == ["Je veux"]


def test_critere20_journal_des_appels_porte_noeud_modele_duree_cout_demande_reponse(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    # EXE-160 : le vérificateur s'intercale entre la rédaction et le juge.
    assert [a.noeud for a in resultat.appels] == [
        "tamis",
        "redaction",
        "verificateur",
        "juge",
    ]
    for appel in resultat.appels:
        assert isinstance(appel, Appel)
        assert appel.modele == "sonnet"
        assert appel.duree_s >= 0
        assert appel.cout_usd == 0.01
        assert appel.demande
        assert appel.reponse


# --- critères 21-23 : un modèle par nœud, dispatch sonnet/opus vs llama/gemma ---


def test_critere21_un_modele_different_par_noeud(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    config = ConfigBoucle(
        modele_tamis="llama3", modele_redaction="sonnet", modele_juge="opus"
    )
    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path, config=config)

    modeles_par_noeud = {a.noeud: a.modele for a in resultat.appels}
    # EXE-160 : sans `verif=`, le vérificateur tourne sur le modèle de la rédaction.
    assert modeles_par_noeud == {
        "tamis": "llama3",
        "redaction": "sonnet",
        "verificateur": "sonnet",
        "juge": "opus",
    }


class TestDispatchModele:
    """Critères 22-23 : le dispatch réel (pas la doublure `appeler_modele`), en
    doublant `claude_agent_sdk.query` et `ollama.Client` eux-mêmes."""

    def test_critere22_sonnet_et_opus_partent_par_le_claude_agent_sdk(
        self, monkeypatch
    ):
        from claude_agent_sdk import ResultMessage

        appels_sdk = []

        def fake_query(*, prompt, options):
            appels_sdk.append((prompt, options))

            async def _gen():
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="s",
                    total_cost_usd=0.03,
                    result='{"rien_a_redire": true, "remarques": null}',
                    structured_output=None,
                )

            return _gen()

        monkeypatch.setattr(boucle, "query", fake_query)

        reponse = boucle.appeler_modele(
            "juge", "sonnet", "demande", schema={"type": "object"}
        )

        assert len(appels_sdk) == 1
        assert appels_sdk[0][1].model == "sonnet"
        assert appels_sdk[0][1].cwd == str(boucle.BOUCLE_JUGE_CWD)
        assert reponse.cout_usd == 0.03

    def test_critere23_llama3_et_gemma_partent_par_ollama(self, monkeypatch):
        appels_ollama = []

        class FakeMessage:
            content = '{"rien_a_redire": true, "remarques": null}'

        class FakeResponse:
            message = FakeMessage()

        class FakeClient:
            def __init__(self, host=None, timeout=None):
                appels_ollama.append((host, timeout))

            def chat(self, **kwargs):
                appels_ollama.append(kwargs)
                return FakeResponse()

        monkeypatch.setattr(boucle.ollama, "Client", FakeClient)

        reponse = boucle.appeler_modele(
            "juge", "llama3", "demande", schema={"type": "object"}
        )

        assert any(
            kw.get("model") == "llama3" for kw in appels_ollama if isinstance(kw, dict)
        )
        assert reponse.cout_usd is None

        appels_ollama.clear()
        boucle.appeler_modele("tamis", "gemma4:12b", "demande")
        assert any(
            kw.get("model") == "gemma4:12b"
            for kw in appels_ollama
            if isinstance(kw, dict)
        )


# --- critères 24-26 : réponses illisibles, échecs, délais dépassés -------------


def test_critere24_tamis_illisible_arrete_sans_lettre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", "ceci n'est pas du JSON")

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert (
        resultat.raison_fin
        == "Le tamis a rendu une réponse que le code ne sait pas lire"
    )
    assert resultat.lettres == []


def test_critere25_juge_illisible_arrete_avec_la_derniere_lettre(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer("juge", "ceci n'est pas du JSON")

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert (
        resultat.raison_fin
        == "Le juge a rendu une réponse que le code ne sait pas lire"
    )
    assert len(resultat.lettres) == 1
    assert resultat.lettres[0]["texte"] == "Lettre 1."


@pytest.mark.parametrize("noeud", ["tamis", "redaction", "juge"])
def test_critere26_appel_echoue_arrete_en_nommant_le_noeud(
    db_path, repertoire_path, cv_path, tournures_path, modeles, noeud
):
    _poser_offre_et_fiche(db_path)
    if noeud != "tamis":
        modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    if noeud == "juge":
        modeles.programmer("redaction", "Lettre 1.")
    modeles.programmer(noeud, boucle.AppelModeleError("a dépassé son délai"))

    resultat = _lancer(db_path, repertoire_path, cv_path, tournures_path)

    assert noeud in resultat.raison_fin
    assert "a dépassé son délai" in resultat.raison_fin


# --- critère 27 : dessin du graphe ----------------------------------------------


def test_critere27_dessin_du_graphe_montre_les_trois_noeuds_et_le_retour_du_juge():
    mermaid = boucle.dessiner_graphe()

    assert "tamis" in mermaid
    assert "redaction" in mermaid
    assert "juge" in mermaid
    assert "juge -.-> redaction" in mermaid


# --- ce qui ne doit pas arriver --------------------------------------------------


def test_la_boucle_n_ecrit_dans_aucune_table(
    db_path, repertoire_path, cv_path, tournures_path, modeles
):
    _poser_offre_et_fiche(db_path)
    modeles.programmer("tamis", _TAMIS_POINT_0_PROTOTYPER)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(db_path, repertoire_path, cv_path, tournures_path)

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM lettres").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM offers").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM fiches_entreprise").fetchone()[0] == 1
    finally:
        conn.close()


def test_redaction_et_juge_ont_des_cwd_distincts():
    assert boucle.BOUCLE_REDACTION_CWD != boucle.BOUCLE_JUGE_CWD
    assert boucle.BOUCLE_TAMIS_CWD != boucle.BOUCLE_REDACTION_CWD
