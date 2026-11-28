"""Tests EXE-223 — « vérifier tout », la fin du run, les sorties et la remise.

Aucun test n'appelle un site : le point d'appel réseau du parcours
(`parcours.reseau.lire`) et `check_url` de la vérification sont simulés, comme dans
tests/test_exe218_fermeture.py. Chaque test pose sa base (fixture
`_isolate_db_path` de conftest.py) et son profil dans un dossier temporaire.

Offre témoin : celle de tests/test_exe218_fermeture.py, dans la file « À postuler »,
famille « Développeur », avec une adresse d'annonce EURES. « Vérifier tout » veut
dire POST /offers/check-expirations avec le corps {"tout": true}. Les parcours des
offres qui ne sont pas lues par le test sont posés directement en base.
"""

import importlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths
from orchestrator.job_search.expiration import service as expiration_service

REPO = Path(__file__).resolve().parent.parent

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EURES_ANNONCE = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=fr"
EDITX_API_20200 = "https://api.editx.eu/en/api/editx/job/20200"
EDITX_20200 = (
    "https://editx.eu/en/job/20200/laravel-developer?utm_source=vdab&utm_medium=cpc"
)
SANDER = (
    "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
    "?utm_source=editx&utm_medium=job_board"
)
SANDER_PROPRE = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
SOURCE = "la source ne rend plus l'offre"
LU_AVANT = "2026-11-01T08:00:00+00:00"

PROFIL = """\
profile_id: test
role_ceiling: ic
seniority_ceiling: intermediate
skills:
  python: { level: 6, desire: 5 }
search_criteria:
  keywords: [python]
  domains: [backend]
  locations: []
  contract_types: []
"""

_compteur = {"n": 0}


# ---------------------------------------------------------------------------
# Réseau simulé
# ---------------------------------------------------------------------------


def _rep(adresse: str, texte: str = "", code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(chaine=[(adresse, code)], texte=texte)


def _eures_json(lien: str) -> str:
    consigne = f'<p>Postulez <a href="{lien.replace("&", "&amp;")}">ici</a></p>'
    return json.dumps({"jvProfiles": {"fr": {"applicationInstructions": [consigne]}}})


def _editx() -> str:
    return json.dumps(
        {
            "status": "online",
            "openToApply": True,
            "applicationType": "url",
            "applicationAction": SANDER,
            "locality": "La Hulpe",
            "onlineDate": {"value": "2026-10-13 06:41:14"},
        }
    )


class Toile:
    """Une réponse par adresse ; toute autre adresse rend une page vide, code 200."""

    def __init__(self) -> None:
        self.pages: dict = {
            EDITX_API_20200: _rep(EDITX_API_20200, _editx()),
            SANDER: _rep(SANDER, "<html><title>Laravel developer</title></html>"),
        }
        self.demandes: list[str] = []

    def eures(self, source_id: str, ferme: bool = False) -> None:
        api = EURES_API.format(id=source_id)
        self.pages[api] = (
            _rep(api, "", 404) if ferme else _rep(api, _eures_json(EDITX_20200))
        )

    def __call__(self, adresse: str):
        self.demandes.append(adresse)
        return self.pages.get(adresse) or _rep(adresse, "<html>Offre</html>")


@pytest.fixture
def toile(monkeypatch) -> Toile:
    t = Toile()
    reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    monkeypatch.setattr(reseau, "lire", t)
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)
    return t


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths, "PROFILE_PATH", chemin)


@pytest.fixture(autouse=True)
def _codes_url(monkeypatch):
    monkeypatch.setattr(
        expiration_service,
        "check_url",
        lambda url: (200, datetime.now(timezone.utc).isoformat()),
    )


@pytest.fixture
def client():
    import api.main as api_main

    with TestClient(api_main.app) as c:
        yield c


# ---------------------------------------------------------------------------
# La base
# ---------------------------------------------------------------------------


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(paths.DB_PATH)


def _offre(
    *,
    source="manuel",
    source_id=None,
    url=None,
    titre="Développeur Python",
    entreprise=None,
    lieu="Bruxelles",
    domaine="backend",
    niveau="intermediate",
    contrat="directhire",
    jours=2,
) -> int:
    _compteur["n"] += 1
    n = _compteur["n"]
    source_id = source_id or f"S{n}"
    url = url or f"https://exemple.be/offre/{n}"
    facts = json.dumps(
        {
            "seniority_required": niveau,
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": domaine,
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    fetched = (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, ad_language, "
            "extracted_facts_json, filtered_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                source,
                source_id,
                f"fp-223-{n}",
                titre,
                entreprise or f"Acme {n}",
                lieu,
                contrat,
                url,
                fetched,
                "Poste de développeur Python dans une équipe produit. " * 10,
                "fr",
                facts,
            ),
        )
        return cur.lastrowid


def _temoin(toile: Toile, ferme: bool = False, **autres) -> int:
    _compteur["n"] += 1
    source_id = f"T{_compteur['n']}"
    toile.eures(source_id, ferme)
    return _offre(
        source="eures",
        source_id=source_id,
        url=EURES_ANNONCE.format(id=source_id),
        **autres,
    )


def _etat(oid: int, etat: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?)", (oid, etat)
        )


def _parcours(
    oid: int,
    *,
    cle=None,
    fin_forme="page",
    fin_adresse=None,
    lieu_reel=None,
    code_postal=None,
    ouverture="ouverte",
    fermeture=None,
    verifiee_le=LU_AVANT,
    lu_le=LU_AVANT,
) -> None:
    """Un parcours lu, posé en base comme la lecture l'écrit."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, "
            "fin_adresse, cle, lieu_reel, code_postal, provinces_json, ouverture, "
            "verifiee_le, fermeture_json) VALUES (?, ?, '[]', ?, ?, ?, ?, ?, '[]', "
            "?, ?, ?)",
            (
                oid,
                lu_le,
                fin_forme,
                fin_adresse or cle,
                cle,
                lieu_reel,
                code_postal,
                ouverture,
                verifiee_le,
                json.dumps(fermeture) if fermeture else None,
            ),
        )


def _expiree(oid: int, quand: str = LU_AVANT) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO expirations (offer_id, expired, last_checked_at) "
            "VALUES (?, 1, ?)",
            (oid, quand),
        )


def _fermee(oid: int, verifiee_le: str = LU_AVANT) -> None:
    """Une offre fermée par une vérification : verdict et parcours."""
    _parcours(
        oid,
        fin_forme="inconnue",
        ouverture="fermée",
        fermeture={"signe": SOURCE, "site": "exemple.be", "code": 404, "phrase": None},
        verifiee_le=verifiee_le,
    )
    _expiree(oid, verifiee_le)


# ---------------------------------------------------------------------------
# Lectures par l'API
# ---------------------------------------------------------------------------


def _tout(client) -> None:
    r = client.post("/offers/check-expirations", json={"tout": True})
    assert r.status_code == 204, r.text


def _lu(client, oid: int) -> dict:
    r = client.get(f"/offers/{oid}/parcours")
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client, **params) -> list[int]:
    r = client.get("/a-postuler", params=params)
    assert r.status_code == 200, r.text
    return [li["id"] for li in r.json()["lignes"]]


def _ligne(client, oid: int, file: str = "principale") -> dict:
    r = client.get("/a-postuler", params={"file": file})
    assert r.status_code == 200, r.text
    lignes = [li for li in r.json()["lignes"] if li["id"] == oid]
    assert len(lignes) == 1, r.json()
    return lignes[0]


def _sorties(client) -> list[dict]:
    r = client.get("/a-postuler/sorties")
    assert r.status_code == 200, r.text
    return r.json()


def _sortie(client, oid: int) -> dict:
    trouvees = [s for s in _sorties(client) if s["id"] == oid]
    assert len(trouvees) == 1, _sorties(client)
    return trouvees[0]


def _etat_stocke(oid: int) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT etat FROM etats_offre WHERE offer_id = ?", (oid,)
        ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Vérifier tout
# ---------------------------------------------------------------------------


class TestVerifierTout:
    def test_critere_1_temoin_lu(self, client, toile):
        oid = _temoin(toile)
        assert _ids(client, famille="developpeur") == [oid]
        _tout(client)
        assert _lu(client, oid)["etat"] == "lu"

    def test_critere_2_famille_ia_lue(self, client, toile):
        _temoin(toile)
        ia = _offre(domaine="ai_engineering")
        assert ia in _ids(client, famille="ia")
        _tout(client)
        assert _lu(client, ia)["etat"] == "lu"

    def test_critere_3_a_etudier_interessant_lu(self, client, toile):
        oid = _offre(domaine="data_science")
        assert oid in _ids(client, file="a_etudier", groupe="interessant")
        _tout(client)
        assert _lu(client, oid)["etat"] == "lu"

    def test_critere_4_a_etudier_trop_senior_lu(self, client, toile):
        oid = _offre(niveau="senior")
        assert oid in _ids(client, file="a_etudier", groupe="trop_senior")
        _tout(client)
        assert _lu(client, oid)["etat"] == "lu"

    def test_critere_5_jumelle_cachee_lue(self, client, toile):
        temoin = _temoin(toile, entreprise="Mozzeno")
        j = _offre(entreprise="Mozzeno", jours=5)
        assert [x["id"] for x in _ligne(client, temoin)["jumelles"]] == [j]
        _tout(client)
        assert _lu(client, j)["etat"] == "lu"

    def test_critere_6_candidature_envoyee_fermee(self, client, toile):
        oid = _temoin(toile, ferme=True)
        _etat(oid, "candidature_envoyee")
        _tout(client)
        assert _lu(client, oid)["etat"] == "lu"
        assert client.get(f"/offers/{oid}").json()["expired"] is True
        assert _etat_stocke(oid) == "candidature_envoyee"

    def test_critere_7_retenue_entretien_offre_recue_lues(self, client, toile):
        ids = {}
        for etat in ("retenue", "entretien", "offre_recue"):
            ids[etat] = _offre()
            _etat(ids[etat], etat)
        _tout(client)
        assert {e: _lu(client, oid)["etat"] for e, oid in ids.items()} == {
            "retenue": "lu",
            "entretien": "lu",
            "offre_recue": "lu",
        }

    def test_critere_8_terminees_deja_lues_pas_relues(self, client, toile):
        ids = {}
        for etat in ("ecartee", "refusee", "sans_suite", "abandonnee"):
            ids[etat] = _offre()
            _etat(ids[etat], etat)
            _parcours(ids[etat], cle=f"https://exemple.be/fin/{etat}")
        _tout(client)
        assert {e: _lu(client, oid)["lu_le"] for e, oid in ids.items()} == {
            e: LU_AVANT for e in ids
        }

    def test_critere_9_ecartee_jamais_lue_lue(self, client, toile):
        oid = _offre()
        _etat(oid, "ecartee")
        _tout(client)
        assert _lu(client, oid)["etat"] == "lu"

    def test_critere_10_a_trier_hors_files_jamais_lue(self, client, toile):
        _temoin(toile)
        oid = _offre(lieu="67 - Strasbourg")
        _tout(client)
        assert _lu(client, oid)["etat"] == "jamais lu"

    def test_critere_11_tout_et_identifiants_422(self, client, toile):
        oid = _temoin(toile)
        r = client.post(
            "/offers/check-expirations", json={"tout": True, "offer_ids": [oid]}
        )
        assert r.status_code == 422
        assert _lu(client, oid)["etat"] == "jamais lu"


# ---------------------------------------------------------------------------
# La fin du run
# ---------------------------------------------------------------------------


def _lancer_run(monkeypatch, tmp_path) -> None:
    import orchestrator.job_search.run as run
    import orchestrator.job_search.scoring.extractor as extractor
    import orchestrator.job_search.sources.france_travail as ft

    class _Source:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch(self):
            return []

    profil = tmp_path / "profil.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", profil)
    monkeypatch.setattr(paths, "PROFILE_PATH", profil)
    monkeypatch.setattr(ft, "FranceTravailSource", _Source)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda host, model: None)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    monkeypatch.setenv("OLLAMA_MODEL_TRI", "tri-test")
    monkeypatch.setenv("OLLAMA_MODEL", "precision-test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--profile",
            str(profil),
            "--no-remotive",
            "--no-indeed",
            "--no-eures",
            "--no-actiris",
            "--no-forem",
        ],
    )
    run.main()


class TestFinDeRun:
    @pytest.fixture
    def base(self, client):
        # Le client crée les tables ; le run les retrouve.
        return client

    def test_critere_12_candidature_envoyee_lue(
        self, base, toile, monkeypatch, tmp_path
    ):
        _temoin(toile, lieu="Belgique")
        oid = _offre(lieu="Belgique")
        _etat(oid, "candidature_envoyee")
        # Déjà lue une fois : la fin du run la relit à chaque fois (H2, 2).
        _parcours(oid, cle="https://exemple.be/fin/envoyee")
        _lancer_run(monkeypatch, tmp_path)
        lu = _lu(base, oid)
        assert lu["etat"] == "lu"
        assert lu["lu_le"] != LU_AVANT

    def test_critere_13_jumelle_lue(self, base, toile, monkeypatch, tmp_path):
        temoin = _temoin(toile, lieu="Belgique", entreprise="Mozzeno")
        j = _offre(lieu="Belgique", entreprise="Mozzeno", jours=5)
        assert [x["id"] for x in _ligne(base, temoin)["jumelles"]] == [j]
        _lancer_run(monkeypatch, tmp_path)
        assert _lu(base, temoin)["etat"] == "lu"
        assert _lu(base, j)["etat"] == "lu"


# ---------------------------------------------------------------------------
# Les sorties
# ---------------------------------------------------------------------------


def _temoin_sorti(client, toile) -> int:
    oid = _temoin(toile, ferme=True, titre="Développeur Laravel", entreprise="Sander")
    _tout(client)
    assert oid not in _ids(client)
    return oid


def _herstal() -> int:
    oid = _offre(lieu="Belgique")
    _parcours(
        oid,
        cle=SANDER_PROPRE,
        lieu_reel="Herstal",
        code_postal="4040",
        fin_forme="page",
    )
    return oid


def _meme_lien() -> tuple[int, int]:
    """Deux offres de même lien : la plus récente est gardée."""
    gardee = _offre(titre="Développeur PHP", jours=1)
    autre = _offre(titre="PHP developer", jours=6)
    _parcours(gardee, cle="https://exemple.be/postuler/42")
    _parcours(autre, cle="https://exemple.be/postuler/42")
    return gardee, autre


class TestSorties:
    def test_critere_14_motif_signe_site_code(self, client, toile):
        s = _sortie(client, _temoin_sorti(client, toile))
        assert (s["motif"], s["signe"], s["site"], s["code"]) == (
            "annonce expirée",
            SOURCE,
            "europa.eu",
            404,
        )

    def test_critere_15_file_date_titre_entreprise(self, client, toile):
        avant = datetime.now(timezone.utc)
        s = _sortie(client, _temoin_sorti(client, toile))
        assert s["file"] == "principale"
        assert s["titre"] == "Développeur Laravel"
        assert s["entreprise"] == "Sander"
        verifiee = datetime.fromisoformat(s["verifiee_le"])
        assert avant <= verifiee <= datetime.now(timezone.utc)

    def test_critere_16_preuve_adresse_de_l_annonce(self, client, toile):
        oid = _temoin_sorti(client, toile)
        url = client.get(f"/offers/{oid}").json()["url"]
        assert _sortie(client, oid)["preuve"] == url

    def test_critere_17_lieu_herstal(self, client, toile):
        s = _sortie(client, _herstal())
        assert (s["motif"], s["lieu_reel"], s["code_postal"], s["preuve"]) == (
            "lieu",
            "Herstal",
            "4040",
            SANDER_PROPRE,
        )

    def test_critere_18_doublon(self, client, toile):
        gardee, autre = _meme_lien()
        s = _sortie(client, autre)
        assert s["motif"] == "doublon"
        assert s["meme_offre_que"]["id"] == gardee
        assert s["meme_offre_que"]["titre"] == "Développeur PHP"
        assert gardee not in [x["id"] for x in _sorties(client)]

    def test_critere_19_deja_traitee(self, client, toile):
        envoyee = _offre(titre="Développeur PHP")
        _etat(envoyee, "candidature_envoyee")
        _parcours(envoyee, cle="https://exemple.be/postuler/7")
        oid = _offre(titre="PHP developer")
        _parcours(oid, cle="https://exemple.be/postuler/7")
        s = _sortie(client, oid)
        assert s["motif"] == "déjà traitée"
        assert s["meme_offre_que"]["id"] == envoyee
        assert s["meme_offre_que"]["etat"] == "candidature_envoyee"

    def test_critere_20_file_a_etudier(self, client, toile):
        oid = _offre(domaine="data_science")
        _fermee(oid)
        s = _sortie(client, oid)
        assert (s["file"], s["motif"]) == ("a_etudier", "annonce expirée")

    def test_critere_21_motifs_hors_verification(self, client, toile):
        strasbourg = _offre(lieu="67 - Strasbourg")
        freelance = _offre(contrat="freelance")
        _fermee(strasbourg)
        _fermee(freelance)
        ids = [s["id"] for s in _sorties(client)]
        assert (strasbourg in ids, freelance in ids) == (False, False)

    def test_critere_22_ecartee_absente(self, client, toile):
        oid = _offre()
        _etat(oid, "ecartee")
        _fermee(oid)
        assert oid not in [s["id"] for s in _sorties(client)]

    def test_critere_23_plus_recente_d_abord(self, client, toile):
        ancienne = _offre()
        recente = _offre()
        _fermee(ancienne, "2026-11-10T08:00:00+00:00")
        _fermee(recente, "2026-11-20T08:00:00+00:00")
        assert [s["id"] for s in _sorties(client)] == [recente, ancienne]

    def test_critere_24_liste_vide(self, client, toile):
        _offre()
        r = client.get("/a-postuler/sorties")
        assert r.status_code == 200
        assert r.json() == []

    def test_h3_fermee_par_l_ancienne_verification_sans_signe(self, client, toile):
        oid = _offre()
        _expiree(oid)
        s = _sortie(client, oid)
        assert s["motif"] == "annonce expirée"
        assert (s["signe"], s["site"], s["code"], s["phrase"]) == (None,) * 4


# ---------------------------------------------------------------------------
# Remettre dans la liste
# ---------------------------------------------------------------------------


def _remettre(client, oid: int) -> None:
    r = client.post(f"/offers/{oid}/remise")
    assert r.status_code == 204, r.text


class TestRemise:
    def test_critere_25_temoin_revient(self, client, toile):
        oid = _temoin_sorti(client, toile)
        assert client.post(f"/offers/{oid}/remise").status_code == 204
        assert oid in _ids(client)

    def test_critere_26_marque(self, client, toile):
        oid = _temoin_sorti(client, toile)
        _remettre(client, oid)
        assert "remise à la main" in _ligne(client, oid)["marques"]

    def test_critere_27_plus_dans_les_sorties(self, client, toile):
        oid = _temoin_sorti(client, toile)
        _remettre(client, oid)
        assert oid not in [s["id"] for s in _sorties(client)]

    def test_critere_28_nouvelle_verification_ne_le_sort_pas(self, client, toile):
        oid = _temoin_sorti(client, toile)
        _remettre(client, oid)
        _tout(client)
        assert _lu(client, oid)["ouverture"] == "fermée"
        assert oid in _ids(client)

    def test_critere_29_herstal_revient(self, client, toile):
        oid = _herstal()
        _remettre(client, oid)
        assert _ligne(client, oid)["lieu"] == "Herstal"

    def test_critere_30_doublon_revient(self, client, toile):
        gardee, autre = _meme_lien()
        _remettre(client, autre)
        ids = _ids(client)
        assert (gardee in ids, autre in ids) == (True, True)
        assert [j["id"] for j in _ligne(client, gardee)["jumelles"]] == []

    def test_critere_31_hors_sorties_409(self, client, toile):
        oid = _offre()
        assert client.post(f"/offers/{oid}/remise").status_code == 409

    def test_critere_32_annulation(self, client, toile):
        oid = _temoin_sorti(client, toile)
        _remettre(client, oid)
        assert client.delete(f"/offers/{oid}/remise").status_code == 204
        assert oid not in _ids(client)
        assert oid in [s["id"] for s in _sorties(client)]

    def test_critere_33_ni_tri_ni_etape(self, client, toile):
        oid = _temoin_sorti(client, toile)
        avant = client.get(f"/offers/{oid}").json()
        _remettre(client, oid)
        apres = client.get(f"/offers/{oid}").json()
        assert (apres["tri"], apres["etape"]) == (avant["tri"], avant["etape"])
        client.delete(f"/offers/{oid}/remise")
        fin = client.get(f"/offers/{oid}").json()
        assert (fin["tri"], fin["etape"]) == (avant["tri"], avant["etape"])


# ---------------------------------------------------------------------------
# Mes candidatures en cours
# ---------------------------------------------------------------------------


def _annonces(client) -> dict[int, dict]:
    r = client.get("/suivi/annonces")
    assert r.status_code == 200, r.text
    return {a["id"]: a for a in r.json()}


class TestSuiviAnnonces:
    def test_critere_34_candidature_fermee(self, client, toile):
        oid = _temoin(toile, ferme=True)
        _etat(oid, "candidature_envoyee")
        _tout(client)
        a = _annonces(client)[oid]
        assert (a["ouverture"], a["signe"], a["site"]) == (
            "fermée",
            SOURCE,
            "europa.eu",
        )
        assert a["verifiee_le"]

    def test_critere_35_jamais_verifiee(self, client, toile):
        oid = _offre()
        _etat(oid, "candidature_envoyee")
        a = _annonces(client)[oid]
        assert (a["ouverture"], a["signe"]) == (None, None)

    def test_critere_36_refusee_et_ecartee_absentes(self, client, toile):
        refusee, ecartee = _offre(), _offre()
        _etat(refusee, "refusee")
        _etat(ecartee, "ecartee")
        ids = _annonces(client)
        assert (refusee in ids, ecartee in ids) == (False, False)


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver
# ---------------------------------------------------------------------------


class TestInterdits:
    def test_lectures_sans_ecriture(self, client, toile):
        oid = _temoin_sorti(client, toile)
        _etat(_offre(), "candidature_envoyee")
        with _conn() as conn:
            avant = list(conn.iterdump())
        _sorties(client)
        _annonces(client)
        with _conn() as conn:
            assert list(conn.iterdump()) == avant
        assert oid not in _ids(client)

    def test_verifier_tout_ne_change_ni_offre_ni_etat(self, client, toile):
        oid = _temoin(toile, ferme=True)
        _etat(oid, "candidature_envoyee")
        with _conn() as conn:
            avant = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
        _tout(client)
        with _conn() as conn:
            apres = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
            remises = conn.execute("SELECT COUNT(*) FROM remises").fetchone()[0]
        assert apres == avant
        assert _etat_stocke(oid) == "candidature_envoyee"
        assert remises == 0
