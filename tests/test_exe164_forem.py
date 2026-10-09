"""Tests EXE-164 — les offres informatiques bruxelloises republiées par le
Forem (Jobat, StepStone, References) entrent dans le run avec leur texte.

Aucun test n'appelle odwb.be ni leforem.be : `requests.get` est remplacé par
une doublure qui rend une page du jeu de données (JSON) et un détail JSON
enregistrés ci-dessous. Aucun test ne lit ni n'écrit sous data/ : base, profil
et REPO_ROOT (run) sont en tmp_path.
"""

import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

import api.db as api_db
import orchestrator.job_search.run as run
import orchestrator.job_search.scoring.extractor as extractor
import orchestrator.job_search.sources.forem as forem
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.scoring.filters import apply_hard_filters
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.sources.fingerprint import fingerprint
from orchestrator.job_search.sources.forem import ForemSource
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.dedup import filter_new
from orchestrator.job_search.storage.offers import save_offer

REPO = Path(__file__).resolve().parent.parent

KEYWORDS = ["python", "data engineer", "machine learning", "développeur"]


# ---------------------------------------------------------------------------
# Fixtures de doublure réseau — formes relevées sur odwb.be / leforem.be le
# 9 octobre 2026
# ---------------------------------------------------------------------------


def _record(
    numero: str,
    *,
    titre: str = "Développeur(se) Python/React (H/F/X)",
    nuts: str = "BE1",
    metier_code: str = "M1805",
    localite: str = "Bruxelles",
    employeur: str = "AURO CLIC - AURO CLIC",
    date_debut: str = "2026-10-08",
    type_contrat: str = "Durée indéterminée",
    regime: str = "Temps plein",
) -> dict:
    return {
        "numerooffreforem": numero,
        "titreoffre": titre,
        "lieuxtravaillocalite": [localite],
        "lieuxtravailregion": ["Bruxelles-Capitale"],
        "lieuxtravailcodepostal": ["1000"],
        "lieuxtravailregionnuts": [nuts],
        "lieuxtravailgeo": [],
        "typecontrat": type_contrat,
        "nomemployeur": employeur,
        "regimetravail": regime,
        "nombrepostes": 1,
        "niveauxetudes": [],
        "langues": [],
        "experiencerequise": "",
        "secteurs": [],
        "source": "Jobat",
        "referenceexterne": "",
        "url": "",
        "datedebutdiffusion": date_debut,
        "datefindiffusion": "2026-11-08",
        "metier": "Développeur",
        "metiercodedimeco": metier_code,
    }


def _detail(
    numero: str,
    *,
    titre: str = "Développeur(se) Python/React (H/F/X)",
    employeur: str = "AURO CLIC - AURO CLIC",
    description: str = (
        "<p>Développer et faire évoluer des services et API en Python avec FastAPI.</p>"
    ),
    type_contrat: str | None = "Durée indéterminée",
    regime: str | None = "Temps plein",
) -> dict:
    return {
        "numero": numero,
        "titreOffre": titre,
        "nomEmployeur": employeur,
        "secteurActiviteEmployeur": "Informatique",
        "typeContrat": type_contrat,
        "regimeTravail": regime,
        "lieuxTravail": [{"localite": "Bruxelles", "codePostal": "1000"}],
        "langues": [],
        "nombrePostes": 1,
        "descriptionJob": description,
        "metier": "Développeur",
        "dateDebutDiffusion": "08/10/2026",
        "dateFinDiffusion": "08/11/2026",
        "dateModification": "08/10/2026",
        "howToApply": {
            "prenom": "Jean",
            "nom": "Dupont",
            "email": "jean.dupont@example.com",
        },
        "logoEmployeur": "data:image/png;base64,AAAA",
        "logoMimeType": "image/png",
        "googleForJobMetadata": {"type": "JobPosting", "context": "https://schema.org"},
    }


_DETAIL_404 = None


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests_module.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


import requests as requests_module  # noqa: E402


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Toutes les offres de ces tests passent par le throttle (critère 6) ;
    on ne veut pas que la suite attende réellement."""
    monkeypatch.setattr(forem.time, "sleep", lambda s: None)


def _fake_requests(monkeypatch, *, list_pages, detail_by_numero, detail_status=200):
    """`list_pages` : liste de réponses JSON successives au GET jeu de données.
    `detail_by_numero` : {numero: detail_json} pour le GET détail."""
    dataset_calls: list[dict] = []
    detail_calls: list[str] = []
    pages = list(list_pages)

    def fake_get(url, params=None, timeout=None):
        if url == forem._DATASET_URL:
            dataset_calls.append(params)
            idx = len(dataset_calls) - 1
            return _FakeResponse(json_data=pages[min(idx, len(pages) - 1)])
        numero = url.rsplit("/", 1)[-1]
        detail_calls.append(numero)
        if numero not in detail_by_numero:
            return _FakeResponse(status_code=404, json_data=None)
        return _FakeResponse(
            status_code=detail_status, json_data=detail_by_numero[numero]
        )

    monkeypatch.setattr(forem.requests, "get", fake_get)
    return dataset_calls, detail_calls


# ---------------------------------------------------------------------------
# Critère 3 — uniquement les offres BE1
# ---------------------------------------------------------------------------


def test_critere3_filtre_nuts_be1(monkeypatch):
    dedans = _record("A1", nuts="BE1")
    hors = _record("A2", nuts="BE3")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 2, "results": [dedans, hors]}],
        detail_by_numero={"A1": _detail("A1"), "A2": _detail("A2")},
    )

    offers = ForemSource(keywords=KEYWORDS).fetch()

    assert {o.source_id for o in offers} == {"A1"}


# ---------------------------------------------------------------------------
# Critère 4 — métier M18 ou mot-clé du profil dans le titre
# ---------------------------------------------------------------------------


def test_critere4_metier_m18_entre(monkeypatch):
    item = _record("B1", metier_code="M1805", titre="Technicien logistique")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"B1": _detail("B1")},
    )

    offers = ForemSource(keywords=KEYWORDS).fetch()

    assert {o.source_id for o in offers} == {"B1"}


def test_critere4_mot_cle_titre_entre_sans_metier_m18(monkeypatch):
    item = _record("C1", metier_code="M1203", titre="Développeur Python freelance")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"C1": _detail("C1")},
    )

    offers = ForemSource(keywords=KEYWORDS).fetch()

    assert {o.source_id for o in offers} == {"C1"}


def test_critere4_mot_cle_insensible_accents_et_casse(monkeypatch):
    item = _record("D1", metier_code="M1203", titre="DÉVELOPPEUR backend confirmé")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"D1": _detail("D1")},
    )

    offers = ForemSource(keywords=KEYWORDS).fetch()

    assert {o.source_id for o in offers} == {"D1"}


def test_critere4_ni_metier_ni_mot_cle_exclu(monkeypatch):
    item = _record("E1", metier_code="M1203", titre="Comptable confirmé")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"E1": _detail("E1")},
    )

    offers = ForemSource(keywords=KEYWORDS).fetch()

    assert offers == []


# ---------------------------------------------------------------------------
# Critère 5 — depuis N jours, plafond réglable, plus récentes d'abord
# ---------------------------------------------------------------------------


def test_critere5_plafond_garde_les_plus_recentes(monkeypatch, capsys):
    vieille = _record("F1", date_debut="2026-10-01")
    recente = _record("F2", date_debut="2026-10-09")
    moyenne = _record("F3", date_debut="2026-10-05")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 3, "results": [vieille, recente, moyenne]}],
        detail_by_numero={
            "F1": _detail("F1"),
            "F2": _detail("F2"),
            "F3": _detail("F3"),
        },
    )

    offers = ForemSource(keywords=KEYWORDS, since_days=5, detail_cap=2).fetch()

    assert [o.source_id for o in offers] == ["F2", "F3"]
    out = capsys.readouterr().out
    assert "2 pages de détail ouvertes" in out


def test_critere5_since_days_passe_a_la_requete(monkeypatch):
    dataset_calls, _ = _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 0, "results": []}],
        detail_by_numero={},
    )

    ForemSource(keywords=KEYWORDS, since_days=3).fetch()

    assert "datedebutdiffusion" in dataset_calls[0]["where"]
    assert "BE1" in dataset_calls[0]["where"]


# ---------------------------------------------------------------------------
# Critère 6 — jamais plus de 2 requêtes par seconde
# ---------------------------------------------------------------------------


def test_critere6_throttle_entre_chaque_requete(monkeypatch):
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
    monkeypatch.setattr(forem.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(forem.time, "sleep", clock.sleep)

    items = [_record(f"G{i}") for i in range(3)]
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 3, "results": items}],
        detail_by_numero={f"G{i}": _detail(f"G{i}") for i in range(3)},
    )

    ForemSource(keywords=KEYWORDS, detail_cap=3).fetch()

    # 1 requête liste + 3 requêtes détail = 4 requêtes -> 3 pauses d'au moins 0.5s
    assert len(clock.sleeps) == 3
    assert all(s >= 0.5 for s in clock.sleeps)


# ---------------------------------------------------------------------------
# Critère 7 — texte complet et employeur, cas réel du 9 octobre 2026
# ---------------------------------------------------------------------------


def test_critere7_texte_complet_et_employeur(monkeypatch):
    item = _record("2087373")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"2087373": _detail("2087373")},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert (
        "Développer et faire évoluer des services et API en Python avec FastAPI"
        in offer.description
    )
    assert offer.company == "AURO CLIC - AURO CLIC"


# ---------------------------------------------------------------------------
# Critère 8 — suffixe de genre retiré
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("Développeur(se) Python/React (H/F/X)", "Développeur(se) Python/React"),
        ("Analyst - Developer ICT Senior  M/V/X", "Analyst - Developer ICT Senior"),
        ("Technicien réseau (m/f/x)", "Technicien réseau"),
        ("Developer M/W/X", "Developer"),
        ("Pas de suffixe", "Pas de suffixe"),
    ],
)
def test_critere8_suffixe_genre_retire(brut, attendu):
    assert forem._strip_gender_suffix(brut) == attendu


def test_critere8_suffixe_retire_sur_offre_mappee(monkeypatch):
    item = _record("H1", titre="Développeur(se) Python/React (H/F/X)")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={
            "H1": _detail("H1", titre="Développeur(se) Python/React (H/F/X)")
        },
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert offer.title == "Développeur(se) Python/React"


# ---------------------------------------------------------------------------
# Critère 9 — lieu "Bruxelles", localité du jeu de données lisible dans le texte
# ---------------------------------------------------------------------------


def test_critere9_lieu_bruxelles_et_localite_lisible(monkeypatch):
    item = _record("I1", localite="Schaerbeek")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"I1": _detail("I1")},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert offer.location == "Bruxelles"
    assert "Schaerbeek" in offer.description


# ---------------------------------------------------------------------------
# Critère 10 — identifiant + URL de la page qui s'ouvre dans un navigateur
# ---------------------------------------------------------------------------


def test_critere10_identifiant_et_url(monkeypatch):
    item = _record("2087373")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"2087373": _detail("2087373")},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert offer.source_id == "2087373"
    assert offer.url == "https://www.leforem.be/recherche-offres/offre-detail/2087373"


# ---------------------------------------------------------------------------
# Critère 11 — type de contrat et régime de travail dans les champs existants
# ---------------------------------------------------------------------------


def test_critere11_contrat_et_regime_renseignes(monkeypatch):
    item = _record("J1", type_contrat="Durée indéterminée", regime="Temps plein")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={
            "J1": _detail("J1", type_contrat="Durée indéterminée", regime="Temps plein")
        },
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert offer.nature_contract == "Durée indéterminée"
    assert offer.full_time is True


def test_critere11_contrat_et_regime_absents_restent_vides(monkeypatch):
    item = _record("K1", type_contrat="", regime="")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"K1": _detail("K1", type_contrat=None, regime=None)},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    assert offer.nature_contract is None
    assert offer.full_time is None


# ---------------------------------------------------------------------------
# Critère 12 — déjà vue au second passage (dédup)
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


def test_critere12_deja_vue_au_second_fetch(monkeypatch, db_path):
    item = _record("L1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"L1": _detail("L1")},
    )

    premier_fetch = ForemSource(keywords=KEYWORDS).fetch()
    for offer in premier_fetch:
        save_offer(db_path, offer)

    second_fetch = ForemSource(keywords=KEYWORDS).fetch()
    nouvelles = filter_new(db_path, second_fetch)

    assert nouvelles == []


# ---------------------------------------------------------------------------
# Critère 13 — aucune offre Forem écartée par le filtre géographique
# ---------------------------------------------------------------------------


def test_critere13_jamais_ecartee_par_le_filtre_geo(monkeypatch):
    profile, _ = load_profile(REPO / "profiles" / "example.yaml")
    item = _record("M1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"M1": _detail("M1")},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]
    filtered_out, reason = apply_hard_filters(
        offer, profile.search_criteria, profile.zones
    )

    assert filtered_out is False
    assert reason is None


# ---------------------------------------------------------------------------
# Critère 14 — détail injoignable : titre seul, avertissement, le run continue
# ---------------------------------------------------------------------------


def test_critere14_detail_injoignable_titre_seul_et_avertissement(monkeypatch):
    item = _record("N1", titre="Offre dont le détail casse")
    dataset_calls = []

    def fake_get(url, params=None, timeout=None):
        if url == forem._DATASET_URL:
            dataset_calls.append(params)
            return _FakeResponse(json_data={"total_count": 1, "results": [item]})
        raise requests_module.ConnectionError("refusée")

    monkeypatch.setattr(forem.requests, "get", fake_get)

    with pytest.warns(UserWarning, match="N1"):
        offers = ForemSource(keywords=KEYWORDS).fetch()

    assert len(offers) == 1
    offer = offers[0]
    assert offer.title == "Offre dont le détail casse"
    assert len(offer.description.strip()) < 50
    # Le détail est injoignable, mais le jeu de données porte déjà l'employeur
    # (à la différence d'Actiris) : il n'est pas perdu.
    assert offer.company == "AURO CLIC - AURO CLIC"


# ---------------------------------------------------------------------------
# Critère 15 — jeu de données injoignable : zéro offre, avertissement, le run continue
# ---------------------------------------------------------------------------


def test_critere15_jeu_de_donnees_injoignable_zero_offre(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        raise requests_module.ConnectionError("refusée")

    monkeypatch.setattr(forem.requests, "get", fake_get)

    with pytest.warns(UserWarning):
        offers = ForemSource(keywords=KEYWORDS).fetch()

    assert offers == []


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — PII et logo jamais enregistrés
# ---------------------------------------------------------------------------


def test_pii_et_logo_jamais_enregistres(monkeypatch):
    item = _record("O1")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={"O1": _detail("O1")},
    )

    offer = ForemSource(keywords=KEYWORDS).fetch()[0]

    dump = offer.model_dump_json()
    for interdit in (
        "Jean",
        "Dupont",
        "jean.dupont@example.com",
        "base64",
        "logoMimeType",
    ):
        assert interdit not in dump


# ---------------------------------------------------------------------------
# Critère 14/15 (dédup cross-source) — une même offre Forem + EURES n'existe
# qu'une fois (crochet fingerprint, comme Actiris/EURES)
# ---------------------------------------------------------------------------


def test_dedup_cross_source_eures_forem(monkeypatch):
    from datetime import datetime, timezone

    item = _record("P1", titre="AI Data Engineer (H/F/X)")
    _fake_requests(
        monkeypatch,
        list_pages=[{"total_count": 1, "results": [item]}],
        detail_by_numero={
            "P1": _detail(
                "P1", titre="AI Data Engineer (H/F/X)", employeur="AG INSURANCE"
            )
        },
    )
    forem_offer = ForemSource(keywords=KEYWORDS).fetch()[0]
    assert forem_offer.title == "AI Data Engineer"
    assert forem_offer.company == "AG INSURANCE"

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

    batch = [eures_offer, forem_offer]
    assert forem_offer.fingerprint == eures_offer.fingerprint

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    nouvelles = filter_new(conn, batch)

    assert len(nouvelles) == 1


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
            "--no-actiris",
            *extra_args,
        ],
    )
    run.main()


def test_critere1_source_interrogee_et_loggee(run_harness, monkeypatch, capsys):
    _SpySource.instances = []
    monkeypatch.setattr(forem, "ForemSource", _SpySource)

    _run(monkeypatch, run_harness)

    assert len(_SpySource.instances) == 1
    assert _SpySource.instances[0].fetch_calls == 1
    out = capsys.readouterr().out
    assert "_SpySource: 0 offres" in out


def test_critere2_no_forem_desactive_la_source(run_harness, monkeypatch):
    _SpySource.instances = []
    monkeypatch.setattr(forem, "ForemSource", _SpySource)

    _run(monkeypatch, run_harness, "--no-forem")

    assert _SpySource.instances == []
