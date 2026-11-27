"""Tests EXE-219 — la même offre venue de deux sources n'apparaît qu'une fois.

Deux offres sont la même quand la clé de comparaison de leur parcours est la même
(H3). Chaque test pose ses offres et leurs parcours directement en base (fixture
`_isolate_db_path` de conftest.py) et son profil dans un dossier temporaire, comme
tests/test_exe210_a_postuler.py (H10). Aucun test n'appelle un site : la lecture
de parcours des critères 21 à 23 passe par un point d'appel réseau simulé.
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

ETATS_TRAITES = [
    "retenue",
    "ecartee",
    "candidature_envoyee",
    "entretien",
    "offre_recue",
    "refusee",
    "sans_suite",
    "abandonnee",
]

CLE = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"
AUTRE_CLE = "https://www.wearesander.com/fr/jobs/net-developer/90001"

_compteur = {"n": 0}


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths, "PROFILE_PATH", chemin)


@pytest.fixture
def client():
    import api.main as api_main

    with TestClient(api_main.app) as c:
        yield c


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(paths.DB_PATH)


def _offre(
    *,
    title="Développeur Python",
    company=None,
    source="actiris",
    source_id=None,
    url=None,
    domain="backend",
    title_data=False,
    jours=3,
    heures=1,
    description="Poste de développeur dans une équipe produit.",
) -> int:
    """L'offre témoin d'EXE-210, sauf ce que le critère change ; rend son id."""
    _compteur["n"] += 1
    n = _compteur["n"]
    company = company if company is not None else f"Acme {n}"
    fetched = (
        datetime.now(timezone.utc) - timedelta(days=jours, hours=heures)
    ).isoformat()
    facts = json.dumps(
        {
            "seniority_required": "intermediate",
            "techs_required": [{"name": "python", "importance": "core"}],
            "domain": domain,
            "role_level": "ic",
            "langues_requises": [],
        }
    )
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, ad_language, "
            "extracted_facts_json, filtered_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                source,
                source_id if source_id is not None else f"id-219-{n}",
                f"fp-219-{n}",
                title,
                company,
                "Bruxelles",
                "directhire",
                url if url is not None else f"https://annonce.test/219/{n}",
                fetched,
                description,
                "fr",
                facts,
            ),
        )
        return cur.lastrowid


def _parcours(oid: int, cle: str | None, fin_forme: str = "page") -> None:
    """Un parcours lu, posé en base comme la lecture l'écrit."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO parcours (offer_id, lu_le, maillons_json, fin_forme, "
            "fin_adresse, cle, provinces_json) VALUES (?, ?, '[]', ?, ?, ?, '[]')",
            (oid, datetime.now(timezone.utc).isoformat(), fin_forme, cle, cle),
        )


def _etat(oid: int, etat: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?)", (oid, etat)
        )


def _expiree(oid: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO expirations (offer_id, expired) VALUES (?, 1)", (oid,)
        )


def _get(client, **params) -> dict:
    r = client.get("/a-postuler", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client, file="principale") -> list[int]:
    return [ligne["id"] for ligne in _get(client, file=file)["lignes"]]


def _toutes(client) -> list[int]:
    return _ids(client, "principale") + _ids(client, "a_etudier")


def _ligne(client, oid: int) -> dict:
    for file in ("principale", "a_etudier"):
        for ligne in _get(client, file=file)["lignes"]:
            if ligne["id"] == oid:
                return ligne
    raise AssertionError(f"offre {oid} dans aucune file")


def _file(client, oid: int) -> dict:
    r = client.get(f"/offers/{oid}/a-postuler")
    assert r.status_code == 200, r.text
    return r.json()


def _paire_sander(*, cle_b: str = CLE) -> tuple[int, int]:
    """Critère 1 : eures « Sander », actiris « OFFRE D'UNE AUTRE REGION ».
    La première est récupérée avant la seconde."""
    a = _offre(
        title="Laravel Developer", company="Sander", source="eures", jours=4
    )
    b = _offre(
        title="Laravel developer (H/F)",
        company="OFFRE D'UNE AUTRE REGION",
        source="actiris",
        jours=2,
    )
    _parcours(a, CLE)
    _parcours(b, cle_b)
    return a, b


# ---------------------------------------------------------------------------
# La même clé
# ---------------------------------------------------------------------------


def test_critere_1_meme_cle_une_ligne(client):
    a, b = _paire_sander()
    lignes = [i for i in _toutes(client) if i in (a, b)]
    assert len(lignes) == 1


def test_critere_2_gardee_la_plus_recente(client):
    a, b = _paire_sander()
    assert b in _toutes(client)
    assert a not in _toutes(client)


def test_critere_3_autre_au_motif_doublon(client):
    a, _ = _paire_sander()
    assert _file(client, a)["motif"] == "doublon"


def test_critere_4_porte_l_offre_gardee(client):
    a, b = _paire_sander()
    meme = _file(client, a).get("meme_offre_que")
    assert meme is not None
    assert meme["id"] == b


def test_critere_5_trois_offres_meme_cle(client):
    ids = [
        _offre(title=f"Poste {n}", company=f"Société {n}", jours=n) for n in (2, 3, 4)
    ]
    for oid in ids:
        _parcours(oid, CLE)
    assert len([i for i in _toutes(client) if i in ids]) == 1
    motifs = [_file(client, oid)["motif"] for oid in ids]
    assert motifs.count("doublon") == 2


def test_critere_6_jumelles_de_la_ligne_gardee(client):
    a, b = _paire_sander()
    c = _offre(title="Laravel dev", company="Autre", source="forem", jours=5)
    _parcours(c, CLE)
    jumelles = _ligne(client, b).get("jumelles")
    assert isinstance(jumelles, list)
    assert sorted(jumelles, key=lambda j: j["id"]) == [
        {"id": a, "source": "eures"},
        {"id": c, "source": "forem"},
    ]


def test_critere_7_sans_jumelle_liste_vide(client):
    oid = _offre()
    _parcours(oid, CLE)
    assert _ligne(client, oid).get("jumelles") == []


# ---------------------------------------------------------------------------
# Des clés différentes
# ---------------------------------------------------------------------------


def test_critere_8_meme_entreprise_meme_titre_cles_differentes(client):
    a = _offre(title=".NET Developer", company="Sander", source="eures", jours=4)
    b = _offre(title=".NET Developer", company="Sander", source="actiris", jours=2)
    _parcours(a, CLE)
    _parcours(b, AUTRE_CLE)
    toutes = _toutes(client)
    assert a in toutes and b in toutes


def test_critere_9_texte_identique_cles_differentes(client):
    texte = "Rejoignez Sander comme développeur Laravel. " * 20
    a = _offre(title="Laravel Developer", company="Sander", description=texte)
    b = _offre(title="Laravel Developer", company="Sander", description=texte)
    _parcours(a, CLE)
    _parcours(b, AUTRE_CLE)
    toutes = _toutes(client)
    assert a in toutes and b in toutes


# ---------------------------------------------------------------------------
# Pas de clé
# ---------------------------------------------------------------------------


def test_critere_10_aucune_cle_entreprise_et_titre(client):
    a = _offre(title="Data Engineer Python", company="Sopra", jours=5)
    b = _offre(title="Data Engineer Python", company="Sopra", jours=2)
    toutes = _toutes(client)
    assert b in toutes and a not in toutes
    assert _file(client, a)["motif"] == "doublon"


def test_critere_11_une_seule_cle(client):
    a = _offre(title="Développeur Python", company="Sopra", jours=5)
    b = _offre(title="Développeur Python", company="Sopra", jours=2)
    _parcours(a, CLE)
    toutes = _toutes(client)
    assert len([i for i in toutes if i in (a, b)]) == 1


def test_critere_12_inconnue_ou_sans_lien_comptent_sans_cle(client):
    # Fin « inconnue » : sa clé gardée ne compte pas. Si elle comptait, les deux
    # clés différeraient et feraient deux lignes ; sans clé, la règle d'avant joue.
    a = _offre(title="Développeur Python", company="Sopra", jours=5)
    b = _offre(title="Développeur Python", company="Sopra", jours=2)
    _parcours(a, AUTRE_CLE, fin_forme="inconnue")
    _parcours(b, CLE)
    assert len([i for i in _toutes(client) if i in (a, b)]) == 1
    # « Sans lien » : aucune adresse de départ, aucun parcours.
    c = _offre(title="Backend Python", company="Proximus", url="", jours=5)
    d = _offre(title="Backend Python", company="Proximus", jours=2)
    _parcours(d, CLE + "/autre")
    r = client.get(f"/offers/{c}/parcours")
    assert r.json()["etat"] == "sans lien"
    assert len([i for i in _toutes(client) if i in (c, d)]) == 1


def test_critere_13_entreprises_differentes_sans_cle(client):
    a = _offre(title="Développeur Python", company="Sopra")
    b = _offre(title="Développeur Python", company="Proximus")
    toutes = _toutes(client)
    assert a in toutes and b in toutes


# ---------------------------------------------------------------------------
# Déjà traitée
# ---------------------------------------------------------------------------


def _traitee_et_soeur(etat: str = "candidature_envoyee") -> tuple[int, int]:
    a = _offre(title="Laravel Developer", company="Sander", source="eures", jours=6)
    b = _offre(
        title="Laravel developer", company="OFFRE D'UNE AUTRE REGION", jours=1
    )
    _etat(a, etat)
    _parcours(a, CLE)
    _parcours(b, CLE)
    return a, b


def test_critere_14_soeur_d_une_offre_envoyee_hors_files(client):
    _, b = _traitee_et_soeur()
    assert b not in _toutes(client)


def test_critere_15_motif_deja_traitee(client):
    _, b = _traitee_et_soeur()
    assert _file(client, b)["motif"] == "déjà traitée"


def test_critere_16_porte_l_offre_traitee_et_son_etat(client):
    a, b = _traitee_et_soeur()
    assert _file(client, b).get("meme_offre_que") == {
        "id": a,
        "etat": "candidature_envoyee",
    }


def test_critere_17_les_huit_etats(client):
    soeurs = []
    for etat in ETATS_TRAITES:
        a = _offre(company=f"Traitée {etat}", jours=6)
        b = _offre(company=f"Sœur {etat}", jours=1)
        _etat(a, etat)
        _parcours(a, f"{CLE}/{etat}")
        _parcours(b, f"{CLE}/{etat}")
        soeurs.append((b, a, etat))
    toutes = _toutes(client)
    for b, a, etat in soeurs:
        assert b not in toutes, etat
        reponse = _file(client, b)
        assert reponse["motif"] == "déjà traitée", etat
        assert reponse["meme_offre_que"] == {"id": a, "etat": etat}


def test_critere_18_ecartee_sort_ses_deux_jumelles(client):
    a = _offre(company="Actiris", jours=6)
    b = _offre(company="EURES", jours=2)
    c = _offre(company="Forem", jours=1)
    _etat(a, "ecartee")
    for oid in (a, b, c):
        _parcours(oid, CLE)
    toutes = _toutes(client)
    assert b not in toutes and c not in toutes
    assert _file(client, b)["motif"] == "déjà traitée"
    assert _file(client, c)["motif"] == "déjà traitée"


def test_critere_19_traitee_ne_sort_que_par_la_cle(client):
    a = _offre(title="Laravel Developer", company="Sander", jours=6)
    b = _offre(title="Laravel Developer", company="Sander", jours=1)
    _etat(a, "candidature_envoyee")
    _parcours(a, CLE)
    _parcours(b, AUTRE_CLE)
    assert b in _ids(client, "principale")
    assert _file(client, b).get("meme_offre_que") is None


def test_critere_20_fermee_ne_garde_pas_la_ligne(client):
    a = _offre(company="Sander", jours=1)
    b = _offre(company="OFFRE D'UNE AUTRE REGION", jours=4)
    _parcours(a, CLE)
    _parcours(b, CLE)
    _expiree(a)
    toutes = _toutes(client)
    assert b in toutes and a not in toutes
    assert _ligne(client, b).get("jumelles") == []


# ---------------------------------------------------------------------------
# Lire le parcours des offres déjà traitées
# ---------------------------------------------------------------------------

EURES_API = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
PAGE_B = "https://emploi.test/b"
PAGE_SANDER = "https://www.wearesander.com/fr/jobs/laravel-developer/87727"


def _eures(lien: str) -> str:
    consigne = f'<p>Postulez <a href="{lien}">ici</a></p>'
    return json.dumps({"jvProfiles": {"fr": {"applicationInstructions": [consigne]}}})


class Toile:
    """Une réponse par adresse, chaque demande comptée ; une adresse inconnue ne
    répond pas (délai dépassé)."""

    def __init__(self, pages: dict) -> None:
        self.pages = pages
        self.demandes: list[str] = []

    def __call__(self, adresse: str):
        self.demandes.append(adresse)
        rep = self.pages.get(adresse)
        if rep is None:
            raise requests.exceptions.Timeout(adresse)
        return rep


def _rep(adresse: str, texte: str) -> SimpleNamespace:
    return SimpleNamespace(chaine=[(adresse, 200)], texte=texte)


@pytest.fixture
def toile(monkeypatch) -> Toile:
    eures_a = EURES_API.format(id="AAA")
    eures_c = EURES_API.format(id="CCC")
    t = Toile(
        {
            eures_a: _rep(eures_a, _eures(PAGE_SANDER)),
            eures_c: _rep(eures_c, _eures(PAGE_SANDER)),
            PAGE_SANDER: _rep(PAGE_SANDER, "<html><title>Laravel</title></html>"),
            PAGE_B: _rep(PAGE_B, "<html><title>Laravel</title></html>"),
        }
    )
    reseau = importlib.import_module("orchestrator.job_search.parcours.reseau")
    monkeypatch.setattr(reseau, "lire", t)
    monkeypatch.setattr(reseau, "attendre", lambda secondes: None)
    monkeypatch.setattr(
        expiration_service,
        "check_url",
        lambda url: (200, datetime.now(timezone.utc).isoformat()),
    )
    return t


def _verifier(client, *ids: int) -> None:
    r = client.post("/offers/check-expirations", json={"offer_ids": list(ids)})
    assert r.status_code == 204, r.text


def test_critere_21_verification_lit_le_parcours_de_la_traitee(client, toile):
    a = _offre(source="eures", source_id="AAA", company="Sander", jours=6)
    b = _offre(url=PAGE_B, company="OFFRE D'UNE AUTRE REGION", jours=1)
    _etat(a, "candidature_envoyee")
    assert client.get(f"/offers/{a}/parcours").json()["etat"] == "jamais lu"
    _verifier(client, b)
    assert client.get(f"/offers/{a}/parcours").json()["etat"] == "lu"


def test_critere_22_traitee_deja_lue_pas_relue(client, toile):
    a = _offre(source="eures", source_id="AAA", company="Sander", jours=6)
    b = _offre(url=PAGE_B, company="OFFRE D'UNE AUTRE REGION", jours=1)
    _etat(a, "candidature_envoyee")
    _parcours(a, CLE)
    _verifier(client, b)
    assert EURES_API.format(id="AAA") not in toile.demandes
    assert PAGE_B in toile.demandes


def test_critere_23_jamais_triee_non_designee_pas_lue(client, toile):
    _offre(source="eures", source_id="CCC", company="Sander", jours=6)
    b = _offre(url=PAGE_B, company="OFFRE D'UNE AUTRE REGION", jours=1)
    _verifier(client, b)
    assert EURES_API.format(id="CCC") not in toile.demandes


# ---------------------------------------------------------------------------
# Les nombres
# ---------------------------------------------------------------------------


def test_critere_24_nombres(client):
    a = _offre(company="Sander", jours=4)
    b = _offre(company="OFFRE D'UNE AUTRE REGION", jours=2)
    _parcours(a, CLE)
    _parcours(b, CLE)
    reponse = _get(client, file="principale")
    assert reponse["nombres"]["file_principale"] == 1
    assert reponse["hors_files"].get("doublon") == 1


def test_critere_25_les_deux_files_partagent_la_regle(client):
    # « Data Analyst » range l'offre en « Data et analyse », file « À étudier ».
    a = _offre(title="Data Analyst", company="Sander", jours=4)
    b = _offre(title="Développeur Python", company="Autre", jours=2)
    _parcours(a, CLE)
    _parcours(b, CLE)
    toutes = _toutes(client)
    assert len([i for i in toutes if i in (a, b)]) == 1
