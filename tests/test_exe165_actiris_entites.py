"""Tests EXE-165 — les titres (et la commune) des offres Actiris sont décodés
de leurs entités HTML avant d'entrer dans le pipeline.

Aucun test n'appelle actiris.brussels : `requests.post`/`requests.get` sont
remplacés par des doublures. Aucun test ne lit ni n'écrit sous data/.
"""

from datetime import datetime, timezone

import pytest

import orchestrator.job_search.sources.actiris as actiris
from orchestrator.job_search.sources.actiris import ActirisSource
from orchestrator.job_search.sources.base import JobOffer
from orchestrator.job_search.sources.fingerprint import fingerprint
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.storage.dedup import filter_new


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise actiris.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Toutes les offres passent par le throttle ; on ne veut pas attendre."""
    monkeypatch.setattr(actiris.time, "sleep", lambda s: None)


def _list_item(
    reference: str,
    *,
    titre_fr: str = "",
    titre_nl: str = "",
    commune_fr: str = "Bruxelles",
    commune_nl: str = "Brussel",
    code_postal: str = "1000",
    code_domaine: str = "Q'3",
) -> dict:
    return {
        "reference": reference,
        "codeDomaineImt": code_domaine,
        "codePostal": code_postal,
        "titreFr": titre_fr,
        "titreNl": titre_nl,
        "typeOffer": "Hrxml",
        "communeFr": commune_fr,
        "communeNl": commune_nl,
        "dateModification": "2026-10-09T00:00:00+02:00",
    }


def _detail_html(*, h1: str = "", employeur: str | None = None) -> str:
    employer_block = ""
    if employeur is not None:
        employer_block = (
            "<table><tr><td><div>Nom de l&#x27;employeur</div></td>"
            f"<td><div>{employeur}</div></td></tr></table>"
        )
    return f"""<html><body>
<h1>{h1}</h1>
<div class="bloc-emploi__text">
<p>Texte de l'offre.</p>
</div>
<div class="bloc-emploi__apply">
{employer_block}
</div>
</body></html>"""


def _fake_requests(monkeypatch, *, items: list[dict], detail_by_ref: dict[str, str]):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse(json_data={"total": len(items), "offers": items})

    def fake_get(url, params=None, timeout=None):
        ref = params["reference"]
        return _FakeResponse(text=detail_by_ref.get(ref, "<html></html>"))

    monkeypatch.setattr(actiris.requests, "post", fake_post)
    monkeypatch.setattr(actiris.requests, "get", fake_get)


# ---------------------------------------------------------------------------
# Critère 1 — titre français décodé, suffixe de genre retiré
# ---------------------------------------------------------------------------


def test_critere1_titre_fr_entites_decodees(monkeypatch):
    titre_brut = (
        "Consultant Junior - Politique europ&#233;enne des clusters, "
        "&#233;cosyst&#232;me d&#39;innovation et sp&#233;cialisation "
        "intelligente H/F/X"
    )
    item = _list_item("5976132", titre_fr=titre_brut)
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"5976132": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert offer.title == (
        "Consultant Junior - Politique européenne des clusters, "
        "écosystème d'innovation et spécialisation intelligente"
    )


# ---------------------------------------------------------------------------
# Critère 2 — entité "&amp;" décodée en "&"
# ---------------------------------------------------------------------------


def test_critere2_entite_esperluette_decodee(monkeypatch):
    item = _list_item("5936886", titre_fr="Senior Process &amp; Project Expert H/F/X")
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"5936886": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert offer.title == "Senior Process & Project Expert"


# ---------------------------------------------------------------------------
# Critère 3 — titre français vide, bascule sur le titre néerlandais décodé
# ---------------------------------------------------------------------------


def test_critere3_bascule_titre_nl_decode(monkeypatch):
    item = _list_item(
        "5919809",
        titre_fr="",
        titre_nl="Op&#233;rateur CNC bois (Zaventem) H/F/X",
    )
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"5919809": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert offer.title == "Opérateur CNC bois (Zaventem)"


# ---------------------------------------------------------------------------
# Critère 4 — le suffixe de genre est retiré même derrière un titre décodé
# ---------------------------------------------------------------------------


def test_critere4_suffixe_retire_apres_decodage(monkeypatch):
    item = _list_item(
        "5976132",
        titre_fr=(
            "Consultant Junior - Politique europ&#233;enne des clusters, "
            "&#233;cosyst&#232;me d&#39;innovation et sp&#233;cialisation "
            "intelligente H/F/X"
        ),
    )
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"5976132": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert offer.title == (
        "Consultant Junior - Politique européenne des clusters, "
        "écosystème d'innovation et spécialisation intelligente"
    )
    assert not offer.title.endswith("H/F/X")


# ---------------------------------------------------------------------------
# Critère 5 — la commune affichée dans la description ne porte aucune entité
# ---------------------------------------------------------------------------


def test_critere5_commune_decodee_dans_la_description(monkeypatch):
    item = _list_item(
        "O1", titre_fr="Offre test", commune_fr="Molenbeek-Saint-Jean &#233;largi"
    )
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"O1": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert "Molenbeek-Saint-Jean élargi" in offer.description
    for interdit in ("&#233;", "&amp;", "&#", "&lt;", "&gt;"):
        assert interdit not in offer.description


# ---------------------------------------------------------------------------
# Critère 6 — l'empreinte Actiris rejoint l'empreinte EURES malgré l'entité
# ---------------------------------------------------------------------------


def test_critere6_empreinte_identique_malgre_entite(monkeypatch):
    item = _list_item(
        "P1", titre_fr="AG Insurance - AI Data Engineer &amp; MLOps H/F/X"
    )
    _fake_requests(
        monkeypatch,
        items=[item],
        detail_by_ref={"P1": _detail_html(employeur="AG INSURANCE")},
    )

    actiris_offer = ActirisSource().fetch()[0]

    eures_offer = JobOffer(
        source="eures",
        source_id="eures-999",
        fingerprint=fingerprint(
            "AG Insurance - AI Data Engineer & MLOps", "AG Insurance", "Bruxelles"
        ),
        title="AG Insurance - AI Data Engineer & MLOps",
        description="Description EURES de la même offre.",
        company="AG Insurance",
        location="Bruxelles",
        remote=False,
        contract_type="DIRECTHIRE",
        url="https://europa.eu/eures/portal/jv-se/jv-details/eures-999?lang=fr",
        fetched_at=datetime.now(timezone.utc),
    )

    assert actiris_offer.fingerprint == eures_offer.fingerprint

    conn_batch = [eures_offer, actiris_offer]
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    nouvelles = filter_new(conn, conn_batch)

    assert len(nouvelles) == 1


# ---------------------------------------------------------------------------
# Critère 7 — un titre sans entité ressort inchangé, au suffixe près
# ---------------------------------------------------------------------------


def test_critere7_titre_sans_entite_inchange(monkeypatch):
    item = _list_item("Q1", titre_fr="Développeur Python H/F/X")
    _fake_requests(monkeypatch, items=[item], detail_by_ref={"Q1": _detail_html()})

    offer = ActirisSource().fetch()[0]

    assert offer.title == "Développeur Python"
