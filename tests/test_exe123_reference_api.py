"""Tests EXE-123 — relecture du jeu de référence via l'API (critères 1 à 10).

Aucun test n'appelle Ollama ni ne lit/écrit sous data/ : chaque test pointe son
propre fichier de jeu et sa propre base SQLite (tmp_path), monkeypatchées sur
les modules qui les consomment (api.reference.JEU_PATH, api.db.DB_PATH).
"""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.db as api_db
import api.reference as api_reference
from orchestrator.job_search.reference.dataset import ReferenceEntry, load_jeu, save_jeu
from orchestrator.job_search.sources.base import ExtractedFacts, TechRequirement
from orchestrator.job_search.storage.db import init_db

FACTS = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[TechRequirement(name="python", importance="core")],
    domain="ai_engineering",
    role_level="ic",
)

CORRECTED = {
    "seniority_required": "senior",
    "techs_required": [{"name": "rust", "importance": "core"}],
    "domain": "backend",
    "role_level": "ic",
    "langues_requises": [],
    "parse_failed": False,
}


def _insert_offer(conn, offer_id, title, description, facts):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title, description, "
        "extracted_facts_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            offer_id,
            "france_travail",
            f"FT-{offer_id}",
            f"fp-{offer_id}",
            title,
            description,
            facts.model_dump_json() if facts else None,
            "2026-10-01T00:00:00+00:00",
        ),
    )
    conn.commit()


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    monkeypatch.setattr(api_db, "DB_PATH", path)
    return path


@pytest.fixture
def jeu_path(tmp_path, monkeypatch):
    path = tmp_path / "jeu.json"
    monkeypatch.setattr(api_reference, "JEU_PATH", path)
    return path


@pytest.fixture
def client(db_path, jeu_path):
    # Import local : api.main inclut d'autres routeurs qui se connectent à des
    # ressources à l'import — il ne doit s'exécuter qu'une fois DB_PATH et
    # JEU_PATH monkeypatchés (même précaution que test_cv_exe63.py).
    import api.main as api_main

    return TestClient(api_main.app)


# ---------------------------------------------------------------------------
# Critère 1 — liste des offres du jeu + compte relues/total
# ---------------------------------------------------------------------------


def test_critere1_liste_les_entrees_avec_compte(client, jeu_path):
    entries = {
        "1": ReferenceEntry(title="Dev IA", text="Texte 1", attendu=FACTS, relu=True),
        "2": ReferenceEntry(
            title="Dev Python", text="Texte 2", attendu=FACTS, relu=False
        ),
    }
    save_jeu(entries, jeu_path)

    resp = client.get("/reference")

    assert resp.status_code == 200
    body = resp.json()
    assert body["relues"] == 1
    assert body["total"] == 2
    by_id = {e["id"]: e for e in body["entries"]}
    assert by_id[1] == {"id": 1, "title": "Dev IA", "relu": True}
    assert by_id[2] == {"id": 2, "title": "Dev Python", "relu": False}


# ---------------------------------------------------------------------------
# Critère 2 — lecture d'une offre du jeu
# ---------------------------------------------------------------------------


def test_critere2_lit_titre_texte_attendu(client, jeu_path):
    save_jeu(
        {"1": ReferenceEntry(title="Dev IA", text="Texte complet", attendu=FACTS)},
        jeu_path,
    )

    resp = client.get("/reference/1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Dev IA"
    assert body["text"] == "Texte complet"
    assert body["attendu"]["domain"] == "ai_engineering"
    assert body["attendu"]["seniority_required"] == "intermediate"


def test_critere2_404_si_absente(client, jeu_path):
    resp = client.get("/reference/999")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Critères 3, 4, 5 — enregistrement d'un attendu corrigé + marque de relecture
# ---------------------------------------------------------------------------


def test_critere3_corrige_et_marque_relu(client, jeu_path):
    save_jeu({"1": ReferenceEntry(title="T", text="X", attendu=FACTS)}, jeu_path)

    resp = client.put("/reference/1", json={"attendu": CORRECTED, "relu": True})

    assert resp.status_code == 204
    entries = load_jeu(jeu_path)
    assert entries["1"].relu is True
    assert entries["1"].attendu.domain == "backend"
    assert entries["1"].attendu.seniority_required.value == "senior"


def test_critere4_corrige_sans_marquer_relu(client, jeu_path):
    save_jeu({"1": ReferenceEntry(title="T", text="X", attendu=FACTS)}, jeu_path)

    resp = client.put("/reference/1", json={"attendu": CORRECTED, "relu": False})

    assert resp.status_code == 204
    entries = load_jeu(jeu_path)
    assert entries["1"].relu is False
    assert entries["1"].attendu.domain == "backend"


def test_critere5_repasse_non_relu_sans_changer_attendu(client, jeu_path):
    save_jeu(
        {"1": ReferenceEntry(title="T", text="X", attendu=FACTS, relu=True)}, jeu_path
    )
    attendu_inchange = json.loads(FACTS.model_dump_json())

    resp = client.put("/reference/1", json={"attendu": attendu_inchange, "relu": False})

    assert resp.status_code == 204
    entries = load_jeu(jeu_path)
    assert entries["1"].relu is False
    assert entries["1"].attendu == FACTS


def test_titre_et_texte_jamais_modifies_par_put(client, jeu_path):
    save_jeu(
        {
            "1": ReferenceEntry(
                title="Titre original", text="Texte original", attendu=FACTS
            )
        },
        jeu_path,
    )

    client.put(
        "/reference/1",
        json={
            "attendu": CORRECTED,
            "relu": True,
            "title": "Autre titre",
            "text": "Autre texte",
        },
    )

    entries = load_jeu(jeu_path)
    assert entries["1"].title == "Titre original"
    assert entries["1"].text == "Texte original"


# ---------------------------------------------------------------------------
# Critère 6 — refus d'une valeur hors vocabulaire
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("domain", "quantum_sorcery"),
        ("seniority_required", "ultra_senior"),
        ("role_level", "ceo"),
    ],
)
def test_critere6_refuse_valeur_hors_vocabulaire(client, jeu_path, field, bad_value):
    save_jeu({"1": ReferenceEntry(title="T", text="X", attendu=FACTS)}, jeu_path)
    attendu = json.loads(FACTS.model_dump_json())
    attendu[field] = bad_value

    resp = client.put("/reference/1", json={"attendu": attendu, "relu": True})

    assert resp.status_code == 422
    assert bad_value in json.dumps(resp.json())
    entries = load_jeu(jeu_path)
    assert entries["1"].attendu == FACTS
    assert entries["1"].relu is False


def test_critere6_refuse_importance_hors_vocabulaire(client, jeu_path):
    save_jeu({"1": ReferenceEntry(title="T", text="X", attendu=FACTS)}, jeu_path)
    attendu = json.loads(FACTS.model_dump_json())
    attendu["techs_required"] = [{"name": "python", "importance": "obligatoire"}]

    resp = client.put("/reference/1", json={"attendu": attendu, "relu": True})

    assert resp.status_code == 422
    entries = load_jeu(jeu_path)
    assert entries["1"].attendu == FACTS


# ---------------------------------------------------------------------------
# Critères 7, 8, 9 — ajout d'une offre au jeu depuis sa page
# ---------------------------------------------------------------------------


def test_critere7_ajoute_offre_avec_faits_prereplie_non_relue(
    client, db_path, jeu_path
):
    conn = sqlite3.connect(db_path)
    _insert_offer(conn, 10, "Dev Rust", "Texte Rust", FACTS)
    conn.close()

    resp = client.post("/offers/10/reference")

    assert resp.status_code == 200
    assert resp.json() == {"statut": "ajoutee"}
    entries = load_jeu(jeu_path)
    assert entries["10"].title == "Dev Rust"
    assert entries["10"].text == "Texte Rust"
    assert entries["10"].relu is False


def test_critere8_offre_deja_presente_ne_change_rien(client, db_path, jeu_path):
    conn = sqlite3.connect(db_path)
    _insert_offer(conn, 11, "Dev Rust", "Texte", FACTS)
    conn.close()
    client.post("/offers/11/reference")
    entries_avant = load_jeu(jeu_path)
    entries_avant["11"].relu = True
    save_jeu(entries_avant, jeu_path)

    resp = client.post("/offers/11/reference")

    assert resp.status_code == 200
    assert resp.json() == {"statut": "deja_presente"}
    entries = load_jeu(jeu_path)
    assert entries["11"].relu is True  # inchangée


def test_critere9_offre_sans_faits_nentre_pas(client, db_path, jeu_path):
    conn = sqlite3.connect(db_path)
    _insert_offer(conn, 12, "Dev sans faits", "Texte", None)
    conn.close()

    resp = client.post("/offers/12/reference")

    assert resp.status_code == 200
    assert resp.json() == {"statut": "sans_faits"}
    entries = load_jeu(jeu_path)
    assert "12" not in entries


def test_ajout_necrit_rien_dans_offers(client, db_path, jeu_path):
    conn = sqlite3.connect(db_path)
    _insert_offer(conn, 13, "Dev IA", "Texte original", FACTS)
    avant = conn.execute(
        "SELECT title, description, extracted_facts_json FROM offers WHERE id = 13"
    ).fetchone()
    conn.close()

    client.post("/offers/13/reference")

    conn = sqlite3.connect(db_path)
    apres = conn.execute(
        "SELECT title, description, extracted_facts_json FROM offers WHERE id = 13"
    ).fetchone()
    conn.close()
    assert avant == apres


# ---------------------------------------------------------------------------
# Critère 10 — le rejeu en ligne de commande lit l'attendu corrigé par l'API
# ---------------------------------------------------------------------------


def test_critere10_le_rejeu_lit_lattendu_corrige_par_lapi(client, jeu_path):
    save_jeu({"1": ReferenceEntry(title="T", text="X", attendu=FACTS)}, jeu_path)

    client.put("/reference/1", json={"attendu": CORRECTED, "relu": True})

    # Même fonction que celle utilisée par le rejeu CLI (replay_jeu charge via
    # load_jeu sur le même fichier) : la correction de l'API s'y voit sans rien
    # d'autre.
    entries = load_jeu(jeu_path)
    assert entries["1"].attendu.domain == "backend"
    assert entries["1"].attendu.seniority_required.value == "senior"
    assert entries["1"].relu is True
