"""Tests EXE-210 — la liste « À postuler » et la file « À étudier ».

Chaque test pose sa base (fixture `_isolate_db_path` de conftest.py) et son
profil personnel dans un dossier temporaire, PROFILE_PATH pointé dessus par
monkeypatch (H7, H11). Aucun test ne lit ni n'écrit sous data/, aucun ne lit
profiles/gregoire.yaml. Chaque critère change une seule chose à l'offre témoin.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths
from orchestrator.job_search.scoring.hors_perimetre import (
    HorsPerimetreCause,
    derive_hors_perimetre,
)
from orchestrator.job_search.sources.base import ExtractedFacts, SeniorityLevel

IA = "IA et automatisation"
DEV = "Développeur"
DATA = "Data et analyse"

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


@pytest.fixture(autouse=True)
def _profil(tmp_path, monkeypatch):
    chemin = tmp_path / "profil_personnel.yaml"
    chemin.write_text(PROFIL, encoding="utf-8")
    monkeypatch.setattr(paths, "PROFILE_PATH", chemin)
    return chemin


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
    location="Bruxelles",
    contract_type="directhire",
    ad_language="fr",
    domain="backend",
    seniority="intermediate",
    role="ic",
    techs=(("python", "core"),),
    langues=(),
    description="Poste de développeur dans une équipe produit.",
    jours=3,
    source="actiris",
    filtered_out=0,
    facts=True,
) -> int:
    """Insère une offre (le témoin, sauf ce que le critère change) et rend son id."""
    _compteur["n"] += 1
    n = _compteur["n"]
    # Une entreprise par offre : deux témoins ne sont pas un doublon (H6).
    company = company if company is not None else f"Acme {n}"
    fetched = (datetime.now(timezone.utc) - timedelta(days=jours, hours=1)).isoformat()
    facts_json = (
        json.dumps(
            {
                "seniority_required": seniority,
                "techs_required": [{"name": t, "importance": i} for t, i in techs],
                "domain": domain,
                "role_level": role,
                "langues_requises": list(langues),
            }
        )
        if facts
        else None
    )
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (source, source_id, fingerprint, title, company, "
            "location, contract_type, url, fetched_at, description, ad_language, "
            "extracted_facts_json, filtered_out) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source,
                f"id-{n}",
                f"fp-{n}",
                title,
                company,
                location,
                contract_type,
                f"https://annonce.test/{n}",
                fetched,
                description,
                ad_language,
                facts_json,
                filtered_out,
            ),
        )
        return cur.lastrowid


def _get(client, **params) -> dict:
    r = client.get("/a-postuler", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client, file=None) -> list[int]:
    params = {"file": file} if file else {}
    return [ligne["id"] for ligne in _get(client, **params)["lignes"]]


def _ligne(client, offer_id, file=None) -> dict:
    params = {"file": file} if file else {}
    for ligne in _get(client, **params)["lignes"]:
        if ligne["id"] == offer_id:
            return ligne
    raise AssertionError(f"offre {offer_id} absente de la file {file}")


def _dehors(client, offer_id) -> None:
    assert offer_id not in _ids(client)
    assert offer_id not in _ids(client, "a_etudier")


# --- La liste --------------------------------------------------------------


def test_critere_01_temoin_rang_1(client):
    oid = _offre()
    lignes = _get(client)["lignes"]
    assert [(li["id"], li["rang"]) for li in lignes] == [(oid, 1)]


def test_critere_02_rangs_1_2_3(client):
    for _ in range(3):
        _offre()
    assert [li["rang"] for li in _get(client)["lignes"]] == [1, 2, 3]


# --- Le lieu ---------------------------------------------------------------


@pytest.mark.parametrize(
    "lieu", ["67 - Strasbourg", "59 - Forest-sur-Marque", "Gand, Belgique"]
)
def test_criteres_03_04_05_lieux_dehors(client, lieu):
    _dehors(client, _offre(location=lieu))


def test_critere_06_louvain_la_neuve(client):
    ligne = _ligne(client, _offre(location="Louvain-la-Neuve, Belgique"))
    assert "lieu non précisé" not in ligne["marques"]


def test_critere_07_belgique_seule(client):
    ligne = _ligne(client, _offre(location="Belgique"))
    assert "lieu non précisé" in ligne["marques"]


# --- Mes refus -------------------------------------------------------------


def test_critere_08_contrats_refuses(client):
    ids = [_offre(contract_type=c) for c in ("selfemployed", "Freelance", "LIB")]
    for oid in ids:
        _dehors(client, oid)


def test_critere_09_stagiaire(client):
    _dehors(client, _offre(title="Stagiaire développeur"))


def test_critere_10_internal_pas_un_stage(client):
    oid = _offre(title="Fullstack Engineer - Internal AI Platform")
    assert oid in _ids(client)


def test_critere_11_annonce_en_neerlandais(client):
    _dehors(client, _offre(ad_language="nl"))


def test_critere_12_neerlandais_exige(client):
    oid = _offre(langues=["nederlands"], description="Néerlandais courant exigé.")
    _dehors(client, oid)


def test_critere_13_neerlandais_atout(client):
    oid = _offre(langues=["nederlands"], description="Le néerlandais est un atout.")
    assert "néerlandais en atout" in _ligne(client, oid)["marques"]


@pytest.mark.parametrize("role", ["lead", "manager"])
def test_criteres_14_15_role(client, role):
    _dehors(client, _offre(role=role))


def test_critere_16_senior_dans_le_titre(client):
    _dehors(client, _offre(title="Senior Java Developer"))


def test_critere_17_senior_extrait_seulement(client):
    oid = _offre(title="Java Developer", seniority="senior")
    assert oid in _ids(client)


@pytest.mark.parametrize(
    "titre", ["Formateur n8n", "Ingénieur robotique", "Network Engineer"]
)
def test_criteres_18_19_20_titres_refuses(client, titre):
    _dehors(client, _offre(title=titre))


def test_critere_21_expiree(client):
    oid = _offre()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO expirations (offer_id, expired) VALUES (?, 1)", (oid,)
        )
    _dehors(client, oid)


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


def test_critere_22_huit_etats(client):
    ids = []
    for etat in ETATS_TRAITES:
        oid = _offre()
        with _conn() as conn:
            conn.execute(
                "INSERT INTO etats_offre (offer_id, etat) VALUES (?, ?)", (oid, etat)
            )
        ids.append(oid)
    for oid in ids:
        _dehors(client, oid)


def test_critere_23_filtree_ingestion(client):
    _dehors(client, _offre(filtered_out=1))


def test_critere_24_sans_faits_ou_sans_techno(client):
    sans_faits = _offre(facts=False)
    sans_techno = _offre(techs=())
    _dehors(client, sans_faits)
    _dehors(client, sans_techno)


# --- Les familles et les deux files ----------------------------------------


def test_critere_25_temoin_developpeur(client):
    assert _ligne(client, _offre())["famille"] == DEV


def test_critere_26_ia(client):
    oid = _offre(domain="fullstack", techs=(("llm", "core"), ("rag", "core")))
    assert _ligne(client, oid)["famille"] == IA


def test_critere_27_automatisation(client):
    oid = _offre(
        domain="devops",
        title="Chef de projet en automatisation",
        techs=(("power automate", "core"),),
    )
    assert _ligne(client, oid)["famille"] == IA


def _data_engineering() -> int:
    return _offre(
        domain="data_engineering", techs=(("sql", "core"), ("airflow", "core"))
    )


def test_critere_28_data_pas_principale(client):
    assert _data_engineering() not in _ids(client)


def test_critere_29_data_a_etudier(client):
    oid = _data_engineering()
    assert _ligne(client, oid, "a_etudier")["famille"] == DATA


def test_critere_30_data_science(client):
    oid = _offre(domain="data_science")
    assert oid in _ids(client, "a_etudier")


def test_critere_31_business_analyst(client):
    oid = _offre(title="Business Analyst", domain="other", techs=(("sql", "core"),))
    assert oid in _ids(client, "a_etudier")


def test_critere_32_analyste_fonctionnel(client):
    oid = _offre(title="Analyste fonctionnel", domain="backend")
    assert oid in _ids(client, "a_etudier")
    assert oid not in _ids(client)


def test_critere_33_sales_hors_famille(client):
    oid = _offre(
        domain="other",
        title="Sales Development Representative",
        techs=(("claude", "required"),),
    )
    _dehors(client, oid)


def test_critere_34_a_etudier_meme_refus_lieu(client):
    _dehors(client, _offre(domain="data_science", location="67 - Strasbourg"))


def test_critere_35_a_etudier_cloud(client):
    _dehors(client, _offre(domain="data_science", title="Cloud Engineer"))


def test_critere_36_aucune_offre_dans_les_deux_files(client):
    _offre()
    _offre(domain="fullstack", techs=(("llm", "core"), ("rag", "core")))
    _offre(
        domain="devops",
        title="Chef de projet en automatisation",
        techs=(("power automate", "core"),),
    )
    _data_engineering()
    _offre(domain="data_science")
    _offre(title="Business Analyst", domain="other", techs=(("sql", "core"),))
    _offre(title="Analyste fonctionnel", domain="backend")
    principale = set(_ids(client))
    a_etudier = set(_ids(client, "a_etudier"))
    assert len(principale) == 3 and len(a_etudier) == 4
    assert principale.isdisjoint(a_etudier)


# --- Les doublons ----------------------------------------------------------


def test_critere_37_doublon(client):
    ancienne = _offre(
        title="Data Support Specialist", company="Sopra", source="eures", jours=5
    )
    recente = _offre(
        title="Data Support Specialist M/W/X",
        company="Sopra",
        source="actiris",
        jours=2,
    )
    ids = _ids(client)
    assert recente in ids and ancienne not in ids


# --- L'ordre ---------------------------------------------------------------


def _ia(**kw) -> int:
    return _offre(domain="fullstack", techs=(("llm", "core"), ("rag", "core")), **kw)


def test_critere_38_recence_avant_famille(client):
    ia = _ia(jours=15)
    dev = _offre(jours=14)
    assert _ids(client) == [dev, ia]


def test_critere_39_ia_avant_developpeur(client):
    dev = _offre(jours=2)
    ia = _ia(jours=10)
    assert _ids(client) == [ia, dev]


def test_critere_40_niveau(client):
    intermediaire = _offre(techs=(("python", "core"), ("cobol", "core")))
    senior = _offre(seniority="senior", title="Java Developer")
    lignes = _get(client)["lignes"]
    assert [li["id"] for li in lignes] == [intermediaire, senior]
    assert lignes[0]["atteignabilite"] < lignes[1]["atteignabilite"]


def test_critere_41_atteignabilite(client):
    basse = _offre(techs=(("python", "core"), ("cobol", "core")))
    haute = _offre()
    assert _ids(client) == [haute, basse]


def test_critere_42_a_etudier_recence(client):
    vieille = _offre(domain="data_science", jours=15)
    recente = _offre(domain="data_science", jours=14)
    assert _ids(client, "a_etudier") == [recente, vieille]


# --- Ce que dit chaque ligne -----------------------------------------------


def test_critere_43_champs(client):
    oid = _offre(company="Acme")
    ligne = _ligne(client, oid)
    assert ligne["id"] == oid
    assert ligne["titre"] == "Développeur Python"
    assert ligne["entreprise"] == "Acme"
    assert ligne["lieu"] == "Bruxelles"
    assert ligne["source"] == "actiris"
    assert ligne["url"].startswith("https://annonce.test/")
    assert ligne["contrat"] == "directhire"
    assert ligne["jours"] == 3
    assert ligne["famille"] == DEV
    assert ligne["origine_famille"]
    assert ligne["niveau"] == "intermediate"
    assert ligne["marques"] == ["jamais vérifiée"]


def test_critere_44_atteignabilite(client):
    oid = _offre(techs=(("python", "core"), ("cobol", "required")))
    ligne = _ligne(client, oid)
    assert ligne["atteignabilite"] == 36
    assert ligne["technos_connues"] == ["python"]
    assert ligne["technos_absentes"] == ["cobol"]


# --- Filtrer et trier ------------------------------------------------------


def test_critere_45_filtre_famille(client):
    _ia()
    _offre()
    lignes = _get(client, famille="developpeur")["lignes"]
    assert lignes and all(li["famille"] == DEV for li in lignes)


def test_critere_46_rang_conserve(client):
    _ia()
    temoin = _offre()
    lignes = _get(client, famille="developpeur")["lignes"]
    assert [(li["id"], li["rang"]) for li in lignes] == [(temoin, 2)]


def test_critere_47_recentes(client):
    recente = _offre(jours=3)
    _offre(jours=20)
    lignes = _get(client, recentes="true")["lignes"]
    assert [li["id"] for li in lignes] == [recente]


def test_critere_48_recherche(client):
    par_entreprise = _offre(company="SANDER SA")
    par_titre = _offre(title="Développeur Sander")
    _offre()
    ids = {li["id"] for li in _get(client, q="sander")["lignes"]}
    assert ids == {par_entreprise, par_titre}


def test_critere_49_tri_entreprise(client):
    _offre(company="Gamma")
    _offre(company="alpha")
    _offre(company="Beta")
    asc = [li["entreprise"] for li in _get(client, tri="entreprise")["lignes"]]
    desc = [
        li["entreprise"]
        for li in _get(client, tri="entreprise", ordre="desc")["lignes"]
    ]
    assert asc == ["alpha", "Beta", "Gamma"]
    assert desc == ["Gamma", "Beta", "alpha"]


TRIS = {
    "rang": lambda li: li["rang"],
    "entreprise": lambda li: li["entreprise"].casefold(),
    "contrat": lambda li: li["contrat"].casefold(),
    "lieu": lambda li: li["lieu"].casefold(),
    "famille": lambda li: li["famille"],
    "recuperee": lambda li: -li["jours"],
    "atteignabilite": lambda li: li["atteignabilite"],
}


def test_critere_50_sept_tris(client):
    _offre(
        company="Beta",
        contract_type="interim",
        location="Wavre",
        jours=1,
        techs=(("python", "core"), ("cobol", "core")),
    )
    _ia(company="Gamma", contract_type="cdd", location="Nivelles", jours=5)
    _offre(company="Alpha", contract_type="directhire", location="Bruxelles", jours=9)
    for tri, cle in TRIS.items():
        lignes = _get(client, tri=tri)["lignes"]
        valeurs = [cle(li) for li in lignes]
        assert len(valeurs) == 3, tri
        assert len(set(valeurs)) >= 2, tri
        assert valeurs == sorted(valeurs), tri
        inverses = [cle(li) for li in _get(client, tri=tri, ordre="desc")["lignes"]]
        assert inverses == sorted(valeurs, reverse=True), tri


def test_critere_51_tri_inconnu(client):
    _offre()
    assert client.get("/a-postuler", params={"tri": "salaire"}).status_code == 422


# --- Les nombres -----------------------------------------------------------


def _quatre_offres():
    _ia()
    _offre()
    _offre(jours=30)
    _offre(domain="data_science")


def test_critere_52_nombres(client):
    _quatre_offres()
    nombres = _get(client)["nombres"]
    assert nombres["file_principale"] == 3
    assert nombres["file_a_etudier"] == 1
    assert nombres["familles"][IA] == 1
    assert nombres["familles"][DEV] == 2


def test_critere_53_recentes(client):
    _quatre_offres()
    assert _get(client)["nombres"]["recentes"] == 2
    assert _get(client, file="a_etudier")["nombres"]["recentes"] == 1


def test_critere_54_nombres_file_entiere(client):
    _quatre_offres()
    entiers = _get(client)["nombres"]
    assert _get(client, famille="ia")["nombres"] == entiers
    assert _get(client, recentes="true")["nombres"] == entiers
    assert _get(client, q="zzz")["nombres"] == entiers


# --- Pourquoi une offre n'y est pas ----------------------------------------


def test_critere_55_motifs(client):
    _offre()
    _offre(location="67 - Strasbourg")
    _offre(location="Gand, Belgique")
    _offre(title="Senior Java Developer")
    hors = _get(client)["hors_files"]
    assert hors == {"lieu": 2, "titre senior": 1}


def test_critere_56_file_et_rang(client):
    _ia()
    temoin = _offre()
    r = client.get(f"/offers/{temoin}/a-postuler")
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["file"] == "principale"
    assert corps["rang"] == 2


def test_critere_57_motif(client):
    oid = _offre(location="67 - Strasbourg", contract_type="Freelance")
    r = client.get(f"/offers/{oid}/a-postuler")
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["file"] is None
    assert corps["motif"] == "lieu"


# --- Le stage lu dans « Internal » -----------------------------------------


def _facts() -> ExtractedFacts:
    return ExtractedFacts(
        seniority_required=SeniorityLevel.intermediate,
        techs_required=[{"name": "python", "importance": "core"}],
        domain="backend",
    )


def test_critere_58_internal_pas_contrat():
    causes = derive_hors_perimetre(
        _facts(), title="Fullstack Software Engineer - Internal Agentic AI Platform"
    )
    assert HorsPerimetreCause.contrat not in causes


def test_critere_59_intern_contrat():
    causes = derive_hors_perimetre(_facts(), title="Software Engineer Intern")
    assert HorsPerimetreCause.contrat in causes


# --- Profil personnel absent (H7) ------------------------------------------


def test_profil_absent_rend_une_erreur(client, tmp_path, monkeypatch):
    _offre()
    monkeypatch.setattr(paths, "PROFILE_PATH", tmp_path / "absent.yaml")
    r = client.get("/a-postuler")
    assert r.status_code == 503
    assert "profil" in r.json()["detail"].lower()
