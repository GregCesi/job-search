"""EXE-146 — le répertoire de la lettre (data/lettre/repertoire.yaml, hors git) est
lu par le code, et un répertoire mal formé est refusé avec sa raison.

Tous les fichiers de ces tests sont posés dans tmp_path (critère 17) : aucune
lecture ni écriture sous data/, aucun appel de modèle.
"""

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

from orchestrator.job_search.lettre.repertoire import (
    RepertoireError,
    charger_repertoire,
)
from orchestrator.job_search.lettre.repertoire import (
    main as controle_main,
)

IDS_TEXTES_TYPES = [
    "mesurer_avant_de_corriger",
    "tester_les_agents_automatiquement",
    "systeme_d_evaluation",
    "prototyper",
    "l_ia_ecrit_l_ingenieur_valide",
    "regle_ou_modele",
    "ecosysteme_claude",
    "generique",
]


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"sujet de {identifiant}",
        "etat": "pret",
        "conviction": f"conviction de {identifiant}",
        "ce_que_j_ai_fait": f"ce que j'ai fait pour {identifiant}",
        "s_applique_si": "l'offre parle de tests",
        "ne_s_applique_pas_si": "l'offre ne parle que de front",
        "exemples": [
            {
                "entreprise": f"Entreprise {identifiant}",
                "fait": f"fait notable de {identifiant}",
                "citation": f"citation de {identifiant}",
                "url": "https://exemple.test/page",
                "texte": f"texte rédigé pour {identifiant}",
                "avis_gregoire": "bon exemple",
            }
        ],
    }
    base.update(overrides)
    return base


def _repertoire_bien_forme() -> dict:
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
        "ce_qui_fait_une_bonne_accroche": [
            "un fait précis de l'entreprise",
            "un lien entre ce fait et ce que j'ai déjà fait",
        ],
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
                "exception": "sauf si l'offre nomme Claude elle-même",
            }
        ],
        "conditions_generales": ["lettre en français", "160 mots cible"],
        "pour_l_entretien_pas_pour_la_lettre": [
            {"sujet": "détail d'archi RAG", "position": "à garder pour l'oral"}
        ],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": "lettre envoyée à Entreprise X le 2 octobre 2026",
        },
        "textes_types": [_texte_type(i) for i in IDS_TEXTES_TYPES],
        "juge": {
            "consigne": "Tu lis cette lettre comme un recruteur.",
            "contexte": "Contexte du poste et de l'entreprise.",
            "exemples": [
                {
                    "titre": "Relecture de référence",
                    "passage_lu": "Passage lu.",
                    "relecture": "Relecture.",
                }
            ],
        },
        "redaction": {
            "consigne_reprise": "Corrige la lettre selon le ressenti du juge."
        },
    }


def _ecrire(tmp_path: Path, donnees: dict, nom: str = "repertoire.yaml") -> Path:
    chemin = tmp_path / nom
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return chemin


# --- critère 1 ---------------------------------------------------------------


def test_charge_8_textes_types(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    assert len(charge.repertoire.textes_types) == 8


# --- critère 2 ---------------------------------------------------------------


def test_texte_type_porte_ses_champs(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    tt = next(t for t in charge.repertoire.textes_types if t.id == "prototyper")
    assert tt.sujet == "sujet de prototyper"
    assert tt.etat == "pret"
    assert tt.conviction == "conviction de prototyper"
    assert tt.ce_que_j_ai_fait == "ce que j'ai fait pour prototyper"
    assert tt.s_applique_si == "l'offre parle de tests"
    assert tt.ne_s_applique_pas_si == "l'offre ne parle que de front"
    assert len(tt.exemples) == 1


# --- critère 3 ---------------------------------------------------------------


def test_exemple_porte_ses_champs(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    tt = next(t for t in charge.repertoire.textes_types if t.id == "prototyper")
    exemple = tt.exemples[0]
    assert exemple.entreprise == "Entreprise prototyper"
    assert exemple.fait == "fait notable de prototyper"
    assert exemple.citation == "citation de prototyper"
    assert exemple.url == "https://exemple.test/page"
    assert exemple.texte == "texte rédigé pour prototyper"
    assert exemple.avis_gregoire == "bon exemple"


# --- critère 4 ---------------------------------------------------------------


def test_posture(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    posture = charge.repertoire.posture
    assert posture.role == "ingénieur qui prototype vite"
    assert posture.quatre_temps == ["accroche", "preuve", "offre", "cta"]
    assert posture.regles == ["jamais de superlatif", "une phrase, une idée"]
    assert len(posture.formulations_rejetees) == 1
    assert posture.formulations_rejetees[0].texte == "passionné par l'IA"
    assert posture.formulations_rejetees[0].motif == "trop vu, sonne creux"


# --- critère 5 ---------------------------------------------------------------


def test_sujets_interdits(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    assert len(charge.repertoire.sujets_interdits) == 1
    sujet = charge.repertoire.sujets_interdits[0]
    assert sujet.sujet == "Claude / Anthropic"
    assert sujet.motif == "l'entreprise visée n'en parle pas"
    assert sujet.exception == "sauf si l'offre nomme Claude elle-même"


# --- critère 6 ---------------------------------------------------------------


def test_conditions_generales_accroche_et_forme(tmp_path: Path) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    charge = charger_repertoire(chemin)
    repertoire = charge.repertoire
    assert repertoire.conditions_generales == ["lettre en français", "160 mots cible"]
    assert repertoire.ce_qui_fait_une_bonne_accroche == [
        "un fait précis de l'entreprise",
        "un lien entre ce fait et ce que j'ai déjà fait",
    ]
    assert repertoire.forme.blocs == ["accroche", "preuve", "offre", "cta"]
    assert repertoire.forme.longueur_cible_mots == 160
    assert repertoire.forme.lettre_de_reference == (
        "lettre envoyée à Entreprise X le 2 octobre 2026"
    )


# --- critère 7 ---------------------------------------------------------------


def test_champ_a_trou_est_rendu_absent(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    donnees["textes_types"][0]["conviction"] = "[À COMPLÉTER après le prochain run]"
    chemin = _ecrire(tmp_path, donnees)

    charge = charger_repertoire(chemin)

    tt = charge.repertoire.textes_types[0]
    assert tt.conviction is None
    dump = charge.repertoire.model_dump_json()
    assert "À COMPLÉTER" not in dump
    assert "[À COMPLÉTER" not in dump


# --- critère 8 ---------------------------------------------------------------


def test_liste_des_trous(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    # trou 1 : champ simple d'un texte type, sans exemple concerné
    donnees["textes_types"][0]["conviction"] = "[À COMPLÉTER]"
    # trou 2 : champ d'un exemple d'un autre texte type
    donnees["textes_types"][1]["exemples"][0]["citation"] = "[À COMPLÉTER citation]"
    # trou 3 : un autre champ d'exemple, texte type générique
    donnees["textes_types"][-1]["exemples"][0]["avis_gregoire"] = "[À COMPLÉTER avis]"
    chemin = _ecrire(tmp_path, donnees)

    charge = charger_repertoire(chemin)

    assert len(charge.trous) == 3

    premier = next(t for t in charge.trous if t.champ == "conviction")
    assert premier.texte_type == IDS_TEXTES_TYPES[0]
    assert premier.exemple is None

    second = next(t for t in charge.trous if t.champ == "citation")
    assert second.texte_type == IDS_TEXTES_TYPES[1]
    assert second.exemple == f"Entreprise {IDS_TEXTES_TYPES[1]}"

    troisieme = next(t for t in charge.trous if t.champ == "avis_gregoire")
    assert troisieme.texte_type == "generique"
    assert troisieme.exemple == "Entreprise generique"


# --- critère 9 ---------------------------------------------------------------


def test_fichier_absent(tmp_path: Path) -> None:
    chemin = tmp_path / "repertoire.yaml"
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    assert str(chemin) in str(exc_info.value)


# --- critère 10 ---------------------------------------------------------------


def test_identifiant_en_double(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    donnees["textes_types"][1]["id"] = donnees["textes_types"][0]["id"]
    chemin = _ecrire(tmp_path, donnees)
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    assert donnees["textes_types"][0]["id"] in str(exc_info.value)


# --- critère 11 ---------------------------------------------------------------


def test_texte_type_sans_identifiant(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    del donnees["textes_types"][2]["id"]
    chemin = _ecrire(tmp_path, donnees)
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    assert "3" in str(exc_info.value)


# --- critère 12 ---------------------------------------------------------------


def test_texte_type_sans_sujet(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    del donnees["textes_types"][3]["sujet"]
    chemin = _ecrire(tmp_path, donnees)
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    assert donnees["textes_types"][3]["id"] in str(exc_info.value)


# --- critère 13 ---------------------------------------------------------------


def test_aucun_texte_type_generique(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    donnees["textes_types"] = [
        tt for tt in donnees["textes_types"] if tt["id"] != "generique"
    ]
    chemin = _ecrire(tmp_path, donnees)
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    assert "generique" in str(exc_info.value)


# --- critère 14 ---------------------------------------------------------------


def test_yaml_illisible(tmp_path: Path) -> None:
    chemin = tmp_path / "repertoire.yaml"
    chemin.write_text("posture: [en train de casser: *manquant", encoding="utf-8")
    with pytest.raises(RepertoireError) as exc_info:
        charger_repertoire(chemin)
    message = str(exc_info.value)
    assert "Traceback" not in message
    assert "YAML" in message


# --- critère 15 ---------------------------------------------------------------


def test_commande_controle_bien_forme(tmp_path: Path, monkeypatch) -> None:
    chemin = _ecrire(tmp_path, _repertoire_bien_forme())
    monkeypatch.setattr("sys.argv", ["repertoire", str(chemin)])
    sortie = io.StringIO()
    with redirect_stdout(sortie):
        code = controle_main()
    assert code == 0
    texte = sortie.getvalue()
    assert "8" in texte
    assert "0 trou" in texte


def test_commande_controle_bien_forme_avec_trous(tmp_path: Path, monkeypatch) -> None:
    donnees = _repertoire_bien_forme()
    donnees["textes_types"][0]["conviction"] = "[À COMPLÉTER]"
    chemin = _ecrire(tmp_path, donnees)
    monkeypatch.setattr("sys.argv", ["repertoire", str(chemin)])
    sortie = io.StringIO()
    with redirect_stdout(sortie):
        code = controle_main()
    assert code == 0
    texte = sortie.getvalue()
    assert "1 trou" in texte
    assert "conviction" in texte


# --- critère 16 ---------------------------------------------------------------


def test_commande_controle_mal_forme(tmp_path: Path, monkeypatch) -> None:
    chemin = tmp_path / "repertoire.yaml"
    monkeypatch.setattr("sys.argv", ["repertoire", str(chemin)])
    sortie = io.StringIO()
    with redirect_stdout(sortie):
        code = controle_main()
    assert code == 1
    assert str(chemin) in sortie.getvalue()


# --- H2 : champ non nommé par H1 gardé tel quel -------------------------------


def test_champ_non_connu_garde_tel_quel(tmp_path: Path) -> None:
    donnees = _repertoire_bien_forme()
    donnees["note_future_inconnue"] = "un champ que le fichier ajoutera plus tard"
    chemin = _ecrire(tmp_path, donnees)
    charge = charger_repertoire(chemin)
    assert (
        charge.repertoire.model_extra["note_future_inconnue"]
        == "un champ que le fichier ajoutera plus tard"
    )
