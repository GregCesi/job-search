"""Tests EXE-221 — une offre lue senior quitte « À postuler » pour « À étudier »,
groupe « trop senior ? ».

Outillage repris de `test_exe210_a_postuler.py` (H9) : base posée par la fixture
`_isolate_db_path` de conftest.py, profil personnel dans un dossier temporaire.
Aucun test ne lit ni n'écrit sous data/, aucun site n'est appelé. Chaque critère
change une seule chose à l'offre témoin.
"""

from tests.test_exe210_a_postuler import (  # noqa: F401 (fixtures)
    DATA,
    DEV,
    IA,
    _dehors,
    _get,
    _ids,
    _ligne,
    _offre,
    _profil,
    client,
)

TROP_SENIOR = "trop senior ?"
INTERESSANT = "est-ce intéressant ?"


def _motif(client, offer_id) -> str:
    r = client.get(f"/offers/{offer_id}/a-postuler")
    assert r.status_code == 200, r.text
    return r.json()["motif"]


# --- Le niveau décide de la file -------------------------------------------


def test_critere_01_senior_hors_file_principale(client):
    oid = _offre(seniority="senior")
    assert oid not in _ids(client)


def test_critere_02_senior_dans_a_etudier(client):
    oid = _offre(seniority="senior")
    assert oid in _ids(client, "a_etudier")


def test_critere_03_groupe_trop_senior(client):
    oid = _offre(seniority="senior")
    assert _ligne(client, oid, "a_etudier")["groupe"] == TROP_SENIOR


def test_critere_04_famille_gardee(client):
    oid = _offre(seniority="senior")
    assert _ligne(client, oid, "a_etudier")["famille"] == DEV


def test_critere_05_lead(client):
    oid = _offre(seniority="lead")
    assert oid not in _ids(client)
    assert _ligne(client, oid, "a_etudier")["groupe"] == TROP_SENIOR


def test_critere_06_ia_senior(client):
    oid = _offre(domain="ai_engineering", seniority="senior")
    assert oid not in _ids(client)
    ligne = _ligne(client, oid, "a_etudier")
    assert ligne["groupe"] == TROP_SENIOR
    assert ligne["famille"] == IA


def test_critere_07_junior_et_intermediate_restent(client):
    junior = _offre(seniority="junior")
    intermediaire = _offre(seniority="intermediate")
    principale = _ids(client)
    assert junior in principale and intermediaire in principale
    a_etudier = _ids(client, "a_etudier")
    assert junior not in a_etudier and intermediaire not in a_etudier


# --- Le groupe des postes data ---------------------------------------------


def test_critere_08_data_intermediate(client):
    oid = _offre(domain="data_science", seniority="intermediate")
    assert _ligne(client, oid, "a_etudier")["groupe"] == INTERESSANT


def test_critere_09_data_senior(client):
    oid = _offre(domain="data_science", seniority="senior")
    ligne = _ligne(client, oid, "a_etudier")
    assert ligne["groupe"] == INTERESSANT
    assert ligne["famille"] == DATA


def test_critere_10_principale_sans_groupe(client):
    _offre()
    _offre(domain="ai_engineering")
    _offre(seniority="senior")
    lignes = _get(client)["lignes"]
    assert len(lignes) == 2
    assert all(li["groupe"] is None for li in lignes)


# --- Les refus restent les mêmes -------------------------------------------


def test_critere_11_titre_senior(client):
    oid = _offre(title="Senior Java Developer")
    _dehors(client, oid)
    assert _motif(client, oid) == "titre senior"


def test_critere_12_senior_et_lieu(client):
    oid = _offre(seniority="senior", location="67 - Strasbourg")
    _dehors(client, oid)
    assert _motif(client, oid) == "lieu"


def test_critere_13_senior_et_role_lead(client):
    oid = _offre(seniority="senior", role="lead")
    _dehors(client, oid)
    assert _motif(client, oid) == "rôle lead ou manager"


# --- Filtrer par groupe ----------------------------------------------------


def _jeu_mixte():
    senior = _offre(seniority="senior", jours=20)
    data = _offre(domain="data_science", jours=3)
    return senior, data


def test_critere_14_filtre_trop_senior(client):
    senior, _ = _jeu_mixte()
    lignes = _get(client, file="a_etudier", groupe="trop_senior")["lignes"]
    assert [li["id"] for li in lignes] == [senior]
    assert all(li["groupe"] == TROP_SENIOR for li in lignes)


def test_critere_15_filtre_interessant(client):
    _, data = _jeu_mixte()
    lignes = _get(client, file="a_etudier", groupe="interessant")["lignes"]
    assert [li["id"] for li in lignes] == [data]
    assert all(li["groupe"] == INTERESSANT for li in lignes)


def test_critere_16_groupe_inconnu(client):
    _jeu_mixte()
    r = client.get("/a-postuler", params={"file": "a_etudier", "groupe": "autre"})
    assert r.status_code == 422


def test_critere_17_rang_conserve(client):
    senior, data = _jeu_mixte()
    entiers = _get(client, file="a_etudier")["lignes"]
    assert [(li["id"], li["rang"]) for li in entiers] == [(data, 1), (senior, 2)]
    lignes = _get(client, file="a_etudier", groupe="trop_senior")["lignes"]
    assert [(li["id"], li["rang"]) for li in lignes] == [(senior, 2)]


# --- Les nombres -----------------------------------------------------------


def _quatre_offres():
    _offre(seniority="intermediate")
    _offre(seniority="senior")
    _offre(seniority="senior", jours=30)
    _offre(domain="data_science")


def test_critere_18_nombres(client):
    _quatre_offres()
    nombres = _get(client)["nombres"]
    assert nombres["file_principale"] == 1
    assert nombres["file_a_etudier"] == 3
    assert nombres["groupes"] == {TROP_SENIOR: 2, INTERESSANT: 1}


def test_critere_19_nombres_file_entiere(client):
    _quatre_offres()
    entiers = _get(client, file="a_etudier")["nombres"]
    for params in ({"groupe": "trop_senior"}, {"recentes": "true"}, {"q": "zzz"}):
        assert _get(client, file="a_etudier", **params)["nombres"] == entiers
    principale = _get(client)["nombres"]
    assert _get(client, groupe="interessant")["nombres"] == principale


def test_critere_20_famille_developpeur(client):
    _quatre_offres()
    assert _get(client)["nombres"]["familles"][DEV] == 1


# --- L'ordre dans « À étudier » --------------------------------------------


def test_critere_21_recence(client):
    vieille = _offre(seniority="senior", jours=15)
    recente = _offre(seniority="senior", jours=14)
    assert _ids(client, "a_etudier") == [recente, vieille]


def test_critere_22_atteignabilite(client):
    basse = _offre(seniority="senior", techs=(("python", "core"), ("cobol", "core")))
    haute = _offre(seniority="senior")
    lignes = _get(client, file="a_etudier", groupe="trop_senior")["lignes"]
    assert [li["id"] for li in lignes] == [haute, basse]
    assert lignes[0]["atteignabilite"] > lignes[1]["atteignabilite"]


def test_critere_22_atteignabilite_avant_famille(client):
    """H3 : dans « À étudier », tranche d'âge puis atteignabilité ; la famille
    n'entre pas dans l'ordre."""
    dev_haute = _offre(seniority="senior")
    ia_basse = _offre(
        domain="ai_engineering",
        seniority="senior",
        techs=(("python", "core"), ("cobol", "core")),
    )
    lignes = _get(client, file="a_etudier", groupe="trop_senior")["lignes"]
    assert [li["id"] for li in lignes] == [dev_haute, ia_basse]


# --- Pourquoi une offre est là ---------------------------------------------


def test_critere_23_offre_senior(client):
    _offre(domain="data_science", jours=2)
    oid = _offre(seniority="senior", jours=20)
    r = client.get(f"/offers/{oid}/a-postuler")
    assert r.status_code == 200, r.text
    corps = r.json()
    assert corps["file"] == "a_etudier"
    assert corps["rang"] == 2
    assert corps["groupe"] == TROP_SENIOR
