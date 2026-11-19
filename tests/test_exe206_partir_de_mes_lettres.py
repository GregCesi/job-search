"""Tests EXE-206 — partir d'une de mes lettres prêtes, copiée telle quelle.

Côté API et service : le bouton de la carte Lettre (critères 1 à 3, rendu par
l'API), la liste des lettres marquées Prêtes sur d'autres offres (critères 4 à
6), la copie (critères 7 à 12) et l'absence de tout appel de modèle (critère
13). Les critères vus à l'écran ont aussi leur test navigateur
(`test_exe206_navigateur.py`). Base sous tmp_path (fixture autouse
`_isolate_db_path` de conftest), aucune lecture ni écriture sous data/.
"""

import sqlite3
from datetime import datetime, timezone

import claude_agent_sdk
import ollama
import pytest
from fastapi.testclient import TestClient

import orchestrator.job_search.paths as paths_mod
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage
from tests.pdf_inspect import extract_text

TEXTE_SIA = (
    "Madame, Monsieur,\n\nChez Capgemini, j'ai appris à livrer vite. "
    "Je serais ravi de rejoindre votre équipe le 3 novembre 2026.\n\nGrégoire"
)

LIBELLE_BOUTON = "Partir d'une de mes lettres"
RAISON_AUCUNE = "Aucune lettre marquée Prête à reprendre"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@pytest.fixture
def db_path():
    path = storage_db.DB_PATH
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def client(db_path):
    from api.main import app

    return TestClient(app)


@pytest.fixture
def tournures_path(tmp_path, monkeypatch):
    path = tmp_path / "tournures.txt"
    path.write_text("je serais ravi\n", encoding="utf-8")
    monkeypatch.setattr(paths_mod, "LETTRE_TOURNURES_PATH", path)
    return path


@pytest.fixture
def coordonnees_path(tmp_path, monkeypatch):
    path = tmp_path / "coordonnees.txt"
    path.write_text(
        "nom: Grégoire Marchand\n"
        "mail: gregoire@example.com\n"
        "telephone: +33 6 00 00 00 00\n"
        "ville: Strasbourg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", path)
    return path


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def insert_offer(db_path, offer_id, title=None, company=None, retenue=True):
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, 'Texte de l offre')",
            (
                offer_id,
                str(offer_id),
                title or f"Poste {offer_id}",
                company or f"Entreprise {offer_id}",
            ),
        )
        if retenue:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def insert_lettre(
    db_path,
    offer_id,
    texte="Texte de la lettre.",
    marque_pret_at=None,
    statut="done",
    decision="demandee",
    nb_versions=1,
):
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, texte, "
            "nb_mots, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                offer_id,
                statut,
                decision,
                marque_pret_at,
                texte,
                len(texte.split()),
                _now(),
            ),
        )
        for _ in range(nb_versions):
            conn.execute(
                "INSERT INTO lettre_versions (offer_id, texte, origine, created_at) "
                "VALUES (?, ?, 'modele', ?)",
                (offer_id, texte, _now()),
            )
        conn.commit()
    finally:
        conn.close()


def _bouton(carte: dict, nom: str) -> dict | None:
    for b in carte["boutons"]:
        if b["bouton"] == nom:
            return b
    return None


def _carte(client, offer_id) -> dict:
    res = client.get(f"/offers/{offer_id}/pieces")
    assert res.status_code == 200, res.text
    return res.json()["lettre_carte"]


def _bouton_partir(client, offer_id) -> dict | None:
    carte = _carte(client, offer_id)
    for b in carte["boutons"]:
        if b["libelle"] == LIBELLE_BOUTON:
            return b
    return None


# ---------------------------------------------------------------------------
# Le bouton (critères 1 à 3)
# ---------------------------------------------------------------------------


class TestCritere1BoutonACoteDesDeuxAutres:
    def test_lettre_a_decider_rend_le_bouton_visible_avec_les_deux_autres(
        self, client, db_path
    ):
        insert_offer(db_path, 10)
        insert_offer(db_path, 11)
        insert_lettre(db_path, 11, marque_pret_at=_now())

        carte = _carte(client, 10)
        visibles = [b["libelle"] for b in carte["boutons"] if b["visible"]]
        assert LIBELLE_BOUTON in visibles
        assert "Générer la lettre" in visibles
        assert "Ne pas faire de lettre pour cette annonce" in visibles
        assert _bouton_partir(client, 10)["actif"] is True

    def test_lettre_demandee_ne_montre_pas_le_bouton(self, client, db_path):
        insert_offer(db_path, 12)
        insert_offer(db_path, 13)
        insert_lettre(db_path, 13, marque_pret_at=_now())
        insert_lettre(db_path, 12, statut="aucune", decision="demandee")

        bouton = _bouton_partir(client, 12)
        assert bouton is None or bouton["visible"] is False


class TestCritere2InactifSansLettrePrete:
    def test_visible_inactif_avec_raison(self, client, db_path):
        insert_offer(db_path, 20)
        insert_offer(db_path, 21)
        # Lettre générée mais non Prête : ne compte pas.
        insert_lettre(db_path, 21, marque_pret_at=None)

        bouton = _bouton_partir(client, 20)
        assert bouton is not None
        assert bouton["visible"] is True
        assert bouton["actif"] is False
        assert bouton["raison"] == RAISON_AUCUNE

    def test_seule_lettre_prete_est_celle_de_l_offre_courante(self, client, db_path):
        insert_offer(db_path, 22)
        insert_lettre(
            db_path, 22, statut="aucune", decision="a_decider", marque_pret_at=_now()
        )

        bouton = _bouton_partir(client, 22)
        assert bouton["visible"] is True
        assert bouton["actif"] is False
        assert bouton["raison"] == RAISON_AUCUNE


class TestCritere3PlusAfficheApresCopie:
    def test_apres_copie_le_bouton_disparait(self, client, db_path):
        insert_offer(db_path, 30)
        insert_offer(db_path, 31)
        insert_lettre(db_path, 31, texte=TEXTE_SIA, marque_pret_at=_now())

        res = client.post("/offers/30/lettre/copier", json={"source_offer_id": 31})
        assert res.status_code == 200, res.text

        bouton = _bouton_partir(client, 30)
        assert bouton is None or bouton["visible"] is False
        assert _carte(client, 30)["statut"] == "generee"


# ---------------------------------------------------------------------------
# La liste (critères 4 à 6)
# ---------------------------------------------------------------------------


class TestCritere4a6Liste:
    def test_trois_pretes_une_non_prete_trois_lignes_rangees(self, client, db_path):
        insert_offer(db_path, 40)
        insert_offer(db_path, 41, title="Dev Python", company="Capgemini")
        insert_offer(db_path, 42, title="Ingénieur IA", company="SFEIR")
        insert_offer(db_path, 43, title="Data engineer", company="Sia")
        insert_offer(db_path, 44, title="Autre", company="NonPrete")
        insert_lettre(db_path, 41, marque_pret_at="2026-10-01T10:00:00+00:00")
        insert_lettre(db_path, 42, marque_pret_at="2026-11-01T10:00:00+00:00")
        insert_lettre(db_path, 43, marque_pret_at="2026-10-15T10:00:00+00:00")
        insert_lettre(db_path, 44, marque_pret_at=None)

        res = client.get("/offers/40/lettre/mes-lettres")
        assert res.status_code == 200, res.text
        lignes = res.json()
        assert len(lignes) == 3
        assert [ligne["entreprise"] for ligne in lignes] == [
            "SFEIR",
            "Sia",
            "Capgemini",
        ]
        assert [ligne["intitule"] for ligne in lignes] == [
            "Ingénieur IA",
            "Data engineer",
            "Dev Python",
        ]
        assert [ligne["marque_pret_at"] for ligne in lignes] == [
            "2026-11-01T10:00:00+00:00",
            "2026-10-15T10:00:00+00:00",
            "2026-10-01T10:00:00+00:00",
        ]
        assert [ligne["offer_id"] for ligne in lignes] == [42, 43, 41]

    def test_liste_exclut_l_offre_courante_et_les_textes_vides(self, client, db_path):
        insert_offer(db_path, 45)
        insert_offer(db_path, 46)
        insert_lettre(
            db_path, 45, statut="aucune", decision="a_decider", marque_pret_at=_now()
        )
        insert_lettre(db_path, 46, texte="   ", marque_pret_at=_now())

        res = client.get("/offers/45/lettre/mes-lettres")
        assert res.status_code == 200, res.text
        assert res.json() == []


# ---------------------------------------------------------------------------
# La copie (critères 7 à 12)
# ---------------------------------------------------------------------------


@pytest.fixture
def copie(client, db_path, tournures_path):
    insert_offer(db_path, 50, title="Développeur backend", company="Aerospacelab")
    insert_offer(db_path, 51, title="Dev Python", company="Capgemini")
    insert_lettre(db_path, 51, texte=TEXTE_SIA, marque_pret_at=_now(), nb_versions=2)
    res = client.post("/offers/50/lettre/copier", json={"source_offer_id": 51})
    assert res.status_code == 200, res.text
    return res.json()


class TestCritere7TexteMotPourMot:
    def test_texte_copie_mot_pour_mot(self, client, copie):
        assert copie["texte"] == TEXTE_SIA
        lettre = client.get("/offers/50/lettre").json()
        assert lettre["texte"] == TEXTE_SIA
        assert lettre["statut"] == "done"


class TestCritere8PasMarqueePrete:
    def test_copie_non_marquee_prete(self, client, copie):
        pieces = client.get("/offers/50/pieces").json()
        assert pieces["lettre"]["statut"] != "prete"
        assert pieces["lettre"]["marque_pret_le"] is None


class TestCritere9VersionMoi:
    def test_historique_porte_une_version_moi_du_texte(self, client, copie):
        versions = client.get("/offers/50/lettre/versions").json()
        assert len(versions) == 1
        assert versions[0]["origine"] == "moi"
        assert versions[0]["texte"] == TEXTE_SIA


class TestCritere10MotsEtTournures:
    def test_nb_mots_et_tournures_du_texte_copie(self, client, copie):
        lettre = client.get("/offers/50/lettre").json()
        assert lettre["nb_mots"] == len(TEXTE_SIA.split())
        assert lettre["tournures_signalees"] == ["Je serais ravi"]


class TestCritere11PdfDeLOffreCourante:
    def test_pdf_objet_et_entete_de_l_offre_courante(
        self, client, copie, coordonnees_path
    ):
        res = client.get("/offers/50/lettre/pdf")
        assert res.status_code == 200, res.text
        texte = extract_text(res.content)
        assert "Développeur backend" in texte
        assert "Aerospacelab" in texte
        assert "Dev Python" not in texte


class TestCritere12OrigineIntacte:
    def test_modifier_la_copie_ne_touche_pas_l_origine(self, client, db_path, copie):
        conn = _conn(db_path)
        try:
            avant = conn.execute(
                "SELECT texte, marque_pret_at FROM lettres WHERE offer_id = 51"
            ).fetchone()
            avant = (avant["texte"], avant["marque_pret_at"])
        finally:
            conn.close()

        res = client.put(
            "/offers/50/lettre/texte", json={"texte": TEXTE_SIA + " Modifié."}
        )
        assert res.status_code == 200, res.text

        conn = _conn(db_path)
        try:
            apres = conn.execute(
                "SELECT texte, marque_pret_at FROM lettres WHERE offer_id = 51"
            ).fetchone()
            nb_versions = conn.execute(
                "SELECT COUNT(*) FROM lettre_versions WHERE offer_id = 51"
            ).fetchone()[0]
        finally:
            conn.close()
        assert (apres["texte"], apres["marque_pret_at"]) == avant
        assert apres["marque_pret_at"] is not None
        assert nb_versions == 2


# ---------------------------------------------------------------------------
# Critère 13 — aucun appel de modèle
# ---------------------------------------------------------------------------


class TestCritere13AucunAppelDeModele:
    def test_copie_sans_appel_claude_ni_ollama(self, client, db_path, monkeypatch):
        import orchestrator.job_search.lettre.boucle as boucle

        appels: list[str] = []

        def _espion(nom):
            def _appel(*_a, **_k):
                appels.append(nom)
                raise AssertionError(f"appel de modèle inattendu : {nom}")

            return _appel

        monkeypatch.setattr(claude_agent_sdk, "query", _espion("claude.query"))
        monkeypatch.setattr(boucle, "query", _espion("boucle.query"))
        monkeypatch.setattr(ollama, "chat", _espion("ollama.chat"))
        monkeypatch.setattr(ollama.Client, "chat", _espion("ollama.Client.chat"))

        insert_offer(db_path, 60)
        insert_offer(db_path, 61)
        insert_lettre(db_path, 61, texte=TEXTE_SIA, marque_pret_at=_now())

        res = client.post("/offers/60/lettre/copier", json={"source_offer_id": 61})
        assert res.status_code == 200, res.text
        assert appels == []
        assert client.get("/offers/60/lettre").json()["texte"] == TEXTE_SIA


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver : copie refusée hors de son cas
# ---------------------------------------------------------------------------


class TestRefus:
    def test_source_non_prete_refusee(self, client, db_path):
        insert_offer(db_path, 70)
        insert_offer(db_path, 71)
        insert_lettre(db_path, 71, marque_pret_at=None)

        res = client.post("/offers/70/lettre/copier", json={"source_offer_id": 71})
        assert res.status_code == 409
        assert client.get("/offers/70/lettre").status_code == 404

    def test_lettre_deja_demandee_refusee(self, client, db_path):
        insert_offer(db_path, 72)
        insert_offer(db_path, 73)
        insert_lettre(db_path, 72, texte="Ma lettre générée.", marque_pret_at=None)
        insert_lettre(db_path, 73, texte=TEXTE_SIA, marque_pret_at=_now())

        res = client.post("/offers/72/lettre/copier", json={"source_offer_id": 73})
        assert res.status_code == 409
        assert client.get("/offers/72/lettre").json()["texte"] == "Ma lettre générée."
