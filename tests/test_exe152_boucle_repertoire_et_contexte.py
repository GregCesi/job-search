"""Tests EXE-152 — la rédaction et le juge reçoivent ce qui est vrai sur moi,
le juge reçoit ma lettre de référence, et un appel à un modèle local demande
une fenêtre de contexte et rend le nombre de jetons lus par le modèle.

Critères 1-5 : `boucle.appeler_modele` est remplacé par une doublure
programmable (reprise de test_exe150_boucle_lettre_manques.py) — aucun appel
de modèle réel. Critères 18-20 : le dispatch réel (`appeler_modele`, pas la
doublure) est exercé en doublant `ollama.Client` et `claude_agent_sdk.query`
eux-mêmes (reprise de test_exe147_boucle_lettre.py::TestDispatchModele).

Aucun test ne lit ni n'écrit sous data/ : le répertoire, le CV de référence
et les tournures interdites sont posés dans tmp_path.
"""

import json

import pytest
import yaml

import orchestrator.job_search.lettre.boucle as boucle
from orchestrator.job_search.lettre.boucle import (
    ConfigBoucle,
    ReponseModele,
    generer_lettre_depuis_donnees,
)

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


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


def _repertoire_donnees(ce_qui_est_vrai_sur_moi=None, lettre_de_reference=None) -> dict:
    """`None` (par défaut) omet entièrement la clé du YAML — reproduit le cas
    « mon répertoire ne porte pas » des critères 3 et 5."""
    donnees: dict = {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "regles": ["jamais de superlatif"],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
        },
        "textes_types": [
            {
                "id": "generique",
                "sujet": "sujet générique",
                "texte": "Texte générique rédigé à la main.",
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
    if ce_qui_est_vrai_sur_moi is not None:
        donnees["ce_qui_est_vrai_sur_moi"] = ce_qui_est_vrai_sur_moi
    if lettre_de_reference is not None:
        donnees["forme"]["lettre_de_reference"] = lettre_de_reference
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


def _lancer(repertoire_path, cv_path, tournures_path, modeles, **repertoire_kwargs):
    modeles.programmer("tamis", _TAMIS_GENERIQUE)
    modeles.programmer("redaction", "Lettre.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        "Texte de l'offre.",
        "Entreprise X",
        [],
        _config(),
        repertoire_path=repertoire_path(**repertoire_kwargs),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
    )


_TETE_CE_QUI_EST_VRAI = (
    "**Ce qui est vrai sur moi, qu'une lettre ne doit jamais contredire** :"
)


# --- critères 1-2 : ce qui est vrai sur moi, rédaction et juge -----------------


def test_critere1_redaction_recoit_ce_qui_est_vrai_sur_moi_en_entier(
    repertoire_path, cv_path, tournures_path, modeles
):
    _lancer(
        repertoire_path,
        cv_path,
        tournures_path,
        modeles,
        ce_qui_est_vrai_sur_moi=["Je code en Python depuis dix ans", "Phrase B"],
    )

    demande_redaction = modeles.appels[1][2]
    assert _TETE_CE_QUI_EST_VRAI in demande_redaction
    assert "Je code en Python depuis dix ans" in demande_redaction
    assert "Phrase B" in demande_redaction


def test_critere2_juge_ne_recoit_plus_ce_qui_est_vrai_sur_moi(
    repertoire_path, cv_path, tournures_path, modeles
):
    # Modifié pour EXE-158 (critère 4) : ce bloc est désormais réservé à la
    # rédaction — le juge ne reçoit plus rien de ce qui est vrai sur moi.
    _lancer(
        repertoire_path,
        cv_path,
        tournures_path,
        modeles,
        ce_qui_est_vrai_sur_moi=["Je code en Python depuis dix ans", "Phrase B"],
    )

    demande_juge = modeles.appels[2][2]
    assert _TETE_CE_QUI_EST_VRAI not in demande_juge
    assert "Je code en Python depuis dix ans" not in demande_juge
    assert "Phrase B" not in demande_juge


# --- critère 3 : absente ou vide, jamais de rubrique vide ni de « None » ------


def test_critere3_liste_absente_ni_rubrique_vide_ni_none(
    repertoire_path, cv_path, tournures_path, modeles
):
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_redaction = modeles.appels[1][2]
    demande_juge = modeles.appels[2][2]
    assert _TETE_CE_QUI_EST_VRAI not in demande_redaction
    assert _TETE_CE_QUI_EST_VRAI not in demande_juge
    assert "None" not in demande_redaction
    assert "None" not in demande_juge


def test_critere3_liste_vide_ni_rubrique_vide_ni_none(
    repertoire_path, cv_path, tournures_path, modeles
):
    _lancer(
        repertoire_path, cv_path, tournures_path, modeles, ce_qui_est_vrai_sur_moi=[]
    )

    demande_redaction = modeles.appels[1][2]
    demande_juge = modeles.appels[2][2]
    assert _TETE_CE_QUI_EST_VRAI not in demande_redaction
    assert _TETE_CE_QUI_EST_VRAI not in demande_juge
    assert "None" not in demande_redaction
    assert "None" not in demande_juge


# --- critère 4 : lettre de référence, réservée au juge -------------------------


def test_critere4_juge_ne_recoit_plus_la_lettre_de_reference(
    repertoire_path, cv_path, tournures_path, modeles
):
    # Modifié pour EXE-158 (critère 4) : la lettre de référence est désormais
    # réservée à la rédaction — le juge ne la reçoit plus.
    _lancer(
        repertoire_path,
        cv_path,
        tournures_path,
        modeles,
        lettre_de_reference="Voici ma lettre de référence, phrase unique.",
    )

    demande_juge = modeles.appels[2][2]
    assert "Voici ma lettre de référence, phrase unique." not in demande_juge
    assert "pas à contester" not in demande_juge


# --- critère 5 : pas de lettre de référence, ni rubrique vide ni « None » -----


def test_critere5_sans_lettre_de_reference_ni_rubrique_vide_ni_none(
    repertoire_path, cv_path, tournures_path, modeles
):
    _lancer(repertoire_path, cv_path, tournures_path, modeles)

    demande_juge = modeles.appels[2][2]
    assert "Lettre de référence" not in demande_juge
    assert "None" not in demande_juge


# --- critères 18-20 : dispatch réel vers Ollama (pas la doublure) -------------


class TestDispatchModeleLocal:
    """Doublure d'`ollama.Client` et de `claude_agent_sdk.query` eux-mêmes —
    reprise de test_exe147_boucle_lettre.py::TestDispatchModele."""

    def test_critere18_appel_local_demande_8192_jetons_de_contexte(self, monkeypatch):
        appels_ollama = []

        class FakeMessage:
            content = '{"rien_a_redire": true, "remarques": null}'

        class FakeResponse:
            message = FakeMessage()
            prompt_eval_count = 1234

        class FakeClient:
            def __init__(self, host=None, timeout=None):
                pass

            def chat(self, **kwargs):
                appels_ollama.append(kwargs)
                return FakeResponse()

        monkeypatch.setattr(boucle.ollama, "Client", FakeClient)

        boucle.appeler_modele("juge", "llama3", "demande", schema={"type": "object"})

        assert appels_ollama[0]["options"]["num_ctx"] == 8192

    def test_critere19_nb_jetons_lus_rendu_par_un_modele_local(self, monkeypatch):
        class FakeMessage:
            content = "Texte de la lettre."

        class FakeResponse:
            message = FakeMessage()
            prompt_eval_count = 4567

        class FakeClient:
            def __init__(self, host=None, timeout=None):
                pass

            def chat(self, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(boucle.ollama, "Client", FakeClient)

        reponse = boucle.appeler_modele("redaction", "llama3", "demande")

        assert reponse.nb_jetons == 4567

    def test_critere20_claude_ne_rend_aucun_nb_jetons(self, monkeypatch):
        from claude_agent_sdk import ResultMessage

        def fake_query(*, prompt, options):
            async def _gen():
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="s",
                    total_cost_usd=0.03,
                    result="Texte de la lettre.",
                    structured_output=None,
                )

            return _gen()

        monkeypatch.setattr(boucle, "query", fake_query)

        reponse = boucle.appeler_modele("redaction", "sonnet", "demande")

        assert reponse.nb_jetons is None
