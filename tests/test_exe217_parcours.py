"""Tests EXE-217 — le parcours de candidature, jusqu'à l'endroit où l'on postule.

Aucun test n'appelle un site : chaque réponse est simulée en remplaçant le point
d'appel réseau du parcours (`parcours.reseau.lire`) et `check_url` de la
vérification d'expiration. Chaque test pose sa base dans un dossier temporaire
(fixture `_isolate_db_path` de conftest.py). Chaque critère change une seule
chose à l'offre témoin.

Le parcours se lance par POST /offers/check-expirations et se lit par
GET /offers/{id}/parcours. Les modules neufs ne s'importent qu'à l'intérieur des
aides : contre le code d'avant ce ticket, les tests échouent sur une assertion,
jamais sur une erreur d'import.
"""

import importlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths
from orchestrator.job_search.expiration import service as expiration_service
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EDITX_API = "https://api.editx.eu/en/api/editx/job/{num}"

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

_compteur = {"n": 0}


# ---------------------------------------------------------------------------
# Réponses simulées
# ---------------------------------------------------------------------------


def _rep(adresse: str, texte: str = "", code: int = 200, via=()) -> SimpleNamespace:
    """Une réponse : la chaîne des adresses traversées (redirections comprises)
    avec leur code, et le texte de la dernière."""
    return SimpleNamespace(chaine=[*via, (adresse, code)], texte=texte)


def _eures(liens: list[str]) -> str:
    consignes = [
        f'<p>Postulez <a href="{lien.replace("&", "&amp;")}">ici</a></p>'
        for lien in liens
    ]
    return json.dumps(
        {
            "creationDate": 1760000000000,
            "jvProfiles": {
                "fr": {
                    "title": "Laravel developer",
                    "employer": {"name": "Sander"},
                    "applicationInstructions": consignes,
                }
            },
        }
    )


def _editx(type_="url", action=SANDER, **autres) -> str:
    data = {
        "status": "online",
        "openToApply": True,
        "applicationType": type_,
        "locality": "La Hulpe",
        "postalCode": " 1310",
        "areas": [{"id": 1, "label": "Namur"}, {"id": 2, "label": "Walloon Brabant"}],
        "onlineDate": {"value": "2026-10-13 06:41:14"},
    }
    if action is not None:
        data["applicationAction"] = action
    data.update(autres)
    return json.dumps(data)


def _actiris(ligne: str | None, bouton_avant: bool = False) -> str:
    bouton = (
        '<a class="btn" href="https://my.actiris.brussels/citizen/joboffer/5977883">'
        "Postuler</a>"
    )
    if ligne is None:
        return "<html><body><div class='offre'>Rien</div></body></html>"
    return (
        '<html><body><div class="bloc-emploi__apply">'
        "<h2>Comment postuler ?</h2>"
        + (bouton if bouton_avant else "")
        + f"<table><tbody>{ligne}</tbody></table>"
        + ("" if bouton_avant else bouton)
        + "</div></body></html>"
    )


def _ligne_website(lien: str) -> str:
    return (
        f'<tr><th>Website</th><td><a href="{lien}">Site de l\'employeur</a></td></tr>'
    )


def _ligne_mail(adresse: str) -> str:
    return f'<tr><th>E-mail</th><td><a href="mailto:{adresse}">{adresse}</a></td></tr>'


class Toile:
    """Double du point d'appel réseau : une réponse par adresse ; une adresse
    inconnue ne répond pas (délai dépassé)."""

    def __init__(self, pages: dict) -> None:
        self.pages = dict(pages)
        self.demandes: list[str] = []

    def __call__(self, adresse: str):
        self.demandes.append(adresse)
        rep = self.pages.get(adresse)
        if rep is None:
            raise requests.exceptions.Timeout(adresse)
        if isinstance(rep, BaseException):
            raise rep
        return rep


def _pages_temoin() -> dict:
    return {
        EURES_API.format(id="AAA"): _rep(
            EURES_API.format(id="AAA"), _eures([EDITX_20200])
        ),
        EDITX_API.format(num=20200): _rep(EDITX_API.format(num=20200), _editx()),
        SANDER: _rep(SANDER),
    }


def _simuler(monkeypatch, toile: Toile, attentes: list | None = None) -> None:
    """Remplace le point d'appel réseau du parcours et son attente. Contre le
    code d'avant ce ticket, le module n'existe pas : rien à remplacer."""
    try:
        reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    except ImportError:
        return
    monkeypatch.setattr(reseau, "lire", toile)
    monkeypatch.setattr(
        reseau,
        "attendre",
        attentes.append if attentes is not None else (lambda secondes: None),
    )


@pytest.fixture(autouse=True)
def _expiration_simulee(monkeypatch):
    """La vérification d'expiration ne sort pas non plus : chaque adresse répond 200."""
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


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(paths.DB_PATH)


def _offre(
    *,
    source="eures",
    source_id="AAA",
    url=TEMOIN_URL,
    title="Laravel developer",
    location="Belgique",
    domain="backend",
    company=None,
) -> int:
    _compteur["n"] += 1
    n = _compteur["n"]
    company = company if company is not None else f"Acme {n}"
    facts = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": "php", "importance": "core"}],
            "domain": domain,
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
                f"fp-{n}",
                title,
                company,
                location,
                "directhire",
                url,
                fetched,
                "Poste de développeur PHP dans une équipe produit. " * 10,
                "fr",
                facts,
            ),
        )
        return cur.lastrowid


def _lire(client, *ids: int) -> None:
    r = client.post("/offers/check-expirations", json={"offer_ids": list(ids)})
    assert r.status_code == 204, r.text


def _parcours(client, offer_id: int) -> dict:
    r = client.get(f"/offers/{offer_id}/parcours")
    assert r.status_code == 200, r.text
    return r.json()


def _lire_temoin(client, monkeypatch, pages=None) -> dict:
    toile = Toile(pages if pages is not None else _pages_temoin())
    _simuler(monkeypatch, toile)
    oid = _offre()
    _lire(client, oid)
    return _parcours(client, oid)


# ---------------------------------------------------------------------------
# Le parcours du témoin
# ---------------------------------------------------------------------------


class TestParcoursTemoin:
    def test_critere_1_trois_maillons_dans_l_ordre(self, client, monkeypatch):
        p = _lire_temoin(client, monkeypatch)
        assert [m["site"] for m in p["maillons"]] == [
            "europa.eu",
            "editx.eu",
            "www.wearesander.com",
        ]

    def test_critere_2_adresse_demandee_et_code(self, client, monkeypatch):
        p = _lire_temoin(client, monkeypatch)
        assert [(m["adresse"], m["reponse"]) for m in p["maillons"]] == [
            (EURES_API.format(id="AAA"), 200),
            (EDITX_API.format(num=20200), 200),
            (SANDER, 200),
        ]

    def test_critere_3_fin_page(self, client, monkeypatch):
        assert _lire_temoin(client, monkeypatch)["fin"]["forme"] == "page"

    def test_critere_4_adresse_de_fin_sans_utm(self, client, monkeypatch):
        p = _lire_temoin(client, monkeypatch)
        assert p["fin"]["adresse"] == SANDER_PROPRE
        assert "utm_" not in p["fin"]["adresse"]

    def test_critere_5_cle_est_l_adresse_de_fin(self, client, monkeypatch):
        assert _lire_temoin(client, monkeypatch)["cle"] == SANDER_PROPRE

    def test_critere_6_lieu_reel(self, client, monkeypatch):
        assert _lire_temoin(client, monkeypatch)["lieu_reel"] == "La Hulpe"

    def test_critere_7_code_postal_et_provinces(self, client, monkeypatch):
        p = _lire_temoin(client, monkeypatch)
        assert p["code_postal"] == "1310"
        assert p["provinces"] == ["Namur", "Walloon Brabant"]

    def test_critere_8_date_de_mise_en_ligne(self, client, monkeypatch):
        assert _lire_temoin(client, monkeypatch)["en_ligne_depuis"] == "2026-10-13"

    def test_critere_9_date_et_heure_de_lecture(self, client, monkeypatch):
        avant = datetime.now(timezone.utc)
        p = _lire_temoin(client, monkeypatch)
        assert p["etat"] == "lu"
        lu_le = datetime.fromisoformat(p["lu_le"])
        assert avant <= lu_le <= datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Les autres fins chez EDITx
# ---------------------------------------------------------------------------


def _pages_editx(num: int, editx_json: str) -> dict:
    annonce = f"https://editx.eu/fr/job/{num}/poste?utm_source=vdab"
    return {
        EURES_API.format(id="AAA"): _rep(EURES_API.format(id="AAA"), _eures([annonce])),
        EDITX_API.format(num=num): _rep(EDITX_API.format(num=num), editx_json),
    }


class TestFinsEditx:
    def test_critere_10_fin_mail(self, client, monkeypatch):
        pages = _pages_editx(
            6167, _editx(type_="email", action="c.brabant@connect-people.eu")
        )
        p = _lire_temoin(client, monkeypatch, pages)
        assert p["fin"] == {"forme": "mail", "adresse": "c.brabant@connect-people.eu"}

    def test_critere_11_cle_editx_mail(self, client, monkeypatch):
        pages = _pages_editx(
            6167, _editx(type_="email", action="c.brabant@connect-people.eu")
        )
        assert _lire_temoin(client, monkeypatch, pages)["cle"] == "editx:6167"

    def test_critere_12_fin_formulaire(self, client, monkeypatch):
        pages = _pages_editx(13187, _editx(type_="editx", action=None))
        p = _lire_temoin(client, monkeypatch, pages)
        assert p["fin"] == {
            "forme": "formulaire",
            "adresse": "https://editx.eu/fr/job/13187/poste",
        }

    def test_critere_13_cle_editx_formulaire(self, client, monkeypatch):
        pages = _pages_editx(13187, _editx(type_="editx", action=None))
        assert _lire_temoin(client, monkeypatch, pages)["cle"] == "editx:13187"


# ---------------------------------------------------------------------------
# Actiris
# ---------------------------------------------------------------------------


def _lire_actiris(client, monkeypatch, page_html: str, autres: dict | None = None):
    pages = {ACTIRIS_URL: _rep(ACTIRIS_URL, page_html)}
    pages.update(autres or {})
    toile = Toile(pages)
    _simuler(monkeypatch, toile)
    oid = _offre(
        source="actiris", source_id="5977883", url=ACTIRIS_URL, location="Bruxelles"
    )
    _lire(client, oid)
    return _parcours(client, oid), toile


class TestActiris:
    def _editx_sander(self) -> dict:
        pages = _pages_temoin()
        del pages[EURES_API.format(id="AAA")]
        return pages

    def test_critere_14_trois_maillons(self, client, monkeypatch):
        lien = "https://editx.eu/en/job/20200/laravel-developer?utm_source=vdab"
        p, _ = _lire_actiris(
            client, monkeypatch, _actiris(_ligne_website(lien)), self._editx_sander()
        )
        assert [m["site"] for m in p["maillons"]] == [
            "www.actiris.brussels",
            "editx.eu",
            "www.wearesander.com",
        ]

    def test_critere_15_meme_cle_que_le_temoin(self, client, monkeypatch):
        temoin = _lire_temoin(client, monkeypatch)
        lien = "https://editx.eu/en/job/20200/laravel-developer?utm_source=vdab"
        p, _ = _lire_actiris(
            client, monkeypatch, _actiris(_ligne_website(lien)), self._editx_sander()
        )
        assert p["cle"] is not None
        assert p["cle"] == temoin["cle"]

    def test_critere_16_fin_mail(self, client, monkeypatch):
        p, _ = _lire_actiris(
            client, monkeypatch, _actiris(_ligne_mail("sabilgo47@gmail.com"))
        )
        assert p["fin"] == {"forme": "mail", "adresse": "sabilgo47@gmail.com"}
        assert p["cle"] == "actiris:5977883"

    def test_critere_17_fin_accueil(self, client, monkeypatch):
        accueil = "https://ice-berry.com/"
        p, _ = _lire_actiris(
            client,
            monkeypatch,
            _actiris(_ligne_website(accueil)),
            {accueil: _rep(accueil)},
        )
        assert p["fin"]["forme"] == "accueil"
        assert p["cle"] == "actiris:5977883"

    def test_critere_18_fin_page_sans_cid(self, client, monkeypatch):
        lien = (
            "https://www.ictjob.be/fr/emploi/smals-kotlin-developer/1-343063"
            "?cid=Partner_Actiris"
        )
        p, _ = _lire_actiris(
            client, monkeypatch, _actiris(_ligne_website(lien)), {lien: _rep(lien)}
        )
        assert p["fin"] == {
            "forme": "page",
            "adresse": "https://www.ictjob.be/fr/emploi/smals-kotlin-developer/1-343063",
        }

    def test_critere_19_page_sans_bloc(self, client, monkeypatch):
        p, _ = _lire_actiris(client, monkeypatch, _actiris(None))
        assert len(p["maillons"]) == 1
        assert p["fin"]["forme"] == "inconnue"
        assert p["cle"] is None

    def test_critere_20_bouton_jamais_pris(self, client, monkeypatch):
        lien = "https://www.ictjob.be/fr/emploi/kotlin/1-343063"
        p, toile = _lire_actiris(
            client,
            monkeypatch,
            _actiris(_ligne_website(lien), bouton_avant=True),
            {lien: _rep(lien)},
        )
        assert p["fin"]["adresse"] == lien
        assert not any("my.actiris.brussels" in d for d in toile.demandes)
        assert not any("my.actiris.brussels" in m["adresse"] for m in p["maillons"])

    def test_critere_20_bouton_seul_n_est_pas_un_lien(self, client, monkeypatch):
        page = (
            '<div class="bloc-emploi__apply"><h2>Comment postuler ?</h2>'
            '<a href="https://my.actiris.brussels/citizen/joboffer/5977883">Postuler</a>'
            "<table><tbody></tbody></table></div>"
        )
        p, toile = _lire_actiris(client, monkeypatch, page)
        assert p["etat"] == "lu"
        assert p["fin"]["forme"] == "inconnue"
        assert toile.demandes == [ACTIRIS_URL]


# ---------------------------------------------------------------------------
# EURES sans lien, autres sources
# ---------------------------------------------------------------------------


class TestEuresSansLien:
    def test_critere_21_consignes_vides(self, client, monkeypatch):
        pages = {
            EURES_API.format(id="AAA"): _rep(EURES_API.format(id="AAA"), _eures([]))
        }
        p = _lire_temoin(client, monkeypatch, pages)
        assert p["etat"] == "lu"
        assert len(p["maillons"]) == 1
        assert p["fin"]["forme"] == "inconnue"
        assert p["cle"] is None


class TestAutresSources:
    def test_critere_22_manuel_page(self, client, monkeypatch):
        adresse = "https://taleez.com/apply/ai-expert"
        _simuler(monkeypatch, Toile({adresse: _rep(adresse)}))
        oid = _offre(source="manuel", source_id="m-1", url=adresse)
        _lire(client, oid)
        p = _parcours(client, oid)
        assert len(p["maillons"]) == 1
        assert p["fin"] == {"forme": "page", "adresse": adresse}

    def test_critere_23_sans_adresse(self, client, monkeypatch):
        _simuler(monkeypatch, Toile({}))
        oid = _offre(source="manuel", source_id="m-2", url=None)
        _lire(client, oid)
        p = _parcours(client, oid)
        assert p["etat"] == "sans lien"
        assert p["maillons"] == []

    def test_critere_24_sans_adresse_aucune_requete(self, client, monkeypatch):
        toile = Toile({})
        _simuler(monkeypatch, toile)
        oid = _offre(source="manuel", source_id="m-3", url=None)
        _lire(client, oid)
        assert _parcours(client, oid)["etat"] == "sans lien"
        assert toile.demandes == []


# ---------------------------------------------------------------------------
# Les redirections
# ---------------------------------------------------------------------------


class TestRedirections:
    JOBAT = (
        "https://www.jobat.be/fr/emplois/jobdetail/job_6485041"
        "?action=apply&utm_source=actiris"
    )
    YPTO = "https://careers.ypto.be/job/6485041"

    def _lire(self, client, monkeypatch) -> dict:
        rep = _rep(self.YPTO, via=[(self.JOBAT, 302)])
        _simuler(monkeypatch, Toile({self.JOBAT: rep}))
        oid = _offre(source="manuel", source_id="m-4", url=self.JOBAT)
        _lire(client, oid)
        return _parcours(client, oid)

    def test_critere_25_adresse_d_arrivee(self, client, monkeypatch):
        assert self._lire(client, monkeypatch)["fin"]["adresse"] == self.YPTO

    def test_critere_26_un_maillon_par_adresse(self, client, monkeypatch):
        p = self._lire(client, monkeypatch)
        assert [(m["adresse"], m["reponse"]) for m in p["maillons"]] == [
            (self.JOBAT, 302),
            (self.YPTO, 200),
        ]


# ---------------------------------------------------------------------------
# Le nettoyage des adresses
# ---------------------------------------------------------------------------


def _cle_de(client, monkeypatch, adresse: str) -> str | None:
    _simuler(monkeypatch, Toile({adresse: _rep(adresse)}))
    _compteur["n"] += 1
    oid = _offre(source="manuel", source_id=f"net-{_compteur['n']}", url=adresse)
    _lire(client, oid)
    return _parcours(client, oid)["cle"]


class TestNettoyage:
    def test_critere_27_utm_retires(self, client, monkeypatch):
        a = _cle_de(
            client,
            monkeypatch,
            "https://exemple.be/offre/1?utm_source=a&utm_medium=b&utm_campaign=c",
        )
        b = _cle_de(client, monkeypatch, "https://exemple.be/offre/1?utm_source=x")
        assert a is not None
        assert a == b == "https://exemple.be/offre/1"

    @pytest.mark.parametrize("parametre", ["cid", "trid", "oga", "gclid", "fbclid"])
    def test_critere_28_autres_parametres_de_suivi(
        self, client, monkeypatch, parametre
    ):
        cle = _cle_de(
            client, monkeypatch, f"https://exemple.be/offre/2?{parametre}=123"
        )
        assert cle == "https://exemple.be/offre/2"

    def test_critere_29_parametre_garde(self, client, monkeypatch):
        adresse = "https://exemple.be/offre?reference=5994360&type=Hrxml"
        assert _cle_de(client, monkeypatch, adresse) == adresse

    def test_critere_30_casse_et_barre_finale(self, client, monkeypatch):
        a = _cle_de(client, monkeypatch, "https://WWW.Wearesander.com/fr/jobs/a/87727/")
        b = _cle_de(client, monkeypatch, "https://www.wearesander.com/fr/jobs/a/87727")
        assert a is not None
        assert a == b


# ---------------------------------------------------------------------------
# Lire, relire, ne pas lire
# ---------------------------------------------------------------------------


def _retenir(offer_id: int) -> None:
    with _conn() as conn:
        suivi_storage.appliquer_geste(
            conn, offer_id, suivi_etats.RETENIR, effet_at="2026-11-27"
        )


class TestLireRelire:
    def test_critere_31_jamais_lu(self, client):
        oid = _offre()
        r = client.get(f"/offers/{oid}/parcours")
        assert r.status_code == 200
        assert r.json()["etat"] == "jamais lu"

    def test_critere_32_seconde_lecture_remplace(self, client, monkeypatch):
        _simuler(monkeypatch, Toile(_pages_temoin()))
        oid = _offre()
        _lire(client, oid)
        premiere = _parcours(client, oid)["lu_le"]
        _lire(client, oid)
        seconde = _parcours(client, oid)["lu_le"]
        assert premiere is not None
        assert seconde > premiere

    def test_critere_33_seulement_les_offres_designees(self, client, monkeypatch):
        pages = {}
        ids = []
        for i in range(3):
            adresse = f"https://exemple.be/offre/{i}"
            pages[adresse] = _rep(adresse)
            ids.append(_offre(source="manuel", source_id=f"d-{i}", url=adresse))
        _simuler(monkeypatch, Toile(pages))
        _lire(client, ids[0], ids[1])
        assert [_parcours(client, i)["etat"] for i in ids] == ["lu", "lu", "jamais lu"]

    def test_critere_34_sans_corps_les_retenues(self, client, monkeypatch):
        pages = {}
        ids = []
        for i in range(2):
            adresse = f"https://exemple.be/retenue/{i}"
            pages[adresse] = _rep(adresse)
            ids.append(_offre(source="manuel", source_id=f"r-{i}", url=adresse))
        _retenir(ids[0])
        _simuler(monkeypatch, Toile(pages))
        r = client.post("/offers/check-expirations")
        assert r.status_code == 204
        assert _parcours(client, ids[0])["etat"] == "lu"
        assert _parcours(client, ids[1])["etat"] == "jamais lu"

    def test_critere_35_offre_inconnue(self, client):
        assert client.get("/offers/987654/parcours").status_code == 404


# ---------------------------------------------------------------------------
# Les pannes
# ---------------------------------------------------------------------------


class TestPannes:
    def _pages_editx_muet(self) -> dict:
        pages = _pages_temoin()
        pages[EDITX_API.format(num=20200)] = requests.exceptions.Timeout("editx")
        return pages

    def test_critere_36_editx_injoignable(self, client, monkeypatch):
        p = _lire_temoin(client, monkeypatch, self._pages_editx_muet())
        assert len(p["maillons"]) == 2
        assert p["maillons"][1]["reponse"] == "injoignable"
        assert p["fin"]["forme"] == "inconnue"

    def test_critere_37_fin_et_cle_gardees(self, client, monkeypatch):
        toile = Toile(_pages_temoin())
        _simuler(monkeypatch, toile)
        oid = _offre()
        _lire(client, oid)
        avant = _parcours(client, oid)
        toile.pages = self._pages_editx_muet()
        _lire(client, oid)
        apres = _parcours(client, oid)
        assert avant["fin"] == {"forme": "page", "adresse": SANDER_PROPRE}
        assert apres["fin"] == avant["fin"]
        assert apres["cle"] == avant["cle"] == SANDER_PROPRE
        assert apres["maillons"][1]["reponse"] == "injoignable"

    def test_critere_38_panne_n_arrete_pas_les_suivantes(self, client, monkeypatch):
        bonne = "https://exemple.be/bonne"
        pages = {
            "https://exemple.be/casse": RuntimeError("panne inattendue"),
            "https://exemple.be/muette": requests.exceptions.ConnectionError("x"),
            bonne: _rep(bonne),
        }
        _simuler(monkeypatch, Toile(pages))
        casse = _offre(source="manuel", source_id="p-1", url="https://exemple.be/casse")
        muette = _offre(
            source="manuel", source_id="p-2", url="https://exemple.be/muette"
        )
        suivante = _offre(source="manuel", source_id="p-3", url=bonne)
        _lire(client, casse, muette, suivante)
        assert _parcours(client, muette)["etat"] == "lu"
        p = _parcours(client, suivante)
        assert p["etat"] == "lu"
        assert p["fin"]["forme"] == "page"


# ---------------------------------------------------------------------------
# La politesse
# ---------------------------------------------------------------------------


class TestPolitesse:
    def test_critere_39_demi_seconde_entre_deux_requetes_du_meme_site(
        self, client, monkeypatch
    ):
        a = "https://exemple.be/offre/a"
        b = "https://exemple.be/offre/b"
        attentes: list[float] = []
        _simuler(monkeypatch, Toile({a: _rep(a), b: _rep(b)}), attentes)
        oa = _offre(source="manuel", source_id="pol-a", url=a)
        ob = _offre(source="manuel", source_id="pol-b", url=b)
        _lire(client, oa, ob)
        assert _parcours(client, ob)["etat"] == "lu"
        assert len(attentes) == 1
        assert 0.4 < attentes[0] <= 0.5


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver
# ---------------------------------------------------------------------------


class TestInterdits:
    def test_garde_fou_le_point_d_appel_reseau_echoue_sans_simulation(self):
        try:
            reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
        except ImportError:
            pytest.fail("point d'appel réseau du parcours absent")
        with pytest.raises(Exception) as exc:
            reseau.lire("https://exemple.be/")
        assert not isinstance(exc.value, requests.exceptions.RequestException)

    def test_le_point_d_appel_reseau_ne_fait_que_des_get(self, monkeypatch):
        try:
            reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
        except ImportError:
            pytest.fail("point d'appel réseau du parcours absent")
        appels = []

        def _get(url, **kwargs):
            appels.append((url, kwargs))
            return SimpleNamespace(
                history=[SimpleNamespace(url=url, status_code=301)],
                url="https://exemple.be/fin",
                status_code=200,
                text="ok",
            )

        def _interdit(*args, **kwargs):
            raise AssertionError("seul GET est permis")

        monkeypatch.setattr(reseau.requests, "get", _get)
        for verbe in ("post", "put", "patch", "delete", "request"):
            monkeypatch.setattr(reseau.requests, verbe, _interdit)
        rep = reseau.envoyer_get("https://exemple.be/debut")
        assert rep.chaine == [
            ("https://exemple.be/debut", 301),
            ("https://exemple.be/fin", 200),
        ]
        assert rep.texte == "ok"
        assert appels[0][1]["allow_redirects"] is True
        assert appels[0][1]["timeout"] == 15

    def test_aucun_champ_de_l_offre_reecrit(self, client, monkeypatch):
        _simuler(monkeypatch, Toile(_pages_temoin()))
        oid = _offre()
        with _conn() as conn:
            avant = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
        _lire(client, oid)
        assert _parcours(client, oid)["lieu_reel"] == "La Hulpe"
        with _conn() as conn:
            apres = conn.execute("SELECT * FROM offers WHERE id = ?", (oid,)).fetchone()
        assert apres == avant

    def test_rien_d_invente_quand_le_site_ne_le_donne_pas(self, client, monkeypatch):
        adresse = "https://taleez.com/apply/ai-expert"
        _simuler(monkeypatch, Toile({adresse: _rep(adresse)}))
        oid = _offre(source="manuel", source_id="inv-1", url=adresse)
        _lire(client, oid)
        p = _parcours(client, oid)
        assert p["etat"] == "lu"
        assert (
            p["lieu_reel"],
            p["code_postal"],
            p["provinces"],
            p["en_ligne_depuis"],
        ) == (
            None,
            None,
            [],
            None,
        )

    def test_editx_sans_code_postal_reste_vide(self, client, monkeypatch):
        pages = _pages_temoin()
        data = json.loads(_editx())
        del data["postalCode"]
        pages[EDITX_API.format(num=20200)] = _rep(
            EDITX_API.format(num=20200), json.dumps(data)
        )
        p = _lire_temoin(client, monkeypatch, pages)
        assert p["code_postal"] is None
        assert p["lieu_reel"] == "La Hulpe"

    def test_parametres_de_suivi_lus_dans_le_fichier(
        self, client, monkeypatch, tmp_path
    ):
        regles = tmp_path / "a_postuler.yaml"
        texte = paths.A_POSTULER_PATH.read_text(encoding="utf-8")
        regles.write_text(
            texte.replace("- cid\n", "- cid\n      - ref\n"), encoding="utf-8"
        )
        assert "- ref\n" in regles.read_text(encoding="utf-8")
        monkeypatch.setattr(paths, "A_POSTULER_PATH", regles)
        cle = _cle_de(client, monkeypatch, "https://exemple.be/offre/3?ref=x&id=4")
        assert cle == "https://exemple.be/offre/3?id=4"

    def test_aucune_lecture_au_demarrage_ni_a_l_affichage(self, client, monkeypatch):
        toile = Toile(_pages_temoin())
        _simuler(monkeypatch, toile)
        oid = _offre()
        _retenir(oid)
        import api.main as api_main

        with TestClient(api_main.app) as autre:
            autre.get("/a-postuler")
            autre.get("/a-postuler", params={"file": "a_etudier"})
            autre.get(f"/offers/{oid}/parcours")
        assert toile.demandes == []
        assert _parcours(client, oid)["etat"] == "jamais lu"
