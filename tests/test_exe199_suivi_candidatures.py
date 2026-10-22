"""Tests EXE-199 — Suivi remplace Retenues : toutes mes candidatures,
l'étape, le dernier geste et le temps écoulé depuis, en cours avant
terminées, un filtre par étape avec ses nombres, et le tri par verdict qui
range correctement une offre qui ne porte qu'une revue hors périmètre, sans
aucun geste. DB sous `tmp_path`, horloge figée, aucun appel modèle.

Critère 2 : le gap réel vit dans `VIEW_PRESETS.suivi` (web/app/stores/offers.ts)
— un appel API sans filtre rendait déjà tout, avant comme après la fiche (la
route ne filtre jamais par défaut). Le test de régression qui est rouge avant
la fiche est donc le test de motif sur le fichier front (TestCritere2Et3
ci-dessous) ; le test API qui pose les quatre offres (H14) est une preuve
supplémentaire du comportement observable, pas le discriminant rouge/vert."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats

FUSEAU_BRUXELLES = ZoneInfo("Europe/Brussels")
WEB_APP = Path(__file__).resolve().parent.parent / "web" / "app"
OFFERS_STORE = WEB_APP / "stores" / "offers.ts"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    import api.main as api_main

    return TestClient(api_main.app)


@pytest.fixture(autouse=True)
def _no_real_cascade(monkeypatch):
    import api.cascade as cascade

    async def _noop(offer_id):
        return []

    monkeypatch.setattr(cascade, "launch_pieces", _noop)


def _figer_horloge(monkeypatch, iso_utc: str):
    fixe = datetime.fromisoformat(iso_utc)
    monkeypatch.setattr(suivi_etats, "maintenant", lambda: fixe)


def _insert_offer(
    db_path,
    offer_id,
    title="Titre",
    company="Acme",
    category="parfait",
    ad_language=None,
    hors_perimetre_reason=None,
    location="Strasbourg",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, category, ad_language, hors_perimetre_reason, location, "
            "filtered_out) VALUES (?, 'test', ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                offer_id,
                str(offer_id),
                f"fp{offer_id}",
                title,
                company,
                category,
                ad_language,
                hors_perimetre_reason,
                location,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _geste(client, offer_id, geste, **kwargs):
    body = {"geste": geste, **kwargs}
    resp = client.post(f"/offers/{offer_id}/geste", json=body)
    assert resp.status_code == 200, (offer_id, geste, resp.text)
    return resp


def _retenir(client, offer_id, effet_at=None):
    kwargs = {"effet_at": effet_at} if effet_at else {}
    _geste(client, offer_id, "retenir", **kwargs)


# ---------------------------------------------------------------------------
# Critères 2 et 3 — Suivi ne filtre ni catégorie, ni langue, ni périmètre, ni
# profil de vue (frontend.md : VIEW_PRESETS.suivi remplace VIEW_PRESETS.retenues)
# ---------------------------------------------------------------------------


class TestCritere2Et3VuePresetSuiviSansFiltre:
    def test_view_presets_suivi_necrit_aucun_filtre_de_perimetre(self):
        texte = OFFERS_STORE.read_text(encoding="utf-8")
        m = re.search(r"suivi:\s*\{([^}]*)\}", texte)
        assert m is not None, "VIEW_PRESETS.suivi introuvable"
        preset = m.group(1)
        assert "exclude_category" not in preset
        assert "hors_perimetre" not in preset
        assert "exclude_ad_language" not in preset
        assert "'retenu'" in preset

    def test_suivi_nest_plus_dans_la_liste_qui_envoie_view_profile(self):
        texte = OFFERS_STORE.read_text(encoding="utf-8")
        m = re.search(
            r"if \(\['cibles', 'gaps', 'filet'(.*?)\]\.includes\(activeView\.value\)\)",
            texte,
        )
        assert m is not None
        assert "suivi" not in m.group(1)
        assert "retenues" not in m.group(1)

    def test_candidate_view_type_porte_suivi_pas_retenues(self):
        texte = OFFERS_STORE.read_text(encoding="utf-8")
        assert "'suivi'" in texte
        assert "'retenues'" not in texte


class TestCritere2PreuveApiQuatreOffresProblematiques:
    """H14 : pose une retenue « hors », une en néerlandais, une hors
    périmètre, une hors de la zone du profil de vue — toutes dans Suivi
    (appel API sans aucun des filtres qu'envoyait l'ancienne vue Retenues)."""

    def test_toutes_les_retenues_apparaissent_sans_filtre(self, client, db_path):
        _insert_offer(db_path, 1, category="hors")
        _insert_offer(db_path, 2, category="parfait", ad_language="nl")
        _insert_offer(db_path, 3, category="parfait", hors_perimetre_reason="no_tech")
        _insert_offer(db_path, 4, category="parfait", location="Paris")
        for oid in (1, 2, 3, 4):
            _retenir(client, oid)

        resp = client.get("/offers", params={"verdict": "retenu"})
        ids = {row["id"] for row in resp.json()}
        assert ids == {1, 2, 3, 4}

        # L'ancien filtre de la vue Retenues les aurait masquées.
        ancien = client.get(
            "/offers",
            params={
                "verdict": "retenu",
                "exclude_category": "hors",
                "hors_perimetre": False,
                "exclude_ad_language": "nl",
            },
        )
        ids_ancien = {row["id"] for row in ancien.json()}
        assert 1 not in ids_ancien
        assert 2 not in ids_ancien
        assert 3 not in ids_ancien


# ---------------------------------------------------------------------------
# Critère 4 — chaque ligne porte l'étape, l'entreprise, l'intitulé, le
# dernier geste non annulé (et non le premier — mutant V3) et sa date d'effet
# ---------------------------------------------------------------------------


class TestCritere4LigneParCandidature:
    def test_ligne_porte_etape_entreprise_intitule_et_dernier_geste(
        self, client, db_path
    ):
        _insert_offer(db_path, 10, title="Dev", company="Acme")
        _retenir(client, 10, effet_at="2026-10-10T09:00:00+00:00")
        _geste(client, 10, "abandonner", effet_at="2026-10-18T09:00:00+00:00")

        resp = client.get("/offers", params={"verdict": "retenu"})
        row = next(r for r in resp.json() if r["id"] == 10)

        assert row.get("etape") == "abandonnee"
        assert row.get("company") == "Acme"
        assert row.get("title") == "Dev"
        # Mutant V3 : le dernier geste non annulé (abandonner), jamais le
        # premier (retenir).
        assert row.get("dernier_geste_libelle") == "Abandonner"
        assert row.get("dernier_geste_effet_at") == "2026-10-18T09:00:00+00:00"


# ---------------------------------------------------------------------------
# Critère 5 — temps écoulé en jours, compté à Bruxelles
# ---------------------------------------------------------------------------


class TestCritere5TempsEcouleEnJoursABruxelles:
    def test_il_y_a_n_jours(self, client, db_path, monkeypatch):
        _insert_offer(db_path, 20)
        _retenir(client, 20, effet_at="2026-10-18T09:00:00+00:00")
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")

        resp = client.get("/offers", params={"verdict": "retenu"})
        row = next(r for r in resp.json() if r["id"] == 20)
        assert row.get("temps_depuis_libelle") == "il y a 3 j"

    def test_aujourd_hui(self, client, db_path, monkeypatch):
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")
        _insert_offer(db_path, 21)
        _retenir(client, 21, effet_at="2026-10-21T08:00:00+00:00")

        resp = client.get("/offers", params={"verdict": "retenu"})
        row = next(r for r in resp.json() if r["id"] == 21)
        assert row.get("temps_depuis_libelle") == "aujourd'hui"

    def test_dans_n_jours_pour_un_entretien_a_venir(self, client, db_path, monkeypatch):
        _insert_offer(db_path, 22)
        _retenir(client, 22)
        _geste(client, 22, "marquer_envoyee")
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")
        _geste(client, 22, "entretien", effet_at="2026-10-23")

        resp = client.get("/offers", params={"verdict": "retenu"})
        row = next(r for r in resp.json() if r["id"] == 22)
        assert row.get("temps_depuis_libelle") == "dans 2 j"


# ---------------------------------------------------------------------------
# Critères 6-8 — ordre Suivi : en cours avant terminées (mutant V2), en cours
# triées par date du dernier geste croissante, terminées décroissante
# ---------------------------------------------------------------------------


class TestCriteres6a8OrdreSuivi:
    def test_en_cours_passent_avant_les_terminees(self, client, db_path, monkeypatch):
        _figer_horloge(monkeypatch, "2026-10-22T10:00:00+00:00")
        _insert_offer(db_path, 30)
        _insert_offer(db_path, 31)
        _retenir(client, 30, effet_at="2026-10-01T09:00:00+00:00")  # en cours
        _retenir(client, 31, effet_at="2026-10-01T09:00:00+00:00")
        _geste(
            client, 31, "abandonner", effet_at="2026-10-05T09:00:00+00:00"
        )  # terminée

        resp = client.get(
            "/offers", params={"verdict": "retenu", "sort": "suivi", "order": "asc"}
        )
        ids = [r["id"] for r in resp.json()]
        assert ids.index(30) < ids.index(31)

    def test_en_cours_le_plus_ancien_geste_dabord(self, client, db_path, monkeypatch):
        _figer_horloge(monkeypatch, "2026-10-22T10:00:00+00:00")
        _insert_offer(db_path, 40)
        _insert_offer(db_path, 41)
        _retenir(client, 40, effet_at="2026-10-15T09:00:00+00:00")
        _retenir(client, 41, effet_at="2026-10-10T09:00:00+00:00")

        resp = client.get(
            "/offers", params={"verdict": "retenu", "sort": "suivi", "order": "asc"}
        )
        ids = [r["id"] for r in resp.json()]
        assert ids.index(41) < ids.index(40)

    def test_terminees_la_plus_recente_dabord(self, client, db_path, monkeypatch):
        _figer_horloge(monkeypatch, "2026-10-22T10:00:00+00:00")
        _insert_offer(db_path, 50)
        _insert_offer(db_path, 51)
        _retenir(client, 50)
        _geste(client, 50, "abandonner", effet_at="2026-10-05T09:00:00+00:00")
        _retenir(client, 51)
        _geste(client, 51, "abandonner", effet_at="2026-10-18T09:00:00+00:00")

        resp = client.get(
            "/offers", params={"verdict": "retenu", "sort": "suivi", "order": "asc"}
        )
        ids = [r["id"] for r in resp.json()]
        assert ids.index(51) < ids.index(50)


# ---------------------------------------------------------------------------
# Critère 9 — filtre par étape avec ses nombres, décidés par l'API
# ---------------------------------------------------------------------------


class TestCritere9FiltreParEtapeAvecComptes:
    def test_comptes_par_etape_et_toutes(self, client, db_path):
        _insert_offer(db_path, 60)
        _insert_offer(db_path, 61)
        _retenir(client, 60)
        _retenir(client, 61)
        _geste(client, 61, "abandonner")

        resp = client.get("/offers/suivi/compte-etapes")
        assert resp.status_code == 200
        counts = resp.json()
        assert counts.get("retenue") == 1
        assert counts.get("abandonnee") == 1
        assert counts.get("toutes") == 2

    def test_filtre_par_etape_naffiche_que_cette_etape(self, client, db_path):
        _insert_offer(db_path, 62)
        _insert_offer(db_path, 63)
        _retenir(client, 62)
        _retenir(client, 63)
        _geste(client, 63, "abandonner")

        resp = client.get(
            "/offers", params={"verdict": "retenu", "etape": "abandonnee"}
        )
        ids = {r["id"] for r in resp.json()}
        assert ids == {63}

    def test_toutes_rend_la_liste_entiere(self, client, db_path):
        _insert_offer(db_path, 64)
        _insert_offer(db_path, 65)
        _retenir(client, 64)
        _retenir(client, 65)
        _geste(client, 65, "abandonner")

        resp = client.get("/offers", params={"verdict": "retenu"})
        ids = {r["id"] for r in resp.json()}
        assert ids == {64, 65}


# ---------------------------------------------------------------------------
# Critère 11 — étape, dernier geste, temps écoulé, ordre et comptes rendus
# par l'API (déjà couvert par les critères 4-9 ; ce test les rassemble)
# ---------------------------------------------------------------------------


class TestCritere11ChampsEtComptesRendusParLApi:
    def test_une_candidature_porte_tous_les_champs_decides_par_lapi(
        self, client, db_path, monkeypatch
    ):
        _figer_horloge(monkeypatch, "2026-10-21T10:00:00+00:00")
        _insert_offer(db_path, 70, title="Dev", company="Acme")
        _retenir(client, 70, effet_at="2026-10-18T09:00:00+00:00")

        resp = client.get(
            "/offers", params={"verdict": "retenu", "sort": "suivi", "order": "asc"}
        )
        row = resp.json()[0]
        assert row.get("etape") == "retenue"
        assert row.get("dernier_geste_libelle") == "Retenir"
        assert row.get("dernier_geste_effet_at") == "2026-10-18T09:00:00+00:00"
        assert row.get("temps_depuis_libelle") == "il y a 3 j"

        counts = client.get("/offers/suivi/compte-etapes").json()
        assert counts.get("retenue") == 1


# ---------------------------------------------------------------------------
# Critère 13 — le tri par verdict range une offre qui ne porte qu'une revue
# hors périmètre, sans geste, au rang de sa revue (mutant V4)
# ---------------------------------------------------------------------------


class TestCritere13TriVerdictRevueSansGeste:
    def test_api_offres_revue_seule_rangee_au_rang_de_sa_revue(self, client, db_path):
        _insert_offer(db_path, 80)  # revue seule, aucun geste
        _insert_offer(db_path, 81)  # retenue + même revue
        _insert_offer(db_path, 82)  # écartée, sans revue
        _insert_offer(db_path, 83)  # retenue, sans revue

        client.put("/offers/80/verdict", json={"status": "hors_perimetre_faux_pos"})
        _retenir(client, 81)
        client.put("/offers/81/verdict", json={"status": "hors_perimetre_faux_pos"})
        client.put("/offers/82/verdict", json={"status": "ecartee"})
        _retenir(client, 83)

        resp = client.get("/offers", params={"sort": "verdict", "order": "asc"})
        ids = [r["id"] for r in resp.json()]

        assert ids.index(83) < ids.index(80)  # retenu(1) < revue(2)
        # mutant V4 : sans le correctif, 80 (revue seule) retombe au rang 5,
        # après 82 (écartée, rang 4) — ce que ce test interdit.
        assert ids.index(80) < ids.index(82)
        assert ids.index(81) < ids.index(82)

    def test_export_offres_revue_seule_rangee_au_rang_de_sa_revue(
        self, client, db_path
    ):
        _insert_offer(db_path, 90, title="Titre90")
        _insert_offer(db_path, 91, title="Titre91")
        _insert_offer(db_path, 92, title="Titre92")

        client.put("/offers/90/verdict", json={"status": "hors_perimetre_faux_pos"})
        client.put("/offers/92/verdict", json={"status": "ecartee"})

        resp = client.get(
            "/export/offers",
            params={"sort": "verdict", "order": "asc", "include": "verdict"},
        )
        assert resp.status_code == 200
        text = resp.text
        assert text.index("Titre90") < text.index("Titre92")
