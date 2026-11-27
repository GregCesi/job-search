"""Tests EXE-218 — « Vérifier les offres » sort celles où l'on ne peut plus postuler.

Aucun test n'appelle un site : chaque réponse est simulée en remplaçant le point
d'appel réseau du parcours (`parcours.reseau.lire`) et `check_url` de la
vérification. Chaque test pose sa base (fixture `_isolate_db_path` de conftest.py)
et son profil dans un dossier temporaire, comme tests/test_exe210_a_postuler.py.

La vérification se lance par POST /offers/check-expirations avec l'identifiant de
l'offre. Le motif d'une offre sortie se lit par GET /offers/{id}/a-postuler, le
signe de fermeture par GET /offers/{id}/parcours. Chaque critère change une seule
chose au témoin : une offre eures de la file principale, dont le parcours est
celui du témoin d'EXE-217 (détail EURES 200, EDITx 20200 en ligne, page Sander 200).
"""

import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths
from orchestrator.job_search.expiration import service as expiration_service
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

REPO = Path(__file__).resolve().parent.parent

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EDITX_API_20200 = "https://api.editx.eu/en/api/editx/job/20200"
TEMOIN_URL = "https://europa.eu/eures/portal/jv-se/jv-details/AAA?lang=fr"
EDITX_20200 = (
    "https://editx.eu/en/job/20200/laravel-developer?utm_source=vdab&utm_medium=cpc"
)
SANDER = (
    "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
    "?utm_source=editx&utm_medium=job_board"
)
SANDER_PROPRE = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
ACTIRIS_URL = (
    "https://www.actiris.brussels/fr/citoyens/detail-offre-demploi/"
    "?reference=5977883&type=Hrxml"
)

# Les cinq phrases de H3, telles que le ticket les donne.
PHRASES_H3 = [
    "n'est plus disponible",
    "no longer available",
    "has been filled",
    "n'existe pas ou plus",
    "offer not found",
]

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
# Réponses simulées
# ---------------------------------------------------------------------------


def _rep(adresse: str, texte: str = "", code: int = 200, via=()) -> SimpleNamespace:
    return SimpleNamespace(chaine=[*via, (adresse, code)], texte=texte)


def _eures(lien: str) -> str:
    consigne = f'<p>Postulez <a href="{lien.replace("&", "&amp;")}">ici</a></p>'
    return json.dumps({"jvProfiles": {"fr": {"applicationInstructions": [consigne]}}})


def _editx(type_="url", action=SANDER, **autres) -> str:
    data = {
        "status": "online",
        "openToApply": True,
        "applicationType": type_,
        "applicationAction": action,
        "locality": "La Hulpe",
        "onlineDate": {"value": "2026-10-13 06:41:14"},
    }
    data.update(autres)
    return json.dumps(data)


def _pages_temoin() -> dict:
    eures = EURES_API.format(id="AAA")
    return {
        eures: _rep(eures, _eures(EDITX_20200)),
        EDITX_API_20200: _rep(EDITX_API_20200, _editx()),
        SANDER: _rep(SANDER, "<html><title>Laravel developer</title></html>"),
    }


def _page(texte: str, code: int = 200) -> SimpleNamespace:
    return _rep(SANDER, texte, code)


def _vers(demandee: str, arrivee: str) -> dict:
    """Le témoin, dont EDITx mène à `demandee`, redirigée vers `arrivee` (200)."""
    pages = _pages_temoin()
    del pages[SANDER]
    pages[EDITX_API_20200] = _rep(EDITX_API_20200, _editx(action=demandee))
    pages[demandee] = _rep(
        arrivee, "<html><body>Jobs</body></html>", 200, via=[(demandee, 301)]
    )
    return pages


class Toile:
    """Une réponse par adresse ; une adresse inconnue ne répond pas (délai dépassé)."""

    def __init__(self, pages: dict) -> None:
        self.pages = dict(pages)

    def __call__(self, adresse: str):
        rep = self.pages.get(adresse)
        if rep is None:
            raise requests.exceptions.Timeout(adresse)
        if isinstance(rep, BaseException):
            raise rep
        return rep


def _simuler(monkeypatch, toile: Toile) -> None:
    reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    monkeypatch.setattr(reseau, "lire", toile)
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths, "PROFILE_PATH", chemin)


@pytest.fixture(autouse=True)
def codes_url(monkeypatch) -> dict:
    """`check_url` simulé : l'URL de l'offre et l'URL employeur répondent 200,
    sauf code posé par le test."""
    codes: dict[str, int | None] = {}

    def _check(url: str):
        return codes.get(url, 200), datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(expiration_service, "check_url", _check)
    return codes


@pytest.fixture
def client():
    import api.main as api_main

    with TestClient(api_main.app) as c:
        yield c


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(paths.DB_PATH)


def _offre(*, source="eures", source_id="AAA", url=TEMOIN_URL) -> int:
    _compteur["n"] += 1
    n = _compteur["n"]
    facts = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": "backend",
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    fetched = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, ad_language, "
            "extracted_facts_json, filtered_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                source,
                source_id,
                f"fp-218-{n}",
                "Développeur Python",
                f"Acme {n}",
                "Bruxelles",
                "directhire",
                url,
                fetched,
                "Poste de développeur Python dans une équipe produit. " * 10,
                "fr",
                facts,
            ),
        )
        return cur.lastrowid


def _verifier(client, *ids: int) -> None:
    r = client.post("/offers/check-expirations", json={"offer_ids": list(ids)})
    assert r.status_code == 204, r.text


def _file(client, oid: int) -> dict:
    r = client.get(f"/offers/{oid}/a-postuler")
    assert r.status_code == 200, r.text
    return r.json()


def _parcours(client, oid: int) -> dict:
    r = client.get(f"/offers/{oid}/parcours")
    assert r.status_code == 200, r.text
    return r.json()


def _temoin(client, monkeypatch, pages=None, **offre) -> int:
    _simuler(monkeypatch, Toile(pages if pages is not None else _pages_temoin()))
    oid = _offre(**offre)
    _verifier(client, oid)
    return oid


def _assert_fermee(client, oid: int, signe: str, site: str | None = None) -> dict:
    a = _file(client, oid)
    assert a["file"] is None
    assert a["motif"] == "annonce expirée"
    p = _parcours(client, oid)
    assert p.get("ouverture") == "fermée"
    assert (p.get("fermeture") or {}).get("signe") == signe
    if site is not None:
        assert (p.get("fermeture") or {}).get("site") == site
    return p


def _assert_reste(client, oid: int) -> None:
    a = _file(client, oid)
    assert a["file"] == "principale", a
    assert a["motif"] is None


# ---------------------------------------------------------------------------
# L'offre ouverte
# ---------------------------------------------------------------------------


class TestOuverte:
    def test_critere_1_temoin_dans_la_file_principale(self, client, monkeypatch):
        _assert_reste(client, _temoin(client, monkeypatch))

    def test_critere_2_ouverte_et_datee(self, client, monkeypatch):
        avant = datetime.now(timezone.utc)
        p = _parcours(client, _temoin(client, monkeypatch))
        assert p.get("ouverture") == "ouverte"
        verifiee = datetime.fromisoformat(p.get("verifiee_le") or "")
        assert avant <= verifiee <= datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# La source ne rend plus l'offre
# ---------------------------------------------------------------------------

SOURCE = "la source ne rend plus l'offre"


class TestSource:
    def _eures_404(self) -> dict:
        pages = _pages_temoin()
        eures = EURES_API.format(id="AAA")
        pages[eures] = _rep(eures, "", 404)
        return pages

    def test_critere_3_eures_404_hors_des_files(self, client, monkeypatch):
        oid = _temoin(client, monkeypatch, self._eures_404())
        a = _file(client, oid)
        assert a["file"] is None
        assert a["motif"] == "annonce expirée"

    def test_critere_4_signe_et_site_europa(self, client, monkeypatch):
        oid = _temoin(client, monkeypatch, self._eures_404())
        _assert_fermee(client, oid, SOURCE, "europa.eu")

    @pytest.mark.parametrize("code", [403, 404], ids=["critere_5", "critere_6"])
    def test_criteres_5_6_editx_403_404(self, client, monkeypatch, code):
        pages = _pages_temoin()
        pages[EDITX_API_20200] = _rep(EDITX_API_20200, "", code)
        oid = _temoin(client, monkeypatch, pages)
        _assert_fermee(client, oid, SOURCE, "editx.eu")

    def test_critere_7_editx_open_to_apply_faux(self, client, monkeypatch):
        pages = _pages_temoin()
        pages[EDITX_API_20200] = _rep(EDITX_API_20200, _editx(openToApply=False))
        oid = _temoin(client, monkeypatch, pages)
        _assert_fermee(client, oid, "EDITx n'accepte plus de candidature")

    def test_critere_8_actiris_offer_not_found(self, client, monkeypatch):
        page = (
            "<html><head><title>Offer not found | Actiris</title></head>"
            "<body><p>Cette offre n'est plus disponible.</p></body></html>"
        )
        pages = {ACTIRIS_URL: _rep(ACTIRIS_URL, page)}
        oid = _temoin(
            client,
            monkeypatch,
            pages,
            source="actiris",
            source_id="5977883",
            url=ACTIRIS_URL,
        )
        _assert_fermee(client, oid, SOURCE, "www.actiris.brussels")


# ---------------------------------------------------------------------------
# La page finale le dit
# ---------------------------------------------------------------------------

PHRASE = "la page dit que l'offre est fermée"
PROXIMUS = (
    "<html><head><title>Proximus careers</title></head><body>"
    "<h1>We're sorry… the job you are trying to apply for has been filled</h1>"
    "</body></html>"
)


class TestPageFinale:
    @pytest.mark.parametrize("code", [404, 410], ids=["critere_9", "critere_10"])
    def test_criteres_9_10_page_introuvable(self, client, monkeypatch, code):
        pages = _pages_temoin()
        pages[SANDER] = _page("", code)
        oid = _temoin(client, monkeypatch, pages)
        p = _assert_fermee(client, oid, "page introuvable")
        assert (p.get("fermeture") or {}).get("code") == code

    def _proximus(self) -> dict:
        pages = _pages_temoin()
        pages[SANDER] = _page(PROXIMUS)
        return pages

    def test_critere_11_has_been_filled(self, client, monkeypatch):
        oid = _temoin(client, monkeypatch, self._proximus())
        _assert_fermee(client, oid, PHRASE)

    def test_critere_12_phrase_rendue(self, client, monkeypatch):
        oid = _temoin(client, monkeypatch, self._proximus())
        assert (
            _parcours(client, oid).get("fermeture", {}).get("phrase")
            == "has been filled"
        )

    @pytest.mark.parametrize("phrase", PHRASES_H3)
    def test_critere_13_chacune_des_cinq_phrases(self, client, monkeypatch, phrase):
        pages = _pages_temoin()
        pages[SANDER] = _page(f"<html><body><p>Désolé : {phrase}.</p></body></html>")
        oid = _temoin(client, monkeypatch, pages)
        p = _assert_fermee(client, oid, PHRASE)
        assert (p.get("fermeture") or {}).get("phrase") == phrase

    def test_critere_13_les_cinq_phrases_vivent_dans_le_fichier(self):
        import yaml

        data = yaml.safe_load(
            (REPO / "profiles" / "a_postuler.yaml").read_text(encoding="utf-8")
        )
        assert data["parcours"].get("phrases_fermeture") == PHRASES_H3

    def test_critere_13_aucune_phrase_dans_le_code_de_la_verification(self):
        # Le code de la vérification : le parcours et l'expiration. Ailleurs,
        # « offer not found » est un message d'erreur de l'API, pas une phrase lue.
        code = "".join(
            f.read_text(encoding="utf-8").casefold()
            for dossier in ("parcours", "expiration")
            for f in (REPO / "orchestrator" / "job_search" / dossier).rglob("*.py")
        )
        assert [p for p in PHRASES_H3 if p in code] == []

    def test_critere_14_sans_casse(self, client, monkeypatch):
        pages = _pages_temoin()
        pages[SANDER] = _page("<html><body><b>NO LONGER AVAILABLE</b></body></html>")
        oid = _temoin(client, monkeypatch, pages)
        _assert_fermee(client, oid, PHRASE)

    def test_critere_15_phrase_dans_script_ou_style(self, client, monkeypatch):
        pages = _pages_temoin()
        pages[SANDER] = _page(
            "<html><head><style>.x:after{content:'has been filled'}</style>"
            '<script>var m = "no longer available";</script></head>'
            "<body><h1>Laravel developer</h1></body></html>"
        )
        oid = _temoin(client, monkeypatch, pages)
        _assert_reste(client, oid)
        assert _parcours(client, oid).get("ouverture") == "ouverte"


# ---------------------------------------------------------------------------
# Le renvoi vers une autre page
# ---------------------------------------------------------------------------

RENVOI = "renvoi vers une autre page"
SANDER_JOBS = "https://www.wearesander.com/en/jobs"


class TestRenvoi:
    def test_critere_16_sander_vers_la_liste(self, client, monkeypatch):
        oid = _temoin(client, monkeypatch, _vers(SANDER_PROPRE, SANDER_JOBS))
        _assert_fermee(client, oid, RENVOI)

    def test_critere_17_fin_et_cle_restent_l_adresse_demandee(
        self, client, monkeypatch
    ):
        oid = _temoin(client, monkeypatch, _vers(SANDER, SANDER_JOBS))
        p = _parcours(client, oid)
        assert p["fin"]["adresse"] == SANDER_PROPRE
        assert p["cle"] == SANDER_PROPRE

    def test_critere_18_meme_numero_reste_ouverte(self, client, monkeypatch):
        arrivee = "https://www.wearesander.com/en/jobs/laravel-developer/87727"
        oid = _temoin(client, monkeypatch, _vers(SANDER_PROPRE, arrivee))
        _assert_reste(client, oid)
        assert _parcours(client, oid).get("ouverture") == "ouverte"

    def test_critere_19_actiris_reference_gardee(self, client, monkeypatch):
        demandee = (
            "https://www.actiris.brussels/fr/citoyens/detail-offre-demploi/"
            "?reference=5994360&type=Hrxml"
        )
        arrivee = (
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/"
            "?reference=5994360&type=Hrxml"
        )
        oid = _temoin(client, monkeypatch, _vers(demandee, arrivee))
        _assert_reste(client, oid)
        assert _parcours(client, oid).get("ouverture") == "ouverte"

    def test_critere_20_jobat_vers_la_liste(self, client, monkeypatch):
        demandee = "https://www.jobat.be/fr/emplois/jobdetail/job_6485041?action=apply"
        arrivee = "https://www.jobat.be/fr/emplois"
        oid = _temoin(client, monkeypatch, _vers(demandee, arrivee))
        _assert_fermee(client, oid, RENVOI)

    def test_critere_21_adresse_sans_numero(self, client, monkeypatch):
        demandee = "https://taleez.com/apply/ai-expert"
        oid = _temoin(client, monkeypatch, _vers(demandee, "https://taleez.com/jobs"))
        _assert_reste(client, oid)
        assert _parcours(client, oid).get("ouverture") == "ouverte"


# ---------------------------------------------------------------------------
# Ce qui ne ferme pas
# ---------------------------------------------------------------------------


class TestNeFermePas:
    @pytest.mark.parametrize(
        ("editx", "forme"),
        [
            (_editx(type_="email", action="jobs@exemple.be"), "mail"),
            (_editx(type_="editx", action=None), "formulaire"),
            (_editx(action="https://www.ama.be/"), "accueil"),
        ],
        ids=["critere_22", "critere_23", "critere_24"],
    )
    def test_criteres_22_23_24_non_verifiable(self, client, monkeypatch, editx, forme):
        pages = _pages_temoin()
        pages[EDITX_API_20200] = _rep(EDITX_API_20200, editx)
        pages["https://www.ama.be/"] = _rep("https://www.ama.be/", "<html>AMA</html>")
        oid = _temoin(client, monkeypatch, pages)
        _assert_reste(client, oid)
        p = _parcours(client, oid)
        assert p["fin"]["forme"] == forme
        assert p.get("ouverture") == "non vérifiable"

    @pytest.mark.parametrize(
        "reponse",
        [
            _page("Forbidden", 403),
            requests.exceptions.Timeout("sander"),
            _page("Erreur", 500),
        ],
        ids=["critere_25", "critere_26", "critere_27"],
    )
    def test_criteres_25_26_27_refus_panne_erreur(self, client, monkeypatch, reponse):
        pages = _pages_temoin()
        pages[SANDER] = reponse
        _assert_reste(client, _temoin(client, monkeypatch, pages))

    def test_critere_28_fermee_puis_403_reste_fermee(self, client, monkeypatch):
        pages = _pages_temoin()
        pages[SANDER] = _page("", 404)
        toile = Toile(pages)
        _simuler(monkeypatch, toile)
        oid = _offre()
        _verifier(client, oid)
        assert _file(client, oid)["file"] is None
        toile.pages[SANDER] = _page("Forbidden", 403)
        _verifier(client, oid)
        a = _file(client, oid)
        assert a["file"] is None
        assert a["motif"] == "annonce expirée"


# ---------------------------------------------------------------------------
# La réouverture
# ---------------------------------------------------------------------------


class TestReouverture:
    def _fermee_puis_temoin(self, client, monkeypatch) -> int:
        pages = _pages_temoin()
        pages[SANDER] = _page(PROXIMUS)
        toile = Toile(pages)
        _simuler(monkeypatch, toile)
        oid = _offre()
        _verifier(client, oid)
        assert _parcours(client, oid).get("ouverture") == "fermée"
        toile.pages = _pages_temoin()
        _verifier(client, oid)
        return oid

    def test_critere_29_revient_dans_la_file(self, client, monkeypatch):
        _assert_reste(client, self._fermee_puis_temoin(client, monkeypatch))

    def test_critere_30_ouverte_sans_signe(self, client, monkeypatch):
        p = _parcours(client, self._fermee_puis_temoin(client, monkeypatch))
        assert p.get("ouverture") == "ouverte"
        assert p.get("fermeture", "absent") is None


# ---------------------------------------------------------------------------
# Les offres retenues
# ---------------------------------------------------------------------------


def _retenir(oid: int) -> None:
    with _conn() as conn:
        suivi_storage.appliquer_geste(
            conn, oid, suivi_etats.RETENIR, effet_at="2026-11-27"
        )


class TestRetenues:
    def test_critere_31_sans_corps_parcours_des_retenues(self, client, monkeypatch):
        pages = _pages_temoin()
        eures = EURES_API.format(id="AAA")
        pages[eures] = _rep(eures, "", 404)
        _simuler(monkeypatch, Toile(pages))
        oid = _offre()
        _retenir(oid)
        assert client.post("/offers/check-expirations").status_code == 204
        assert client.get(f"/offers/{oid}").json()["expired"] is True

    def test_critere_32_url_employeur_410(self, client, monkeypatch, codes_url):
        _simuler(monkeypatch, Toile(_pages_temoin()))
        oid = _offre()
        _retenir(oid)
        employeur = "https://exemple.be/carrieres/poste-1234"
        r = client.put(f"/offers/{oid}/employer-url", json={"url": employeur})
        assert r.status_code == 204, r.text
        codes_url[employeur] = 410
        assert client.post("/offers/check-expirations").status_code == 204
        assert client.get(f"/offers/{oid}").json()["expired"] is True


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver
# ---------------------------------------------------------------------------


class TestInterdits:
    def test_fermeture_ne_change_ni_l_offre_ni_son_tri(self, client, monkeypatch):
        pages = _pages_temoin()
        pages[SANDER] = _page("", 410)
        _simuler(monkeypatch, Toile(pages))
        oid = _offre()
        with _conn() as conn:
            avant = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
            tri_avant = suivi_storage.tri(conn, oid)
        _verifier(client, oid)
        with _conn() as conn:
            apres = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
            assert suivi_storage.tri(conn, oid) == tri_avant
        assert apres == avant
        assert _parcours(client, oid).get("ouverture") == "fermée"
