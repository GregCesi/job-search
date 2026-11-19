"""Tests EXE-208 — profil développeur du CV, troisième texte de profil choisi à
la main dans Modifier (critères 2, 3, 5, 6, 7, 9 à 14, et « ce qui ne doit pas
arriver »).

Passent par les fonctions de route de l'API (`api/cv.py`) sur une base
`tmp_path` ; une erreur de validation ou HTTP est rendue comme son code de
statut. Aucun test ne
lit ni n'écrit sous data/ : CV de référence FR/EN et fichiers de profil
(Claude et développeur) sont posés sous `tmp_path` (H2, H3 du ticket). Aucun
appel de modèle : `query` du SDK est remplacé par un faux générateur.
"""

import sqlite3

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import api.cv as api_cv
import orchestrator.job_search.cv.profil as cv_profil
import orchestrator.job_search.paths as paths
from tests.test_exe184_cv_profil_claude import (
    PROFIL_CLAUDE_EN,
    PROFIL_CLAUDE_FR,
    _cvs_row,
    _insert_fiche,
    _insert_offer,
    _run_cv,
    cv_fixture_paths,  # noqa: F401 — fixture réutilisée
    db_path,  # noqa: F401 — fixture réutilisée
)

PROFIL_DEV_FR = "Développeur backend Python, je construis des API solides."
PROFIL_DEV_EN = "Backend Python developer, I build solid APIs."
PROFIL_BASE_FR = "Profil de base, inchangé."
PROFIL_BASE_EN = "Base profile, unchanged."


@pytest.fixture
def dev_paths(tmp_path, monkeypatch, cv_fixture_paths):  # noqa: F811
    # `constate_profil` lit ses propres noms importés : le CV de référence de
    # la fixture EXE-184 y est reposé, pour que le profil affiché se constate.
    ref, ref_en = cv_fixture_paths[0], cv_fixture_paths[1]
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_PATH", ref)
    monkeypatch.setattr(cv_profil, "CV_REFERENCE_EN_PATH", ref_en)
    fr = tmp_path / "profil_dev.fr.txt"
    fr.write_text(PROFIL_DEV_FR, encoding="utf-8")
    en = tmp_path / "profil_dev.en.txt"
    en.write_text(PROFIL_DEV_EN, encoding="utf-8")
    monkeypatch.setattr(cv_profil, "CV_PROFIL_DEV_FR_PATH", fr, raising=False)
    monkeypatch.setattr(cv_profil, "CV_PROFIL_DEV_EN_PATH", en, raising=False)
    return fr, en


class _Reponse:
    """Réponse de route réduite à ce que les tests lisent : code et corps."""

    def __init__(self, status_code: int, corps):
        self.status_code = status_code
        self.corps = corps
        self.text = str(corps)

    def json(self):
        return self.corps


class _Client:
    """Appelle les fonctions de route de `api/cv.py` comme le ferait FastAPI :
    corps validé par `CvProfilIn` (422 sinon), `HTTPException` rendue en code."""

    def put(self, url: str, json: dict) -> _Reponse:
        offer_id = int(url.split("/")[2])
        try:
            body = api_cv.CvProfilIn(**json)
        except ValidationError as exc:
            return _Reponse(422, str(exc))
        try:
            return _Reponse(200, api_cv.put_cv_profil(offer_id, body))
        except HTTPException as exc:
            return _Reponse(exc.status_code, {"detail": exc.detail})

    def get(self, url: str) -> _Reponse:
        offer_id = int(url.split("/")[2])
        try:
            return _Reponse(200, api_cv.get_cv(offer_id))
        except HTTPException as exc:
            return _Reponse(exc.status_code, {"detail": exc.detail})


@pytest.fixture
def client():
    return _Client()


def _cv_genere(db_path, monkeypatch, offer_id, ad_language="en"):  # noqa: F811
    _insert_offer(db_path, offer_id, techs=[], ad_language=ad_language)
    _run_cv(monkeypatch, offer_id)
    row = _cvs_row(db_path, offer_id)
    assert row["statut"] == "done"
    return row


def _choisir(client, offer_id, profil):
    return client.put(f"/offers/{offer_id}/cv/profil", json={"profil": profil})


class TestCritere2Et3TexteDuFichierMotPourMot:
    def test_fr_et_en_portent_les_fichiers_developpeur(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _cv_genere(db_path, monkeypatch, 801)

        resp = _choisir(client, 801, "dev")
        assert resp.status_code == 200, resp.text

        row = _cvs_row(db_path, 801)
        assert f'<p class="lead">{PROFIL_DEV_FR}</p>' in row["html"]
        assert PROFIL_BASE_FR not in row["html"]
        assert f'<p class="lead">{PROFIL_DEV_EN}</p>' in row["en_html"]
        assert PROFIL_BASE_EN not in row["en_html"]


class TestCritere4Et5Et7ProfilAfficheEtPhrase:
    def test_profil_affiche_dev_et_choisi_par_toi_meme_apres_rechargement(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _cv_genere(db_path, monkeypatch, 802)

        resp = _choisir(client, 802, "dev")
        assert resp.status_code == 200, resp.text
        assert resp.json()["profil_affiche"] == "dev"
        assert resp.json()["profil_phrase"] == "Choisi par toi"

        # Critère 7 : relu depuis la base, comme au rechargement de la page.
        relu = client.get("/offers/802/cv").json()
        assert relu["profil"] == "dev"
        assert relu["profil_affiche"] == "dev"
        assert relu["profil_phrase"] == "Choisi par toi"


class TestCritere6MarquePreteEffacee:
    def test_la_marque_prete_s_efface(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _cv_genere(db_path, monkeypatch, 803)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE cvs SET marque_pret_at='2026-11-19T10:00:00' WHERE offer_id=803"
        )
        conn.commit()
        conn.close()

        resp = _choisir(client, 803, "dev")
        assert resp.status_code == 200, resp.text
        assert _cvs_row(db_path, 803)["marque_pret_at"] is None


class TestCritere9RetourAuProfilDeBase:
    def test_le_paragraphe_redevient_celui_du_cv_de_reference(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _cv_genere(db_path, monkeypatch, 804)
        assert _choisir(client, 804, "dev").status_code == 200

        resp = _choisir(client, 804, "base")
        assert resp.status_code == 200, resp.text
        row = _cvs_row(db_path, 804)
        assert f'<p class="lead">{PROFIL_BASE_FR}</p>' in row["html"]
        assert PROFIL_DEV_FR not in row["html"]
        assert f'<p class="lead">{PROFIL_BASE_EN}</p>' in row["en_html"]
        assert resp.json()["profil_affiche"] == "base"


class TestCritere10FichierFrancaisAbsent:
    def test_message_nomme_le_fichier_et_le_cv_ne_change_pas(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        avant = _cv_genere(db_path, monkeypatch, 805)
        dev_fr, _ = dev_paths
        dev_fr.unlink()

        resp = _choisir(client, 805, "dev")
        assert resp.status_code == 409
        assert str(dev_fr) in resp.json()["detail"]

        apres = _cvs_row(db_path, 805)
        assert apres["html"] == avant["html"]
        assert apres["en_html"] == avant["en_html"]
        assert apres["profil"] == avant["profil"]
        assert apres["profil_motif"] == avant["profil_motif"]


class TestCritere11FichierAnglaisAbsent:
    def test_le_francais_change_l_anglais_nomme_le_fichier(
        self,
        client,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _cv_genere(db_path, monkeypatch, 806)
        _, dev_en = dev_paths
        dev_en.unlink()

        resp = _choisir(client, 806, "dev")
        assert resp.status_code == 200, resp.text
        row = _cvs_row(db_path, 806)
        assert PROFIL_DEV_FR in row["html"]
        assert str(dev_en) in (row["en_error_message"] or "")


class TestCritere12Et13ChoixAutomatiqueInchange:
    """Non-régression (le comportement précède le ticket) : avec les fichiers
    développeur présents, la génération rend toujours base ou Claude."""

    def test_offre_sans_claude_recoit_le_profil_base(
        self,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _insert_offer(
            db_path, 807, techs=[{"name": "python", "importance": "required"}]
        )
        _run_cv(monkeypatch, 807)
        row = _cvs_row(db_path, 807)
        assert row["profil"] == "base"
        assert PROFIL_BASE_FR in row["html"]

    def test_offre_qui_cite_claude_recoit_le_profil_claude(
        self,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _insert_offer(
            db_path,
            808,
            techs=[{"name": "Claude", "importance": "required"}],
            ad_language="en",
        )
        _run_cv(monkeypatch, 808)
        row = _cvs_row(db_path, 808)
        assert row["profil"] == "claude"
        assert PROFIL_CLAUDE_FR in row["html"]
        assert PROFIL_CLAUDE_EN in row["en_html"]

    def test_retour_de_fiche_ne_choisit_jamais_le_profil_dev(
        self,
        db_path,  # noqa: F811
        cv_fixture_paths,  # noqa: F811
        dev_paths,
        monkeypatch,
    ):
        _insert_offer(db_path, 809, techs=[])
        _run_cv(monkeypatch, 809)
        _insert_fiche(db_path, 809, presentation="Développement backend pur.")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            from orchestrator.job_search.cv.service import (  # noqa: PLC0415
                recalc_profile_after_fiche,
            )

            recalc_profile_after_fiche(conn, 809)
        finally:
            conn.close()
        assert _cvs_row(db_path, 809)["profil"] == "base"


class TestCritere14CheminsHorsDeData:
    def test_les_deux_chemins_ne_sont_pas_sous_data_du_depot(self):
        data_dir = paths.REPO_ROOT / "data"
        for nom in ("CV_PROFIL_DEV_FR_PATH", "CV_PROFIL_DEV_EN_PATH"):
            for module in (paths, cv_profil):
                chemin = getattr(module, nom, None)
                assert chemin is not None, f"{module.__name__}.{nom} absent"
                assert not chemin.resolve().is_relative_to(data_dir.resolve()), (
                    f"{module.__name__}.{nom} = {chemin} est sous data/"
                )
