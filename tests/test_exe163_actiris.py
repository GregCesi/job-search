"""Tests EXE-163 — les offres informatiques bruxelloises d'Actiris entrent dans
le run avec leur texte complet.

Aucun test n'appelle actiris.brussels : `requests.post`/`requests.get` sont
remplacés par des doublures qui rendent une réponse de liste JSON et une page
de détail HTML enregistrées ci-dessous. Aucun test ne lit ni n'écrit sous
data/ : base, profil et REPO_ROOT (run) sont en tmp_path.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

import api.db as api_db
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.sources.actiris as actiris
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.sources.actiris import ActirisSource
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.sources.fingerprint import fingerprint
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.dedup import filter_new
from orchestrator.job_search.storage.offers import save_offer

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures de doublure réseau — formes relevées sur le site le 9 octobre 2026
# ---------------------------------------------------------------------------


def _list_item(
    reference: str,
    *,
    code_postal: str = "1000",
    code_domaine: str = "Q'3",
    titre_fr: str = "Développeur Python",
    titre_nl: str = "",
    type_offer: str = "Hrxml",
    commune_fr: str = "Bruxelles",
    commune_nl: str = "Brussel",
    date_modification: str = "2026-10-09T00:00:00+02:00",
) -> dict:
    return {
        "reference": reference,
        "codeDomaineImt": code_domaine,
        "codePostal": code_postal,
        "employer": None,
        "regimeTravail": "NO",
        "titreFr": titre_fr,
        "titreNl": titre_nl,
        "typeContrat": "CDI",
        "typeOffer": type_offer,
        "codePays": "BE",
        "communeFr": commune_fr,
        "communeNl": commune_nl,
        "numeroEntreprise": "0860737913",
        "typeContratLibelle": "Durée indéterminée",
        "dateCreation": date_modification,
        "dateModification": date_modification,
    }


def _detail_html(
    *,
    h1: str = "AG Insurance - AI Data Engineer H/F/X",
    entreprise: str = "<p>Chez AG, nous voulons faire la différence.</p>",
    fonction: str = (
        "<p>Concevoir, construire et maintenir des pipelines ETL pour nos "
        "équipes data.</p>"
    ),
    langues: str = "<p>Français (atout) - Anglais (atout)</p>",
    employeur: str | None = "AG INSURANCE",
) -> str:
    employer_block = ""
    if employeur is not None:
        employer_block = (
            "<table><tr><td><div>Nom de l&#x27;employeur</div></td>"
            f"<td><div>{employeur}</div></td></tr></table>"
        )
    return f"""<html><body>
<h1>{h1}</h1>
<div class="col-12 col-lg-8 bloc-emploi__text">
<h3>Description de l&#x27;entreprise</h3>
{entreprise}
<h3>Description de la fonction</h3>
{fonction}
<h3>Comp&#xE9;tences linguistiques</h3>
{langues}
</div>
<div class="col-12 col-lg-8 bloc-emploi__text">
<p>Envie d&#x27;en apprendre davantage sur ce m&#xE9;tier ? Parcourez toutes
les informations utiles sur Panorama des m&#xE9;tiers.</p>
</div>
<div class="bloc-emploi__disclaimer">
<p>Cette offre a &#xE9;t&#xE9; r&#xE9;dig&#xE9;e par l&#x27;employeur.</p>
</div>
<div class="bloc-emploi__apply">
<h2>Comment postuler ?</h2>
{employer_block}
</div>
<footer>
<a href="#">Mentions l&#xE9;gales</a>
<a href="#">Restons en contact</a>
<a href="#">Panorama des m&#xE9;tiers</a>
</footer>
</body></html>"""


_DETAIL_HTML_SANS_RUBRIQUE = (
    "<html><body><p>Page vide, sans structure.</p></body></html>"
)


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Toutes les offres de ces tests passent par le throttle (critère 5) ;
    on ne veut pas que la suite attende réellement."""
    monkeypatch.setattr(actiris.time, "sleep", lambda s: None)


def _fake_requests(monkeypatch, *, list_pages, detail_by_ref, detail_status=200):
    """`list_pages` : liste de réponses JSON successives au POST liste.
    `detail_by_ref` : {reference: html} pour le GET détail."""
    posts: list[dict] = []
    gets: list[dict] = []
    pages = list(list_pages)

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append(json)
        page_idx = len(posts) - 1
        data = pages[min(page_idx, len(pages) - 1)]
        return _FakeResponse(json_data=data)

    def fake_get(url, params=None, timeout=None):
        gets.append(params)
        ref = params["reference"]
        html_text = detail_by_ref.get(ref, _DETAIL_HTML_SANS_RUBRIQUE)
        return _FakeResponse(status_code=detail_status, text=html_text)

    monkeypatch.setattr(actiris.requests, "post", fake_post)
    monkeypatch.setattr(actiris.requests, "get", fake_get)
    return posts, gets


# ---------------------------------------------------------------------------
# Critère 3 — code postal + domaine
# ---------------------------------------------------------------------------


def test_critere3_filtre_code_postal_et_domaine(monkeypatch):
    dedans = _list_item("A1", code_postal="1000", code_domaine="Q'1")
    hors_code = _list_item("A2", code_postal="9999", code_domaine="Q'1")
    hors_domaine = _list_item("A3", code_postal="1000", code_domaine="Q'2")
    posts, _ = _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [dedans, hors_code, hors_domaine]}],
        detail_by_ref={"A1": _detail_html()},
    )

    offers = ActirisSource().fetch()

    refs = {o.source_id for o in offers}
    assert refs == {"A1"}
    # le filtre côté adapter n'a pas besoin de tricher sur la requête envoyée
    assert posts[0]["offreFilter"]["codesPostal"] == actiris.BRUSSELS_POSTAL_CODES
    assert posts[0]["offreFilter"]["domainesImt"] == actiris.IT_DOMAINS
    assert posts[0]["offreFilter"]["localisation"] == "Tout"


# ---------------------------------------------------------------------------
# Critère 4 — depuis N jours, plafond réglable, plus récentes d'abord
# ---------------------------------------------------------------------------


def test_critere4_plafond_garde_les_plus_recentes(monkeypatch, capsys):
    vieille = _list_item("B1", date_modification="2026-10-01T00:00:00+02:00")
    recente = _list_item("B2", date_modification="2026-10-09T00:00:00+02:00")
    moyenne = _list_item("B3", date_modification="2026-10-05T00:00:00+02:00")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 3, "offers": [vieille, recente, moyenne]}],
        detail_by_ref={
            "B1": _detail_html(),
            "B2": _detail_html(),
            "B3": _detail_html(),
        },
    )

    offers = ActirisSource(since_days=5, detail_cap=2).fetch()

    assert [o.source_id for o in offers] == ["B2", "B3"]
    out = capsys.readouterr().out
    assert "2 pages de détail ouvertes" in out


def test_critere4_since_days_passe_a_la_requete(monkeypatch):
    posts, _ = _fake_requests(
        monkeypatch,
        list_pages=[{"total": 0, "offers": []}],
        detail_by_ref={},
    )

    ActirisSource(since_days=3).fetch()

    assert posts[0]["offreFilter"]["dateDerniereModification"] is not None


# ---------------------------------------------------------------------------
# Critère 5 — jamais plus de 2 requêtes par seconde
# ---------------------------------------------------------------------------


def test_critere5_throttle_entre_chaque_requete(monkeypatch):
    class _FakeClock:
        def __init__(self):
            self.t = 0.0
            self.sleeps: list[float] = []

        def monotonic(self):
            return self.t

        def sleep(self, s):
            self.sleeps.append(s)
            self.t += s

    clock = _FakeClock()
    monkeypatch.setattr(actiris.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(actiris.time, "sleep", clock.sleep)

    items = [_list_item(f"C{i}") for i in range(3)]
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 3, "offers": items}],
        detail_by_ref={f"C{i}": _detail_html() for i in range(3)},
    )

    ActirisSource(detail_cap=3).fetch()

    # 1 requête liste + 3 requêtes détail = 4 requêtes -> 3 pauses d'au moins 0.5s
    assert len(clock.sleeps) == 3
    assert all(s >= 0.5 for s in clock.sleeps)


# ---------------------------------------------------------------------------
# Critères 6/7 — texte complet, sans menu ni pied de page
# ---------------------------------------------------------------------------


def test_critere6_7_texte_complet_sans_menu_ni_pied(monkeypatch):
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [_list_item("D1")]}],
        detail_by_ref={"D1": _detail_html()},
    )

    offer = ActirisSource().fetch()[0]

    assert "Concevoir, construire et maintenir des pipelines ETL" in offer.description
    assert offer.company == "AG INSURANCE"
    for interdit in ("Mentions légales", "Restons en contact", "Panorama des métiers"):
        assert interdit not in offer.description


# ---------------------------------------------------------------------------
# Critère 8 — bascule de titre FR -> NL -> détail, jamais "Sans titre" à tort
# ---------------------------------------------------------------------------


def test_critere8_titre_bascule_fr_nl_puis_detail(monkeypatch):
    fr = _list_item("E1", titre_fr="Développeur Python H/F/X", titre_nl="")
    nl_seul = _list_item("E2", titre_fr="", titre_nl="Python Ontwikkelaar M/V/X")
    aucun = _list_item("E3", titre_fr="", titre_nl="")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 3, "offers": [fr, nl_seul, aucun]}],
        detail_by_ref={
            "E1": _detail_html(h1="Développeur Python H/F/X"),
            "E2": _detail_html(h1="Python Ontwikkelaar M/V/X"),
            "E3": _detail_html(h1="Titre de la page de détail H/F/X"),
        },
    )

    offers = {o.source_id: o for o in ActirisSource().fetch()}

    assert offers["E1"].title == "Développeur Python"
    assert offers["E2"].title == "Python Ontwikkelaar"
    assert offers["E3"].title == "Titre de la page de détail"
    assert all(o.title != "Sans titre" for o in offers.values())


def test_critere8_sans_titre_si_les_trois_sont_vides(monkeypatch):
    aucun = _list_item("F1", titre_fr="", titre_nl="")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [aucun]}],
        detail_by_ref={"F1": _DETAIL_HTML_SANS_RUBRIQUE},
    )

    offer = ActirisSource().fetch()[0]

    assert offer.title == "Sans titre"


# ---------------------------------------------------------------------------
# Critère 9 — suffixe de genre retiré
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("AG Insurance - AI Data Engineer H/F/X", "AG Insurance - AI Data Engineer"),
        ("Analyst - Developer ICT Senior  M/V/X", "Analyst - Developer ICT Senior"),
        ("Technicien réseau (m/f/x)", "Technicien réseau"),
        ("Developer M/W/X", "Developer"),
        ("Pas de suffixe", "Pas de suffixe"),
    ],
)
def test_critere9_suffixe_genre_retire(brut, attendu):
    assert actiris._strip_gender_suffix(brut) == attendu


# ---------------------------------------------------------------------------
# Critère 10 — lieu "Bruxelles", commune/code postal lisibles dans le texte
# ---------------------------------------------------------------------------


def test_critere10_lieu_bruxelles_et_commune_lisible(monkeypatch):
    item = _list_item("G1", code_postal="1030", commune_fr="Schaerbeek")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"G1": _detail_html()},
    )

    offer = ActirisSource().fetch()[0]

    assert offer.location == "Bruxelles"
    assert "Schaerbeek" in offer.description
    assert "1030" in offer.description


# ---------------------------------------------------------------------------
# Critère 11 — identifiant + URL de la page de détail
# ---------------------------------------------------------------------------


def test_critere11_identifiant_et_url(monkeypatch):
    item = _list_item("H1", type_offer="Hrxml")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"H1": _detail_html()},
    )

    offer = ActirisSource().fetch()[0]

    assert offer.source_id == "H1"
    assert offer.url == (
        "https://www.actiris.brussels/fr/citoyens/detail-offre-demploi/"
        "?reference=H1&type=Hrxml"
    )


# ---------------------------------------------------------------------------
# Critère 12 — employeur vide si la rubrique manque, jamais inventé
# ---------------------------------------------------------------------------


def test_critere12_employeur_vide_si_rubrique_absente(monkeypatch):
    item = _list_item("I1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"I1": _detail_html(employeur=None)},
    )

    offer = ActirisSource().fetch()[0]

    assert offer.company is None


# ---------------------------------------------------------------------------
# Critère 13 — déjà vue au second passage (dédup)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_critere13_deja_vue_au_second_fetch(monkeypatch, db_path):
    item = _list_item("J1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"J1": _detail_html()},
    )

    premier_fetch = ActirisSource().fetch()
    for offer in premier_fetch:
        save_offer(db_path, offer)

    second_fetch = ActirisSource().fetch()
    nouvelles = filter_new(db_path, second_fetch)

    assert nouvelles == []


# ---------------------------------------------------------------------------
# Critère 14 — une même offre EURES + Actiris n'existe qu'une fois
# ---------------------------------------------------------------------------


def test_critere14_dedup_cross_source_eures_actiris(monkeypatch):
    from datetime import datetime, timezone

    item = _list_item("K1", titre_fr="AI Data Engineer H/F/X")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"K1": _detail_html(h1="AI Data Engineer H/F/X")},
    )
    actiris_offer = ActirisSource().fetch()[0]
    assert actiris_offer.title == "AI Data Engineer"
    assert actiris_offer.company == "AG INSURANCE"

    eures_offer = JobOffer(
        source="eures",
        source_id="eures-999",
        fingerprint=fingerprint("AI Data Engineer", "AG INSURANCE", "Bruxelles"),
        title="AI Data Engineer",
        description="Description EURES de la même offre.",
        company="AG INSURANCE",
        location="Bruxelles",
        remote=False,
        contract_type="DIRECTHIRE",
        url="https://europa.eu/eures/portal/jv-se/jv-details/eures-999?lang=fr",
        fetched_at=datetime.now(timezone.utc),
    )

    batch = [eures_offer, actiris_offer]
    assert actiris_offer.fingerprint == eures_offer.fingerprint

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    nouvelles = filter_new(conn, batch)

    assert len(nouvelles) == 1


# ---------------------------------------------------------------------------
# Critère 15 — aucune offre Actiris écartée par le filtre géographique
# ---------------------------------------------------------------------------


def test_critere15_jamais_ecartee_par_le_filtre_geo(monkeypatch):
    profile, _ = load_profile(REPO / "profiles" / "example.yaml")
    item = _list_item("L1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"L1": _detail_html()},
    )

    offer = ActirisSource().fetch()[0]
    filtered_out, reason = apply_hard_filters(
        offer, profile.search_criteria, profile.zones
    )

    assert filtered_out is False
    assert reason is None


# ---------------------------------------------------------------------------
# Critère 16 — page de détail injoignable ou sans rubrique : texte manquant,
# avertissement, le run continue
# ---------------------------------------------------------------------------


def test_critere16_detail_injoignable_titre_seul_et_avertissement(monkeypatch):
    item = _list_item("M1", titre_fr="Offre dont le détail casse")
    posts = []

    def fake_post(url, json=None, headers=None, timeout=None):
        posts.append(json)
        return _FakeResponse(json_data={"total": 1, "offers": [item]})

    def fake_get(url, params=None, timeout=None):
        raise actiris.requests.ConnectionError("refusée")

    monkeypatch.setattr(actiris.requests, "post", fake_post)
    monkeypatch.setattr(actiris.requests, "get", fake_get)

    with pytest.warns(UserWarning, match="M1"):
        offers = ActirisSource().fetch()

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Offre dont le détail casse"
    assert len(offer.description.strip()) < 50
    assert offer.company is None


def test_critere16_page_sans_rubrique_ne_casse_pas_le_run(monkeypatch):
    item = _list_item("N1", titre_fr="Offre sans rubriques connues")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total": 1, "offers": [item]}],
        detail_by_ref={"N1": _DETAIL_HTML_SANS_RUBRIQUE},
    )

    offers = ActirisSource().fetch()

    assert len(offers) == 1
    assert offers[0].title == "Offre sans rubriques connues"
    assert offers[0].company is None


# ---------------------------------------------------------------------------
# Critères 1/2 — wiring run.py : source interrogée / désactivable
# ---------------------------------------------------------------------------


class _SpySource:
    instances: list["_SpySource"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.fetch_calls = 0
        _SpySource.instances.append(self)

    def fetch(self):
        self.fetch_calls += 1
        return []


@pytest.fixture
def run_harness(tmp_path, monkeypatch):
    import orchestrator.job_search.sources.france_travail as ft

    class _NoOpFT:
        def __init__(self, *a, **k):
            pass

        def fetch(self):
            return []

    monkeypatch.setattr(ft, "FranceTravailSource", _NoOpFT)
    monkeypatch.setattr(extractor, "ensure_models_available", lambda *a, **k: None)
    monkeypatch.setattr(extractor, "unload_model", lambda *a, **k: None)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)

    profil_path = tmp_path / "profil.yaml"
    shutil.copy(REPO / "profiles" / "example.yaml", profil_path)

    db_path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", db_path)
    monkeypatch.setattr(api_db, "DB_PATH", db_path)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    conn.close()

    return profil_path


def _run(monkeypatch, profil_path, *extra_args):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run",
            "--profile",
            str(profil_path),
            "--no-remotive",
            "--no-indeed",
            "--no-eures",
            "--no-forem",
            *extra_args,
        ],
    )
    run.main()


def test_critere1_source_interrogee_et_loggee(run_harness, monkeypatch, capsys):
    _SpySource.instances = []
    monkeypatch.setattr(actiris, "ActirisSource", _SpySource)

    _run(monkeypatch, run_harness)

    assert len(_SpySource.instances) == 1
    assert _SpySource.instances[0].fetch_calls == 1
    out = capsys.readouterr().out
    assert "_SpySource: 0 offres" in out


def test_critere2_no_actiris_desactive_la_source(run_harness, monkeypatch):
    _SpySource.instances = []
    monkeypatch.setattr(actiris, "ActirisSource", _SpySource)

    _run(monkeypatch, run_harness, "--no-actiris")

    assert _SpySource.instances == []
